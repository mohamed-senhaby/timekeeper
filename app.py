import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
from io import BytesIO
import time as time_module
import hashlib
# Google Sheets integration
import gspread
from google.oauth2.service_account import Credentials

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
WORK_START_TIME = time(9, 0)  # 9:00 AM - configurable start time
STANDARD_WORK_HOURS = 8  # Standard work day hours

# Action types
ACTION_CHECK_IN = "Check In"
ACTION_CHECK_OUT = "Check Out"
ACTION_BREAK_START = "Break Start"
ACTION_BREAK_END = "Break End"
ACTION_SITE_VISIT_START = "Site Visit Start"
ACTION_SITE_VISIT_END = "Site Visit End"

# Load secrets from .streamlit/secrets.toml
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123")
SHEET_URL = st.secrets.get("SHEET_URL", "")

# --- Functions ---

@st.cache_resource
def get_gsheet_client():
    """Returns an authorized gspread client (cached)."""
    # Load credentials from Streamlit secrets
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(dict(creds_dict), scopes=SCOPES)
    return gspread.authorize(creds)

def retry_operation(operation, max_retries=3, delay=1):
    """Retry an operation with exponential backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time_module.sleep(delay * (2 ** attempt))
    raise last_error

def hash_password(password):
    """Hash a password for secure storage."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_employees_worksheet():
    """Get or create the Employees worksheet."""
    client = get_gsheet_client()
    sh = client.open_by_url(SHEET_URL)

    # Try to get the Employees worksheet
    try:
        worksheet = sh.worksheet("Employees")
    except gspread.exceptions.WorksheetNotFound:
        # Create the worksheet with headers
        worksheet = sh.add_worksheet(title="Employees", rows=100, cols=3)
        worksheet.append_row(["Username", "PasswordHash", "DisplayName"])

    return worksheet

@st.cache_data(ttl=60)
def load_employees_from_sheet():
    """Load employee credentials from Google Sheets."""
    def _load():
        worksheet = get_employees_worksheet()
        data = worksheet.get_all_records()
        credentials = {}
        for row in data:
            username = row.get('Username', '').lower().strip()
            if username:
                credentials[username] = {
                    'password_hash': row.get('PasswordHash', ''),
                    'name': row.get('DisplayName', '')
                }
        return credentials

    try:
        return retry_operation(_load)
    except Exception as e:
        st.error(f"Failed to load employees: {e}")
        return {}

def clear_employees_cache():
    """Clear the employees cache."""
    load_employees_from_sheet.clear()

def get_employee_credentials():
    """Get employee credentials from Google Sheets."""
    return load_employees_from_sheet()

def get_employees():
    """Get the list of employee names."""
    credentials = get_employee_credentials()
    return [data['name'] for data in credentials.values()]

def authenticate_employee(username, password):
    """Authenticate an employee by username and password."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower in credentials:
        if credentials[username_lower]['password_hash'] == hash_password(password):
            return credentials[username_lower]['name']
    return None

def add_employee(username, password, display_name):
    """Add a new employee to Google Sheets."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower in credentials:
        return False, "Username already exists!"
    if not username_lower or not password or not display_name:
        return False, "All fields are required!"

    def _add():
        worksheet = get_employees_worksheet()
        password_hash = hash_password(password)
        worksheet.append_row([username_lower, password_hash, display_name.strip()])

    try:
        retry_operation(_add)
        clear_employees_cache()
        return True, f"Employee {display_name} added successfully!"
    except Exception as e:
        return False, f"Failed to add employee: {e}"

def remove_employee(username):
    """Remove an employee from Google Sheets."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower not in credentials:
        return False, "Employee not found!"

    def _remove():
        worksheet = get_employees_worksheet()
        # Find the row with this username
        cell = worksheet.find(username_lower, in_column=1)
        if cell:
            worksheet.delete_rows(cell.row)

    try:
        retry_operation(_remove)
        clear_employees_cache()
        return True, "Employee removed successfully!"
    except Exception as e:
        return False, f"Failed to remove employee: {e}"

def change_employee_password(username, new_password):
    """Change an employee's password in Google Sheets."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower not in credentials:
        return False, "Employee not found!"

    def _change():
        worksheet = get_employees_worksheet()
        # Find the row with this username
        cell = worksheet.find(username_lower, in_column=1)
        if cell:
            # Update the password hash (column 2)
            worksheet.update_cell(cell.row, 2, hash_password(new_password))

    try:
        retry_operation(_change)
        clear_employees_cache()
        return True, "Password changed successfully!"
    except Exception as e:
        return False, f"Failed to change password: {e}"

def logout_employee():
    """Log out the current employee."""
    if 'logged_in_employee' in st.session_state:
        del st.session_state.logged_in_employee
    if 'logged_in_username' in st.session_state:
        del st.session_state.logged_in_username

@st.cache_data(ttl=60)
def load_data():
    """Loads the time logs from Google Sheets (cached for 60 seconds)."""
    def _load():
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(0)
        data = worksheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=['Employee', 'Action', 'Timestamp'])
        return pd.DataFrame(data)

    try:
        return retry_operation(_load)
    except Exception as e:
        st.error(f"Failed to load data from Google Sheets: {e}")
        return pd.DataFrame(columns=['Employee', 'Action', 'Timestamp'])

def clear_data_cache():
    """Clear the load_data cache to force fresh data."""
    load_data.clear()

def save_log(employee, action):
    """Saves a new time log entry to the Google Sheet with retry logic."""
    def _save():
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(0)
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        new_row = [employee, action, now_str]
        worksheet.append_row(new_row)
        return now

    result = retry_operation(_save)
    clear_data_cache()
    return result

def get_employee_status(employee, df=None):
    """Get the current status of an employee."""
    if df is None:
        df = load_data()

    if df.empty:
        return None, None

    df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
    today = datetime.now().date()
    today_records = df[
        (df['Employee'] == employee) &
        (df['Timestamp'].dt.date == today)
    ].sort_values('Timestamp')

    if today_records.empty:
        return None, None

    last_action = today_records.iloc[-1]['Action']
    last_time = today_records.iloc[-1]['Timestamp']
    return last_action, last_time

def is_late_arrival(check_in_time):
    """Check if the check-in time is after the configured start time."""
    if check_in_time is None:
        return False
    return check_in_time.time() > WORK_START_TIME

def calculate_work_sessions(employee_df, include_breaks=True):
    """Calculate work sessions by pairing Check In and Check Out events."""
    if employee_df.empty:
        return pd.DataFrame(), 0, 0, 0

    employee_df = employee_df.sort_values(by='Timestamp')
    employee_df['Timestamp'] = pd.to_datetime(employee_df['Timestamp'])

    sessions = []
    check_in_time = None
    break_start = None
    site_visit_start = None
    total_break_time = timedelta()
    total_site_visit_time = timedelta()

    for _, row in employee_df.iterrows():
        action = row['Action']
        timestamp = row['Timestamp']

        if action == ACTION_CHECK_IN:
            check_in_time = timestamp
        elif action == ACTION_CHECK_OUT and check_in_time is not None:
            check_out_time = timestamp
            duration = check_out_time - check_in_time
            if include_breaks:
                duration = duration - total_break_time
            sessions.append({
                'Check In': check_in_time,
                'Check Out': check_out_time,
                'Duration': duration,
                'Hours': duration.total_seconds() / 3600,
                'Break Time': total_break_time.total_seconds() / 3600,
                'Site Visit Time': total_site_visit_time.total_seconds() / 3600
            })
            check_in_time = None
            total_break_time = timedelta()
            total_site_visit_time = timedelta()
        elif action == ACTION_BREAK_START:
            break_start = timestamp
        elif action == ACTION_BREAK_END and break_start is not None:
            total_break_time += timestamp - break_start
            break_start = None
        elif action == ACTION_SITE_VISIT_START:
            site_visit_start = timestamp
        elif action == ACTION_SITE_VISIT_END and site_visit_start is not None:
            total_site_visit_time += timestamp - site_visit_start
            site_visit_start = None

    sessions_df = pd.DataFrame(sessions)
    total_hours = sessions_df['Hours'].sum() if not sessions_df.empty else 0
    total_break_hours = sessions_df['Break Time'].sum() if not sessions_df.empty else 0
    total_site_hours = sessions_df['Site Visit Time'].sum() if not sessions_df.empty else 0

    return sessions_df, total_hours, total_break_hours, total_site_hours

def calculate_overtime(hours_worked):
    """Calculate overtime hours beyond standard work hours."""
    if hours_worked > STANDARD_WORK_HOURS:
        return hours_worked - STANDARD_WORK_HOURS
    return 0

def get_week_dates():
    """Get the start and end dates of the current week."""
    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

def calculate_weekly_summary(df=None):
    """Calculate weekly hours for all employees."""
    if df is None:
        df = load_data()

    if df.empty:
        return pd.DataFrame()

    df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
    start_of_week, end_of_week = get_week_dates()

    weekly_data = []
    for employee in get_employees():
        emp_df = df[
            (df['Employee'] == employee) &
            (df['Timestamp'].dt.date >= start_of_week) &
            (df['Timestamp'].dt.date <= end_of_week)
        ]

        sessions_df, total_hours, break_hours, site_hours = calculate_work_sessions(emp_df)
        overtime = calculate_overtime(total_hours)

        weekly_data.append({
            'Employee': employee,
            'Hours Worked': round(total_hours, 2),
            'Break Time': round(break_hours, 2),
            'Site Visits': round(site_hours, 2),
            'Overtime': round(overtime, 2)
        })

    return pd.DataFrame(weekly_data)

def get_employee_history(employee, days=30):
    """Get the history of an employee for the last N days."""
    df = load_data()
    if df.empty:
        return pd.DataFrame()

    df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
    cutoff_date = datetime.now().date() - timedelta(days=days)

    emp_df = df[
        (df['Employee'] == employee) &
        (df['Timestamp'].dt.date >= cutoff_date)
    ].sort_values('Timestamp', ascending=False)

    return emp_df

def generate_excel_report(start_date=None, end_date=None):
    """Generate simple Excel report with employee hours for payment."""
    df = load_data()
    if df.empty:
        return None, None

    df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')

    # Apply date filter if provided
    if start_date and end_date:
        df = df[
            (df['Timestamp'].dt.date >= start_date) &
            (df['Timestamp'].dt.date <= end_date)
        ]

    if df.empty:
        return None, None

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Simple summary: Employee name and total hours worked
        summary_data = []
        for employee in get_employees():
            emp_df = df[df['Employee'] == employee]
            sessions_df, total_hours, break_hours, site_hours = calculate_work_sessions(emp_df)

            if total_hours > 0:
                summary_data.append({
                    'Employee': employee,
                    'Total Hours': round(total_hours, 2),
                    'Total Days (8h)': round(total_hours / 8, 2)
                })

        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Payment Summary', index=False)

        # Auto-adjust column widths for better readability
        worksheet = writer.sheets['Payment Summary']
        worksheet.column_dimensions['A'].width = 25  # Employee name
        worksheet.column_dimensions['B'].width = 15  # Total Hours
        worksheet.column_dimensions['C'].width = 18  # Total Days

    output.seek(0)
    return output, summary_df

# --- Google Sheets Upload Functions ---

def upload_df_to_gsheet(df, worksheet_index=0):
    """Upload a DataFrame to a Google Sheet worksheet with retry logic."""
    def _upload():
        safe_df = df.replace([float('inf'), float('-inf')], pd.NA)
        safe_df = safe_df.fillna("")
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(worksheet_index)
        worksheet.clear()
        worksheet.update([safe_df.columns.values.tolist()] + safe_df.values.tolist())

    retry_operation(_upload)

# --- Clear All Data Function ---

def clear_all_data(worksheet_index=0):
    """Clear all data from the Google Sheet and re-add headers."""
    def _clear():
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(worksheet_index)
        worksheet.clear()
        worksheet.append_row(['Employee', 'Action', 'Timestamp'])

    retry_operation(_clear)
    clear_data_cache()


def calculate_monthly_summary_df():
    """Calculate the monthly summary DataFrame for all employees."""
    df = load_data()
    monthly_summary = []
    for employee in get_employees():
        emp_df = df[df['Employee'] == employee]
        if emp_df.empty:
            continue
        emp_df['Timestamp'] = pd.to_datetime(emp_df['Timestamp'], errors='coerce')
        emp_df = emp_df.sort_values('Timestamp')
        sessions_df, _, _, _ = calculate_work_sessions(emp_df)
        if sessions_df.empty:
            continue
        sessions_df['Employee'] = employee
        sessions_df['Year'] = sessions_df['Check In'].dt.year
        sessions_df['Month'] = sessions_df['Check In'].dt.strftime('%B')
        grouped = sessions_df.groupby(['Employee', 'Year', 'Month'])['Hours'].sum().reset_index()
        if not grouped.empty:
            monthly_summary.append(grouped)

    if monthly_summary:
        monthly_summary_df = pd.concat(monthly_summary, ignore_index=True)
        if not monthly_summary_df.empty:
            monthly_summary_df = monthly_summary_df[['Employee', 'Year', 'Month', 'Hours']]
            monthly_summary_df = monthly_summary_df.rename(columns={'Hours': 'Total Hours'})
            return monthly_summary_df
    return pd.DataFrame(columns=['Employee', 'Year', 'Month', 'Total Hours'])

def upload_monthly_summary_to_gsheet():
    """Upload the monthly summary to Google Sheets with retry logic."""
    def _upload():
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        try:
            worksheet = sh.worksheet('Monthly Summary')
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title='Monthly Summary', rows=100, cols=10)
        worksheet.clear()
        monthly_summary_df = calculate_monthly_summary_df()
        worksheet.update([monthly_summary_df.columns.values.tolist()] + monthly_summary_df.values.tolist())

    retry_operation(_upload)

# --- Streamlit UI ---

st.set_page_config(page_title="Employee Time Clock", page_icon="⏰")

st.title("⏰ Employee Time Registration")

# Initialize session state for login
if 'logged_in_employee' not in st.session_state:
    st.session_state.logged_in_employee = None
if 'logged_in_username' not in st.session_state:
    st.session_state.logged_in_username = None
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False
if 'show_admin_login' not in st.session_state:
    st.session_state.show_admin_login = False

# Main Interface
if st.session_state.admin_logged_in:
    # Admin Panel on main page
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader("🔐 Admin Panel")
    with col_header2:
        if st.button("🚪 Logout Admin"):
            st.session_state.admin_logged_in = False
            st.rerun()

    # Weekly Summary View
    st.subheader("📅 Weekly Summary")
    weekly_df = calculate_weekly_summary()
    if not weekly_df.empty:
        start_of_week, end_of_week = get_week_dates()
        st.caption(f"Week: {start_of_week.strftime('%b %d')} - {end_of_week.strftime('%b %d, %Y')}")
        st.dataframe(weekly_df, use_container_width=True)
    else:
        st.info("No data for this week.")

    st.divider()
    st.subheader("📊 Download Reports")

    # Date range filter
    col_start, col_end = st.columns(2)
    with col_start:
        filter_start = st.date_input("From:", value=None, key="filter_start")
    with col_end:
        filter_end = st.date_input("To:", value=None, key="filter_end")

    if st.button("Generate Excel Report"):
        try:
            excel_data, summary_df = generate_excel_report(filter_start, filter_end)
            if excel_data is not None and summary_df is not None:
                date_suffix = ""
                if filter_start and filter_end:
                    date_suffix = f"_{filter_start.strftime('%Y%m%d')}_to_{filter_end.strftime('%Y%m%d')}"
                st.download_button(
                    label="📥 Download Excel Report",
                    data=excel_data,
                    file_name=f"time_report{date_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("No data available for the selected date range.")
        except Exception as e:
            st.error(f"Failed to generate report: {e}")

    st.divider()
    if st.checkbox("Show Raw Data"):
        st.subheader("All Logs")
        try:
            df_all = load_data()
            st.dataframe(df_all)
        except Exception as e:
            st.error(f"Failed to load data: {e}")

    st.divider()
    st.subheader("👥 Manage Employees")

    # Add new employee
    st.write("**Add New Employee:**")
    new_username = st.text_input("Username:", key="new_username")
    new_password = st.text_input("Password:", type="password", key="new_password")
    new_display_name = st.text_input("Display Name:", key="new_display_name")

    if st.button("➕ Add Employee"):
        if new_username and new_password and new_display_name:
            success, message = add_employee(new_username, new_password, new_display_name)
            if success:
                st.success(message)
                # Clear input fields
                del st.session_state.new_username
                del st.session_state.new_password
                del st.session_state.new_display_name
                st.rerun()
            else:
                st.warning(message)
        else:
            st.warning("Please fill in all fields.")

    # Remove employee
    st.write("**Remove Employee:**")
    credentials = get_employee_credentials()
    if credentials:
        usernames = list(credentials.keys())
        username_to_remove = st.selectbox("Select employee:", usernames, key="remove_emp")
        if st.button("➖ Remove Employee"):
            if len(credentials) > 1:
                success, message = remove_employee(username_to_remove)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.warning(message)
            else:
                st.warning("Cannot remove the last employee!")

    # Reset password
    st.write("**Reset Password:**")
    if credentials:
        username_for_reset = st.selectbox("Select employee:", usernames, key="reset_pwd_emp")
        new_pwd = st.text_input("New Password:", type="password", key="reset_pwd")
        if st.button("🔑 Reset Password"):
            if new_pwd:
                success, message = change_employee_password(username_for_reset, new_pwd)
                if success:
                    st.success(message)
                else:
                    st.warning(message)
            else:
                st.warning("Please enter a new password.")

    # Show current employees list
    st.write("**Current Employees:**")
    for uname, data in credentials.items():
        st.caption(f"• {data['name']} (@{uname})")

    st.divider()
    st.subheader("⚠️ Danger Zone")
    confirm_clear = st.checkbox("I confirm I want to delete ALL data", key="confirm_clear")
    if st.button("❌ Clear All Data", type="primary", disabled=not confirm_clear):
        try:
            clear_all_data()
            st.success("All data cleared from Google Sheet!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to clear data: {e}")

elif st.session_state.logged_in_employee is None:
    # Show login form
    if st.session_state.show_admin_login:
        # Admin login form
        st.subheader("🔐 Admin Login")

        admin_password = st.text_input("Admin Password:", type="password", key="admin_pwd")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🔓 Login as Admin", use_container_width=True):
                if admin_password == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.session_state.show_admin_login = False
                    st.rerun()
                else:
                    st.error("Invalid admin password!")
        with col_btn2:
            if st.button("⬅️ Back to Employee Login", use_container_width=True):
                st.session_state.show_admin_login = False
                st.rerun()
    else:
        # Employee login form
        st.subheader("🔑 Employee Login")

        col_login1, col_login2 = st.columns([2, 1])

        with col_login1:
            login_username = st.text_input("Username:", key="login_username")
            login_password = st.text_input("Password:", type="password", key="login_password")

            if st.button("🔓 Login", use_container_width=True):
                if login_username and login_password:
                    employee_name = authenticate_employee(login_username, login_password)
                    if employee_name:
                        st.session_state.logged_in_employee = employee_name
                        st.session_state.logged_in_username = login_username.lower().strip()
                        st.success(f"Welcome, {employee_name}!")
                        st.rerun()
                    else:
                        st.error("Invalid username or password!")
                else:
                    st.warning("Please enter both username and password.")

        with col_login2:
            st.info("💡 Contact your administrator if you forgot your password.")

        st.divider()
        if st.button("🔐 Login as Admin", use_container_width=True):
            st.session_state.show_admin_login = True
            st.rerun()

else:
    # User is logged in
    selected_employee = st.session_state.logged_in_employee

    # Header with logout
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader(f"👋 Welcome, {selected_employee}!")
    with col_header2:
        if st.button("🚪 Logout"):
            logout_employee()
            st.rerun()

    # Tabs for Time Log and History
    tab1, tab2, tab3 = st.tabs(["⏰ Log Time", "📜 My History", "⚙️ Settings"])

    with tab1:
        # Show current status and today's activity
        try:
            df_status = load_data()
            today = datetime.now().date()

            if not df_status.empty:
                df_status['Timestamp'] = pd.to_datetime(df_status['Timestamp'], errors='coerce')
                today_records = df_status[
                    (df_status['Employee'] == selected_employee) &
                    (df_status['Timestamp'].dt.date == today)
                ].sort_values('Timestamp')

                # Current status indicator
                if today_records.empty:
                    st.warning(f"📋 Status: You have not checked in today")
                else:
                    last_action = today_records.iloc[-1]['Action']
                    last_time = today_records.iloc[-1]['Timestamp']
                    last_time_str = last_time.strftime('%H:%M:%S')

                    # Status display based on last action
                    if last_action == ACTION_CHECK_IN:
                        st.success(f"🟢 Status: Currently checked in (since {last_time_str})")
                    elif last_action == ACTION_CHECK_OUT:
                        st.info(f"🔴 Status: Checked out (at {last_time_str})")
                    elif last_action == ACTION_BREAK_START:
                        st.warning(f"☕ Status: On break (since {last_time_str})")
                    elif last_action == ACTION_BREAK_END:
                        st.success(f"🟢 Status: Back from break (at {last_time_str})")
                    elif last_action == ACTION_SITE_VISIT_START:
                        st.info(f"🚗 Status: On site visit (since {last_time_str})")
                    elif last_action == ACTION_SITE_VISIT_END:
                        st.success(f"🟢 Status: Back from site visit (at {last_time_str})")

                    # Late arrival warning
                    check_ins = today_records[today_records['Action'] == ACTION_CHECK_IN]
                    if not check_ins.empty:
                        first_check_in = check_ins.iloc[0]['Timestamp']
                        if is_late_arrival(first_check_in):
                            st.error(f"⚠️ Late arrival! Checked in at {first_check_in.strftime('%H:%M:%S')} (after {WORK_START_TIME.strftime('%H:%M')})")

                    # Today's activity summary
                    with st.expander("📅 Today's Activity"):
                        check_ins = today_records[today_records['Action'] == ACTION_CHECK_IN]
                        check_outs = today_records[today_records['Action'] == ACTION_CHECK_OUT]
                        breaks_start = today_records[today_records['Action'] == ACTION_BREAK_START]
                        site_starts = today_records[today_records['Action'] == ACTION_SITE_VISIT_START]

                        sessions_df, hours_today, break_hours, site_hours = calculate_work_sessions(today_records)

                        # Show all work sessions
                        st.write(f"**Work Sessions:** {len(check_ins)}")
                        if not sessions_df.empty:
                            for idx, session in sessions_df.iterrows():
                                in_time = session['Check In'].strftime('%H:%M:%S')
                                out_time = session['Check Out'].strftime('%H:%M:%S') if pd.notna(session['Check Out']) else "Still working"
                                session_hours = f"{session['Hours']:.2f}h" if session['Hours'] > 0 else ""
                                st.caption(f"  Session {idx+1}: {in_time} - {out_time} {session_hours}")

                        # Show if currently in an open session
                        if len(check_ins) > len(check_outs):
                            last_check_in = check_ins.iloc[-1]['Timestamp']
                            hours_so_far = (datetime.now() - last_check_in).total_seconds() / 3600
                            st.write(f"**Current session:** {hours_so_far:.2f}h (still working)")

                        if not breaks_start.empty:
                            st.write(f"**Breaks taken:** {len(breaks_start)}")

                        if not site_starts.empty:
                            st.write(f"**Site visits:** {len(site_starts)}")

                        # Total hours
                        st.divider()
                        st.write(f"**Total Hours Today:** {hours_today:.2f}h")
                        overtime = calculate_overtime(hours_today)
                        if overtime > 0:
                            st.write(f"**Overtime:** {overtime:.2f}h")
                        if break_hours > 0:
                            st.write(f"**Break time:** {break_hours:.2f}h")
                        if site_hours > 0:
                            st.write(f"**Site visit time:** {site_hours:.2f}h")
            else:
                st.info(f"📋 No records yet")
        except Exception as e:
            st.error(f"Failed to load status: {e}")

        st.divider()

        # Action Buttons - Check In/Out
        st.write("**Main Actions:**")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("🟢 Check IN", use_container_width=True):
                try:
                    df_all = load_data()
                    today = datetime.now().date()
                    can_check_in = True

                    if not df_all.empty:
                        df_all['Timestamp'] = pd.to_datetime(df_all['Timestamp'], errors='coerce')
                        today_records = df_all[
                            (df_all['Employee'] == selected_employee) &
                            (df_all['Timestamp'].dt.date == today)
                        ].sort_values('Timestamp')

                        if not today_records.empty:
                            last_action = today_records.iloc[-1]['Action']
                            # Can only check in if last action was check out
                            if last_action != ACTION_CHECK_OUT:
                                can_check_in = False

                    if not can_check_in:
                        st.warning("You are already checked in! Please check out first.")
                    else:
                        time_logged = save_log(selected_employee, ACTION_CHECK_IN)
                        st.success(f"Checked IN at {time_logged.strftime('%Y-%m-%d %H:%M:%S')}")
                        if is_late_arrival(time_logged):
                            st.warning(f"⚠️ Late arrival! (after {WORK_START_TIME.strftime('%H:%M')})")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                            upload_monthly_summary_to_gsheet()
                        except Exception:
                            pass
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed to check in: {e}")

        with col2:
            if st.button("🔴 Check OUT", use_container_width=True):
                try:
                    df_all = load_data()
                    today = datetime.now().date()
                    can_check_out = False
                    error_message = ""

                    if not df_all.empty:
                        df_all['Timestamp'] = pd.to_datetime(df_all['Timestamp'], errors='coerce')
                        today_records = df_all[
                            (df_all['Employee'] == selected_employee) &
                            (df_all['Timestamp'].dt.date == today)
                        ].sort_values('Timestamp')

                        if today_records.empty:
                            error_message = "You have not checked in today!"
                        else:
                            last_action = today_records.iloc[-1]['Action']
                            if last_action == ACTION_CHECK_OUT:
                                error_message = "You have already checked out!"
                            elif last_action in [ACTION_CHECK_IN, ACTION_BREAK_END, ACTION_SITE_VISIT_END]:
                                can_check_out = True
                            elif last_action == ACTION_BREAK_START:
                                error_message = "Please end your break before checking out!"
                            elif last_action == ACTION_SITE_VISIT_START:
                                error_message = "Please end your site visit before checking out!"
                    else:
                        error_message = "You have not checked in today!"

                    if not can_check_out:
                        st.warning(error_message)
                    else:
                        time_logged = save_log(selected_employee, ACTION_CHECK_OUT)
                        st.info(f"Checked OUT at {time_logged.strftime('%Y-%m-%d %H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                            upload_monthly_summary_to_gsheet()
                        except Exception:
                            pass
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed to check out: {e}")

        # Break and Site Visit Buttons
        st.write("**Break & Site Visit:**")
        col3, col4, col5, col6 = st.columns(4)

        with col3:
            if st.button("☕ Start Break", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action in [ACTION_CHECK_IN, ACTION_BREAK_END, ACTION_SITE_VISIT_END]:
                        time_logged = save_log(selected_employee, ACTION_BREAK_START)
                        st.success(f"Break started at {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    elif last_action == ACTION_BREAK_START:
                        st.warning("Already on break!")
                    elif last_action == ACTION_SITE_VISIT_START:
                        st.warning("End site visit first!")
                    else:
                        st.warning("Please check in first!")
                except Exception as e:
                    st.error(f"Failed to start break: {e}")

        with col4:
            if st.button("☕ End Break", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action == ACTION_BREAK_START:
                        time_logged = save_log(selected_employee, ACTION_BREAK_END)
                        st.success(f"Break ended at {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    else:
                        st.warning("Not currently on break!")
                except Exception as e:
                    st.error(f"Failed to end break: {e}")

        with col5:
            if st.button("🚗 Start Site Visit", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action in [ACTION_CHECK_IN, ACTION_BREAK_END, ACTION_SITE_VISIT_END]:
                        time_logged = save_log(selected_employee, ACTION_SITE_VISIT_START)
                        st.success(f"Site visit started at {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    elif last_action == ACTION_SITE_VISIT_START:
                        st.warning("Already on site visit!")
                    elif last_action == ACTION_BREAK_START:
                        st.warning("End break first!")
                    else:
                        st.warning("Please check in first!")
                except Exception as e:
                    st.error(f"Failed to start site visit: {e}")

        with col6:
            if st.button("🚗 End Site Visit", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action == ACTION_SITE_VISIT_START:
                        time_logged = save_log(selected_employee, ACTION_SITE_VISIT_END)
                        st.success(f"Site visit ended at {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    else:
                        st.warning("Not currently on site visit!")
                except Exception as e:
                    st.error(f"Failed to end site visit: {e}")

    with tab2:
        # Personal History View
        st.subheader("📜 My Time History")

        # Date range selector
        history_days = st.selectbox("Show history for:", [7, 14, 30, 60, 90], index=2, format_func=lambda x: f"Last {x} days")

        history_df = get_employee_history(selected_employee, days=history_days)

        if not history_df.empty:
            # Summary statistics
            col_stat1, col_stat2, col_stat3 = st.columns(3)

            sessions_df, total_hours, break_hours, site_hours = calculate_work_sessions(history_df)

            with col_stat1:
                st.metric("Total Hours", f"{total_hours:.1f}h")
            with col_stat2:
                st.metric("Work Sessions", len(sessions_df))
            with col_stat3:
                overtime = max(0, total_hours - (history_days / 7 * 5 * STANDARD_WORK_HOURS))
                st.metric("Est. Overtime", f"{overtime:.1f}h")

            st.divider()

            # Work sessions table
            st.write("**Work Sessions:**")
            if not sessions_df.empty:
                display_sessions = sessions_df.copy()
                display_sessions['Date'] = display_sessions['Check In'].dt.strftime('%Y-%m-%d')
                display_sessions['Check In'] = display_sessions['Check In'].dt.strftime('%H:%M:%S')
                display_sessions['Check Out'] = display_sessions['Check Out'].dt.strftime('%H:%M:%S')
                display_sessions['Hours'] = display_sessions['Hours'].round(2)
                display_sessions['Break Time'] = display_sessions['Break Time'].round(2)
                display_sessions = display_sessions[['Date', 'Check In', 'Check Out', 'Hours', 'Break Time']]
                st.dataframe(display_sessions, use_container_width=True)
            else:
                st.info("No completed work sessions in this period.")

            st.divider()

            # Raw activity log
            with st.expander("📋 Detailed Activity Log"):
                display_history = history_df.copy()
                display_history['Timestamp'] = display_history['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                display_history = display_history[['Timestamp', 'Action']]
                st.dataframe(display_history, use_container_width=True)

            # Check for issues
            st.divider()
            st.write("**⚠️ Potential Issues:**")

            history_df_sorted = history_df.sort_values('Timestamp')
            all_issues = []

            for date in history_df_sorted['Timestamp'].dt.date.unique():
                day_records = history_df_sorted[history_df_sorted['Timestamp'].dt.date == date].sort_values('Timestamp')
                date_str = date.strftime('%Y-%m-%d')

                # Count actions
                check_ins = day_records[day_records['Action'] == ACTION_CHECK_IN]
                check_outs = day_records[day_records['Action'] == ACTION_CHECK_OUT]
                break_starts = day_records[day_records['Action'] == ACTION_BREAK_START]
                break_ends = day_records[day_records['Action'] == ACTION_BREAK_END]
                site_starts = day_records[day_records['Action'] == ACTION_SITE_VISIT_START]
                site_ends = day_records[day_records['Action'] == ACTION_SITE_VISIT_END]

                # Issue 1: Missing check-out
                if len(check_ins) > len(check_outs):
                    all_issues.append({
                        'Date': date_str,
                        'Issue': '🔴 Missing check-out',
                        'Details': f'{len(check_ins)} check-ins, {len(check_outs)} check-outs'
                    })

                # Issue 2: Missing check-in (checkout without checkin)
                if len(check_outs) > len(check_ins):
                    all_issues.append({
                        'Date': date_str,
                        'Issue': '🔴 Missing check-in',
                        'Details': f'{len(check_ins)} check-ins, {len(check_outs)} check-outs'
                    })

                # Issue 3: Unfinished break
                if len(break_starts) > len(break_ends):
                    all_issues.append({
                        'Date': date_str,
                        'Issue': '☕ Unfinished break',
                        'Details': f'{len(break_starts)} break starts, {len(break_ends)} break ends'
                    })

                # Issue 4: Break end without start
                if len(break_ends) > len(break_starts):
                    all_issues.append({
                        'Date': date_str,
                        'Issue': '☕ Break end without start',
                        'Details': f'{len(break_starts)} break starts, {len(break_ends)} break ends'
                    })

                # Issue 5: Unfinished site visit
                if len(site_starts) > len(site_ends):
                    all_issues.append({
                        'Date': date_str,
                        'Issue': '🚗 Unfinished site visit',
                        'Details': f'{len(site_starts)} site starts, {len(site_ends)} site ends'
                    })

                # Issue 6: Site visit end without start
                if len(site_ends) > len(site_starts):
                    all_issues.append({
                        'Date': date_str,
                        'Issue': '🚗 Site visit end without start',
                        'Details': f'{len(site_starts)} site starts, {len(site_ends)} site ends'
                    })

                # Issue 7: Late arrival
                if not check_ins.empty:
                    first_check_in = check_ins.iloc[0]['Timestamp']
                    if is_late_arrival(first_check_in):
                        all_issues.append({
                            'Date': date_str,
                            'Issue': '⏰ Late arrival',
                            'Details': f'Checked in at {first_check_in.strftime("%H:%M:%S")} (after {WORK_START_TIME.strftime("%H:%M")})'
                        })

                # Issue 8: Very short work day (less than 4 hours) - using actual session hours
                if len(check_ins) == len(check_outs) and len(check_ins) > 0:
                    day_sessions, day_hours, _, _ = calculate_work_sessions(day_records)
                    if day_hours < 4 and day_hours > 0:
                        all_issues.append({
                            'Date': date_str,
                            'Issue': '📉 Short work day',
                            'Details': f'Only {day_hours:.1f} hours worked'
                        })

                # Issue 9: Very long work day (more than 12 hours) - using actual session hours
                if len(check_ins) == len(check_outs) and len(check_ins) > 0:
                    day_sessions, day_hours, _, _ = calculate_work_sessions(day_records)
                    if day_hours > 12:
                        all_issues.append({
                            'Date': date_str,
                            'Issue': '⚠️ Excessively long day',
                            'Details': f'{day_hours:.1f} hours (more than 12h)'
                        })

                # Issue 10: Check-out before check-in (time order issue)
                if not check_ins.empty and not check_outs.empty:
                    first_in = check_ins.iloc[0]['Timestamp']
                    first_out = check_outs.iloc[0]['Timestamp']
                    if first_out < first_in:
                        all_issues.append({
                            'Date': date_str,
                            'Issue': '🔄 Check-out before check-in',
                            'Details': f'Out at {first_out.strftime("%H:%M")}, In at {first_in.strftime("%H:%M")}'
                        })

                # Issue 11: Very long break (more than 2 hours)
                if not break_starts.empty and not break_ends.empty:
                    for i in range(min(len(break_starts), len(break_ends))):
                        break_duration = (break_ends.iloc[i]['Timestamp'] - break_starts.iloc[i]['Timestamp']).total_seconds() / 3600
                        if break_duration > 2:
                            all_issues.append({
                                'Date': date_str,
                                'Issue': '☕ Long break',
                                'Details': f'Break lasted {break_duration:.1f} hours'
                            })
                            break  # Only report once per day

                # Issue 12: Weekend work
                if date.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    day_name = 'Saturday' if date.weekday() == 5 else 'Sunday'
                    all_issues.append({
                        'Date': date_str,
                        'Issue': '📅 Weekend work',
                        'Details': f'Worked on {day_name}'
                    })

            if all_issues:
                issues_df = pd.DataFrame(all_issues)
                st.dataframe(issues_df, use_container_width=True, hide_index=True)
                st.caption("Contact your administrator to correct any issues.")
            else:
                st.success("No issues found in your time records!")

        else:
            st.info("No history available for the selected period.")

    with tab3:
        # Settings tab - Change password
        st.subheader("⚙️ Account Settings")

        st.write("**Change Password:**")
        current_pwd = st.text_input("Current Password:", type="password", key="current_pwd")
        new_pwd1 = st.text_input("New Password:", type="password", key="new_pwd1")
        new_pwd2 = st.text_input("Confirm New Password:", type="password", key="new_pwd2")

        if st.button("🔐 Change Password"):
            if not current_pwd or not new_pwd1 or not new_pwd2:
                st.warning("Please fill in all fields.")
            elif new_pwd1 != new_pwd2:
                st.error("New passwords do not match!")
            else:
                # Verify current password
                employee_name = authenticate_employee(st.session_state.logged_in_username, current_pwd)
                if employee_name:
                    success, message = change_employee_password(st.session_state.logged_in_username, new_pwd1)
                    if success:
                        st.success("Password changed successfully!")
                    else:
                        st.error(message)
                else:
                    st.error("Current password is incorrect!")

    # Footer
    st.divider()
    st.info("✅ Your attendance is being recorded. Thank you!")
    st.caption("For issues or corrections, please contact your administrator.")
