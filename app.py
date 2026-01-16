import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
from io import BytesIO
import time as time_module
import hashlib
# Google Sheets integration
import gspread
from google.oauth2.service_account import Credentials

# --- Konfiguration ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
WORK_START_TIME = time(9, 0)  # 9:00 Uhr - konfigurierbarer Arbeitsbeginn
STANDARD_WORK_HOURS = 8  # Standard Arbeitsstunden pro Tag

# Aktionstypen
ACTION_CHECK_IN = "Einstempeln"
ACTION_CHECK_OUT = "Ausstempeln"
ACTION_BREAK_START = "Pause Start"
ACTION_BREAK_END = "Pause Ende"
ACTION_SITE_VISIT_START = "Außendienst Start"
ACTION_SITE_VISIT_END = "Außendienst Ende"

# Secrets aus .streamlit/secrets.toml laden
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123")
SHEET_URL = st.secrets.get("SHEET_URL", "")

# --- Funktionen ---

@st.cache_resource
def get_gsheet_client():
    """Gibt einen autorisierten gspread-Client zurück (gecacht)."""
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(dict(creds_dict), scopes=SCOPES)
    return gspread.authorize(creds)

def retry_operation(operation, max_retries=3, delay=1):
    """Wiederholt eine Operation mit exponentiellem Backoff."""
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
    """Hasht ein Passwort für sichere Speicherung."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_employees_worksheet():
    """Holt oder erstellt das Mitarbeiter-Arbeitsblatt."""
    client = get_gsheet_client()
    sh = client.open_by_url(SHEET_URL)

    try:
        worksheet = sh.worksheet("Mitarbeiter")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title="Mitarbeiter", rows=100, cols=3)
        worksheet.append_row(["Benutzername", "PasswortHash", "Anzeigename"])

    return worksheet

@st.cache_data(ttl=60)
def load_employees_from_sheet():
    """Lädt Mitarbeiter-Anmeldedaten aus Google Sheets."""
    def _load():
        worksheet = get_employees_worksheet()
        data = worksheet.get_all_records()
        credentials = {}
        for row in data:
            username = row.get('Benutzername', '').lower().strip()
            if username:
                credentials[username] = {
                    'password_hash': row.get('PasswortHash', ''),
                    'name': row.get('Anzeigename', '')
                }
        return credentials

    try:
        return retry_operation(_load)
    except Exception as e:
        st.error(f"Fehler beim Laden der Mitarbeiter: {e}")
        return {}

def clear_employees_cache():
    """Leert den Mitarbeiter-Cache."""
    load_employees_from_sheet.clear()

def get_employee_credentials():
    """Holt Mitarbeiter-Anmeldedaten aus Google Sheets."""
    return load_employees_from_sheet()

def get_employees():
    """Gibt die Liste der Mitarbeiternamen zurück."""
    credentials = get_employee_credentials()
    return [data['name'] for data in credentials.values()]

def authenticate_employee(username, password):
    """Authentifiziert einen Mitarbeiter anhand von Benutzername und Passwort."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower in credentials:
        if credentials[username_lower]['password_hash'] == hash_password(password):
            return credentials[username_lower]['name']
    return None

def add_employee(username, password, display_name):
    """Fügt einen neuen Mitarbeiter zu Google Sheets hinzu."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower in credentials:
        return False, "Benutzername existiert bereits!"
    if not username_lower or not password or not display_name:
        return False, "Alle Felder sind erforderlich!"

    def _add():
        worksheet = get_employees_worksheet()
        password_hash = hash_password(password)
        worksheet.append_row([username_lower, password_hash, display_name.strip()])

    try:
        retry_operation(_add)
        clear_employees_cache()
        return True, f"Mitarbeiter {display_name} erfolgreich hinzugefügt!"
    except Exception as e:
        return False, f"Fehler beim Hinzufügen des Mitarbeiters: {e}"

def remove_employee(username):
    """Entfernt einen Mitarbeiter aus Google Sheets."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower not in credentials:
        return False, "Mitarbeiter nicht gefunden!"

    def _remove():
        worksheet = get_employees_worksheet()
        cell = worksheet.find(username_lower, in_column=1)
        if cell:
            worksheet.delete_rows(cell.row)

    try:
        retry_operation(_remove)
        clear_employees_cache()
        return True, "Mitarbeiter erfolgreich entfernt!"
    except Exception as e:
        return False, f"Fehler beim Entfernen des Mitarbeiters: {e}"

def change_employee_password(username, new_password):
    """Ändert das Passwort eines Mitarbeiters in Google Sheets."""
    credentials = get_employee_credentials()
    username_lower = username.lower().strip()
    if username_lower not in credentials:
        return False, "Mitarbeiter nicht gefunden!"

    def _change():
        worksheet = get_employees_worksheet()
        cell = worksheet.find(username_lower, in_column=1)
        if cell:
            worksheet.update_cell(cell.row, 2, hash_password(new_password))

    try:
        retry_operation(_change)
        clear_employees_cache()
        return True, "Passwort erfolgreich geändert!"
    except Exception as e:
        return False, f"Fehler beim Ändern des Passworts: {e}"

def logout_employee():
    """Meldet den aktuellen Mitarbeiter ab."""
    if 'logged_in_employee' in st.session_state:
        del st.session_state.logged_in_employee
    if 'logged_in_username' in st.session_state:
        del st.session_state.logged_in_username

@st.cache_data(ttl=60)
def load_data():
    """Lädt die Zeitprotokolle aus Google Sheets (60 Sekunden gecacht)."""
    def _load():
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(0)
        data = worksheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=['Mitarbeiter', 'Aktion', 'Zeitstempel'])
        return pd.DataFrame(data)

    try:
        return retry_operation(_load)
    except Exception as e:
        st.error(f"Fehler beim Laden der Daten aus Google Sheets: {e}")
        return pd.DataFrame(columns=['Mitarbeiter', 'Aktion', 'Zeitstempel'])

def clear_data_cache():
    """Leert den Daten-Cache."""
    load_data.clear()

def save_log(employee, action):
    """Speichert einen neuen Zeiteintrag in Google Sheets."""
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
    """Gibt den aktuellen Status eines Mitarbeiters zurück."""
    if df is None:
        df = load_data()

    if df.empty:
        return None, None

    df['Zeitstempel'] = pd.to_datetime(df['Zeitstempel'], errors='coerce')
    today = datetime.now().date()
    today_records = df[
        (df['Mitarbeiter'] == employee) &
        (df['Zeitstempel'].dt.date == today)
    ].sort_values('Zeitstempel')

    if today_records.empty:
        return None, None

    last_action = today_records.iloc[-1]['Aktion']
    last_time = today_records.iloc[-1]['Zeitstempel']
    return last_action, last_time

def is_late_arrival(check_in_time):
    """Prüft, ob die Einstempelzeit nach dem konfigurierten Arbeitsbeginn liegt."""
    if check_in_time is None:
        return False
    return check_in_time.time() > WORK_START_TIME

def calculate_work_sessions(employee_df, include_breaks=True):
    """Berechnet Arbeitseinheiten durch Paaren von Ein- und Ausstempelungen."""
    if employee_df.empty:
        return pd.DataFrame(), 0, 0, 0

    employee_df = employee_df.sort_values(by='Zeitstempel')
    employee_df['Zeitstempel'] = pd.to_datetime(employee_df['Zeitstempel'])

    sessions = []
    check_in_time = None
    break_start = None
    site_visit_start = None
    total_break_time = timedelta()
    total_site_visit_time = timedelta()

    for _, row in employee_df.iterrows():
        action = row['Aktion']
        timestamp = row['Zeitstempel']

        if action == ACTION_CHECK_IN:
            check_in_time = timestamp
        elif action == ACTION_CHECK_OUT and check_in_time is not None:
            check_out_time = timestamp
            duration = check_out_time - check_in_time
            if include_breaks:
                duration = duration - total_break_time
            sessions.append({
                'Einstempeln': check_in_time,
                'Ausstempeln': check_out_time,
                'Dauer': duration,
                'Stunden': duration.total_seconds() / 3600,
                'Pausenzeit': total_break_time.total_seconds() / 3600,
                'Außendienstzeit': total_site_visit_time.total_seconds() / 3600
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
    total_hours = sessions_df['Stunden'].sum() if not sessions_df.empty else 0
    total_break_hours = sessions_df['Pausenzeit'].sum() if not sessions_df.empty else 0
    total_site_hours = sessions_df['Außendienstzeit'].sum() if not sessions_df.empty else 0

    return sessions_df, total_hours, total_break_hours, total_site_hours

def calculate_overtime(hours_worked):
    """Berechnet Überstunden über die Standardarbeitszeit hinaus."""
    if hours_worked > STANDARD_WORK_HOURS:
        return hours_worked - STANDARD_WORK_HOURS
    return 0

def get_week_dates():
    """Gibt das Start- und Enddatum der aktuellen Woche zurück."""
    today = datetime.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

def calculate_weekly_summary(df=None):
    """Berechnet die wöchentlichen Stunden für alle Mitarbeiter."""
    if df is None:
        df = load_data()

    if df.empty:
        return pd.DataFrame()

    df['Zeitstempel'] = pd.to_datetime(df['Zeitstempel'], errors='coerce')
    start_of_week, end_of_week = get_week_dates()

    weekly_data = []
    for employee in get_employees():
        emp_df = df[
            (df['Mitarbeiter'] == employee) &
            (df['Zeitstempel'].dt.date >= start_of_week) &
            (df['Zeitstempel'].dt.date <= end_of_week)
        ]

        sessions_df, total_hours, break_hours, site_hours = calculate_work_sessions(emp_df)
        overtime = calculate_overtime(total_hours)

        weekly_data.append({
            'Mitarbeiter': employee,
            'Arbeitsstunden': round(total_hours, 2),
            'Pausenzeit': round(break_hours, 2),
            'Außendienst': round(site_hours, 2),
            'Überstunden': round(overtime, 2)
        })

    return pd.DataFrame(weekly_data)

def get_employee_history(employee, days=30):
    """Gibt die Historie eines Mitarbeiters für die letzten N Tage zurück."""
    df = load_data()
    if df.empty:
        return pd.DataFrame()

    df['Zeitstempel'] = pd.to_datetime(df['Zeitstempel'], errors='coerce')
    cutoff_date = datetime.now().date() - timedelta(days=days)

    emp_df = df[
        (df['Mitarbeiter'] == employee) &
        (df['Zeitstempel'].dt.date >= cutoff_date)
    ].sort_values('Zeitstempel', ascending=False)

    return emp_df

def generate_excel_report(start_date=None, end_date=None):
    """Erstellt einen einfachen Excel-Bericht mit Mitarbeiterstunden für die Abrechnung."""
    df = load_data()
    if df.empty:
        return None, None

    df['Zeitstempel'] = pd.to_datetime(df['Zeitstempel'], errors='coerce')

    if start_date and end_date:
        df = df[
            (df['Zeitstempel'].dt.date >= start_date) &
            (df['Zeitstempel'].dt.date <= end_date)
        ]

    if df.empty:
        return None, None

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_data = []
        for employee in get_employees():
            emp_df = df[df['Mitarbeiter'] == employee]
            sessions_df, total_hours, break_hours, site_hours = calculate_work_sessions(emp_df)

            if total_hours > 0:
                summary_data.append({
                    'Mitarbeiter': employee,
                    'Gesamtstunden': round(total_hours, 2),
                    'Arbeitstage (8h)': round(total_hours / 8, 2)
                })

        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Abrechnungsübersicht', index=False)

        worksheet = writer.sheets['Abrechnungsübersicht']
        worksheet.column_dimensions['A'].width = 25
        worksheet.column_dimensions['B'].width = 15
        worksheet.column_dimensions['C'].width = 18

    output.seek(0)
    return output, summary_df

# --- Google Sheets Upload Funktionen ---

def upload_df_to_gsheet(df, worksheet_index=0):
    """Lädt ein DataFrame in ein Google Sheets Arbeitsblatt hoch."""
    def _upload():
        safe_df = df.replace([float('inf'), float('-inf')], pd.NA)
        safe_df = safe_df.fillna("")
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(worksheet_index)
        worksheet.clear()
        worksheet.update([safe_df.columns.values.tolist()] + safe_df.values.tolist())

    retry_operation(_upload)

# --- Alle Daten löschen Funktion ---

def clear_all_data(worksheet_index=0):
    """Löscht alle Daten aus dem Google Sheet und fügt die Überschriften wieder hinzu."""
    def _clear():
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(worksheet_index)
        worksheet.clear()
        worksheet.append_row(['Mitarbeiter', 'Aktion', 'Zeitstempel'])

    retry_operation(_clear)
    clear_data_cache()


def calculate_monthly_summary_df():
    """Berechnet die monatliche Zusammenfassung für alle Mitarbeiter."""
    df = load_data()
    monthly_summary = []
    for employee in get_employees():
        emp_df = df[df['Mitarbeiter'] == employee]
        if emp_df.empty:
            continue
        emp_df['Zeitstempel'] = pd.to_datetime(emp_df['Zeitstempel'], errors='coerce')
        emp_df = emp_df.sort_values('Zeitstempel')
        sessions_df, _, _, _ = calculate_work_sessions(emp_df)
        if sessions_df.empty:
            continue
        sessions_df['Mitarbeiter'] = employee
        sessions_df['Jahr'] = sessions_df['Einstempeln'].dt.year
        sessions_df['Monat'] = sessions_df['Einstempeln'].dt.strftime('%B')
        grouped = sessions_df.groupby(['Mitarbeiter', 'Jahr', 'Monat'])['Stunden'].sum().reset_index()
        if not grouped.empty:
            monthly_summary.append(grouped)

    if monthly_summary:
        monthly_summary_df = pd.concat(monthly_summary, ignore_index=True)
        if not monthly_summary_df.empty:
            monthly_summary_df = monthly_summary_df[['Mitarbeiter', 'Jahr', 'Monat', 'Stunden']]
            monthly_summary_df = monthly_summary_df.rename(columns={'Stunden': 'Gesamtstunden'})
            return monthly_summary_df
    return pd.DataFrame(columns=['Mitarbeiter', 'Jahr', 'Monat', 'Gesamtstunden'])

def upload_monthly_summary_to_gsheet():
    """Lädt die monatliche Zusammenfassung in Google Sheets hoch."""
    def _upload():
        client = get_gsheet_client()
        sh = client.open_by_url(SHEET_URL)
        try:
            worksheet = sh.worksheet('Monatliche Zusammenfassung')
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title='Monatliche Zusammenfassung', rows=100, cols=10)
        worksheet.clear()
        monthly_summary_df = calculate_monthly_summary_df()
        worksheet.update([monthly_summary_df.columns.values.tolist()] + monthly_summary_df.values.tolist())

    retry_operation(_upload)

# --- Streamlit Benutzeroberfläche ---

st.set_page_config(page_title="Zeiterfassung", page_icon="⏰")

st.title("⏰ Mitarbeiter Zeiterfassung")

# Session State für Anmeldung initialisieren
if 'logged_in_employee' not in st.session_state:
    st.session_state.logged_in_employee = None
if 'logged_in_username' not in st.session_state:
    st.session_state.logged_in_username = None
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False
if 'show_admin_login' not in st.session_state:
    st.session_state.show_admin_login = False

# Hauptoberfläche
if st.session_state.admin_logged_in:
    # Admin-Bereich auf Hauptseite
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader("🔐 Admin-Bereich")
    with col_header2:
        if st.button("🚪 Abmelden"):
            st.session_state.admin_logged_in = False
            st.rerun()

    # Wochenübersicht
    st.subheader("📅 Wochenübersicht")
    weekly_df = calculate_weekly_summary()
    if not weekly_df.empty:
        start_of_week, end_of_week = get_week_dates()
        st.caption(f"Woche: {start_of_week.strftime('%d.%m.')} - {end_of_week.strftime('%d.%m.%Y')}")
        st.dataframe(weekly_df, use_container_width=True)
    else:
        st.info("Keine Daten für diese Woche.")

    st.divider()
    st.subheader("📊 Berichte herunterladen")

    # Datumsfilter
    col_start, col_end = st.columns(2)
    with col_start:
        filter_start = st.date_input("Von:", value=None, key="filter_start")
    with col_end:
        filter_end = st.date_input("Bis:", value=None, key="filter_end")

    if st.button("Excel-Bericht erstellen"):
        try:
            excel_data, summary_df = generate_excel_report(filter_start, filter_end)
            if excel_data is not None and summary_df is not None:
                date_suffix = ""
                if filter_start and filter_end:
                    date_suffix = f"_{filter_start.strftime('%Y%m%d')}_bis_{filter_end.strftime('%Y%m%d')}"
                st.download_button(
                    label="📥 Excel-Bericht herunterladen",
                    data=excel_data,
                    file_name=f"zeitbericht{date_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Keine Daten für den ausgewählten Zeitraum verfügbar.")
        except Exception as e:
            st.error(f"Fehler beim Erstellen des Berichts: {e}")

    st.divider()
    if st.checkbox("Rohdaten anzeigen"):
        st.subheader("Alle Einträge")
        try:
            df_all = load_data()
            st.dataframe(df_all)
        except Exception as e:
            st.error(f"Fehler beim Laden der Daten: {e}")

    st.divider()
    st.subheader("👥 Mitarbeiter verwalten")

    # Neuen Mitarbeiter hinzufügen
    st.write("**Neuen Mitarbeiter hinzufügen:**")
    new_username = st.text_input("Benutzername:", key="new_username")
    new_password = st.text_input("Passwort:", type="password", key="new_password")
    new_display_name = st.text_input("Anzeigename:", key="new_display_name")

    if st.button("➕ Mitarbeiter hinzufügen"):
        if new_username and new_password and new_display_name:
            success, message = add_employee(new_username, new_password, new_display_name)
            if success:
                st.success(message)
                del st.session_state.new_username
                del st.session_state.new_password
                del st.session_state.new_display_name
                st.rerun()
            else:
                st.warning(message)
        else:
            st.warning("Bitte alle Felder ausfüllen.")

    # Mitarbeiter entfernen
    st.write("**Mitarbeiter entfernen:**")
    credentials = get_employee_credentials()
    if credentials:
        usernames = list(credentials.keys())
        username_to_remove = st.selectbox("Mitarbeiter auswählen:", usernames, key="remove_emp")
        if st.button("➖ Mitarbeiter entfernen"):
            if len(credentials) > 1:
                success, message = remove_employee(username_to_remove)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.warning(message)
            else:
                st.warning("Der letzte Mitarbeiter kann nicht entfernt werden!")

    # Passwort zurücksetzen
    st.write("**Passwort zurücksetzen:**")
    if credentials:
        username_for_reset = st.selectbox("Mitarbeiter auswählen:", usernames, key="reset_pwd_emp")
        new_pwd = st.text_input("Neues Passwort:", type="password", key="reset_pwd")
        if st.button("🔑 Passwort zurücksetzen"):
            if new_pwd:
                success, message = change_employee_password(username_for_reset, new_pwd)
                if success:
                    st.success(message)
                else:
                    st.warning(message)
            else:
                st.warning("Bitte ein neues Passwort eingeben.")

    # Aktuelle Mitarbeiterliste anzeigen
    st.write("**Aktuelle Mitarbeiter:**")
    for uname, data in credentials.items():
        st.caption(f"• {data['name']} (@{uname})")

    st.divider()
    st.subheader("⚠️ Gefahrenzone")
    confirm_clear = st.checkbox("Ich bestätige, dass ich ALLE Daten löschen möchte", key="confirm_clear")
    if st.button("❌ Alle Daten löschen", type="primary", disabled=not confirm_clear):
        try:
            clear_all_data()
            st.success("Alle Daten wurden aus Google Sheets gelöscht!")
            st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Löschen der Daten: {e}")

elif st.session_state.logged_in_employee is None:
    # Anmeldeformular anzeigen
    if st.session_state.show_admin_login:
        # Admin-Anmeldeformular
        st.subheader("🔐 Admin-Anmeldung")

        admin_password = st.text_input("Admin-Passwort:", type="password", key="admin_pwd")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🔓 Als Admin anmelden", use_container_width=True):
                if admin_password == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.session_state.show_admin_login = False
                    st.rerun()
                else:
                    st.error("Ungültiges Admin-Passwort!")
        with col_btn2:
            if st.button("⬅️ Zurück zur Mitarbeiter-Anmeldung", use_container_width=True):
                st.session_state.show_admin_login = False
                st.rerun()
    else:
        # Mitarbeiter-Anmeldeformular
        st.subheader("🔑 Mitarbeiter-Anmeldung")

        col_login1, col_login2 = st.columns([2, 1])

        with col_login1:
            login_username = st.text_input("Benutzername:", key="login_username")
            login_password = st.text_input("Passwort:", type="password", key="login_password")

            if st.button("🔓 Anmelden", use_container_width=True):
                if login_username and login_password:
                    employee_name = authenticate_employee(login_username, login_password)
                    if employee_name:
                        st.session_state.logged_in_employee = employee_name
                        st.session_state.logged_in_username = login_username.lower().strip()
                        st.success(f"Willkommen, {employee_name}!")
                        st.rerun()
                    else:
                        st.error("Ungültiger Benutzername oder Passwort!")
                else:
                    st.warning("Bitte Benutzername und Passwort eingeben.")

        with col_login2:
            st.info("💡 Kontaktieren Sie Ihren Administrator, wenn Sie Ihr Passwort vergessen haben.")

        st.divider()
        if st.button("🔐 Als Admin anmelden", use_container_width=True):
            st.session_state.show_admin_login = True
            st.rerun()

else:
    # Benutzer ist angemeldet
    selected_employee = st.session_state.logged_in_employee

    # Kopfzeile mit Abmelden
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader(f"👋 Willkommen, {selected_employee}!")
    with col_header2:
        if st.button("🚪 Abmelden"):
            logout_employee()
            st.rerun()

    # Tabs für Zeiterfassung und Historie
    tab1, tab2, tab3 = st.tabs(["⏰ Zeit erfassen", "📜 Meine Historie", "⚙️ Einstellungen"])

    with tab1:
        # Aktuellen Status und heutige Aktivität anzeigen
        try:
            df_status = load_data()
            today = datetime.now().date()

            if not df_status.empty:
                df_status['Zeitstempel'] = pd.to_datetime(df_status['Zeitstempel'], errors='coerce')
                today_records = df_status[
                    (df_status['Mitarbeiter'] == selected_employee) &
                    (df_status['Zeitstempel'].dt.date == today)
                ].sort_values('Zeitstempel')

                # Statusanzeige
                if today_records.empty:
                    st.warning(f"📋 Status: Sie haben sich heute noch nicht eingestempelt")
                else:
                    last_action = today_records.iloc[-1]['Aktion']
                    last_time = today_records.iloc[-1]['Zeitstempel']
                    last_time_str = last_time.strftime('%H:%M:%S')

                    # Statusanzeige basierend auf letzter Aktion
                    if last_action == ACTION_CHECK_IN:
                        st.success(f"🟢 Status: Eingestempelt (seit {last_time_str})")
                    elif last_action == ACTION_CHECK_OUT:
                        st.info(f"🔴 Status: Ausgestempelt (um {last_time_str})")
                    elif last_action == ACTION_BREAK_START:
                        st.warning(f"☕ Status: In der Pause (seit {last_time_str})")
                    elif last_action == ACTION_BREAK_END:
                        st.success(f"🟢 Status: Zurück von der Pause (um {last_time_str})")
                    elif last_action == ACTION_SITE_VISIT_START:
                        st.info(f"🚗 Status: Im Außendienst (seit {last_time_str})")
                    elif last_action == ACTION_SITE_VISIT_END:
                        st.success(f"🟢 Status: Zurück vom Außendienst (um {last_time_str})")

                    # Verspätungswarnung
                    check_ins = today_records[today_records['Aktion'] == ACTION_CHECK_IN]
                    if not check_ins.empty:
                        first_check_in = check_ins.iloc[0]['Zeitstempel']
                        if is_late_arrival(first_check_in):
                            st.error(f"⚠️ Verspätung! Eingestempelt um {first_check_in.strftime('%H:%M:%S')} (nach {WORK_START_TIME.strftime('%H:%M')})")

                    # Heutige Aktivitätsübersicht
                    with st.expander("📅 Heutige Aktivität"):
                        check_ins = today_records[today_records['Aktion'] == ACTION_CHECK_IN]
                        check_outs = today_records[today_records['Aktion'] == ACTION_CHECK_OUT]
                        breaks_start = today_records[today_records['Aktion'] == ACTION_BREAK_START]
                        site_starts = today_records[today_records['Aktion'] == ACTION_SITE_VISIT_START]

                        sessions_df, hours_today, break_hours, site_hours = calculate_work_sessions(today_records)

                        # Alle Arbeitseinheiten anzeigen
                        st.write(f"**Arbeitseinheiten:** {len(check_ins)}")
                        if not sessions_df.empty:
                            for idx, session in sessions_df.iterrows():
                                in_time = session['Einstempeln'].strftime('%H:%M:%S')
                                out_time = session['Ausstempeln'].strftime('%H:%M:%S') if pd.notna(session['Ausstempeln']) else "Noch aktiv"
                                session_hours = f"{session['Stunden']:.2f}h" if session['Stunden'] > 0 else ""
                                st.caption(f"  Einheit {idx+1}: {in_time} - {out_time} {session_hours}")

                        # Anzeigen, ob aktuell in einer offenen Einheit
                        if len(check_ins) > len(check_outs):
                            last_check_in = check_ins.iloc[-1]['Zeitstempel']
                            hours_so_far = (datetime.now() - last_check_in).total_seconds() / 3600
                            st.write(f"**Aktuelle Einheit:** {hours_so_far:.2f}h (noch aktiv)")

                        if not breaks_start.empty:
                            st.write(f"**Pausen:** {len(breaks_start)}")

                        if not site_starts.empty:
                            st.write(f"**Außendienste:** {len(site_starts)}")

                        # Gesamtstunden
                        st.divider()
                        st.write(f"**Stunden heute:** {hours_today:.2f}h")
                        overtime = calculate_overtime(hours_today)
                        if overtime > 0:
                            st.write(f"**Überstunden:** {overtime:.2f}h")
                        if break_hours > 0:
                            st.write(f"**Pausenzeit:** {break_hours:.2f}h")
                        if site_hours > 0:
                            st.write(f"**Außendienstzeit:** {site_hours:.2f}h")
            else:
                st.info(f"📋 Noch keine Einträge")
        except Exception as e:
            st.error(f"Fehler beim Laden des Status: {e}")

        st.divider()

        # Aktionsschaltflächen - Ein-/Ausstempeln
        st.write("**Hauptaktionen:**")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("🟢 Einstempeln", use_container_width=True):
                try:
                    df_all = load_data()
                    today = datetime.now().date()
                    can_check_in = True

                    if not df_all.empty:
                        df_all['Zeitstempel'] = pd.to_datetime(df_all['Zeitstempel'], errors='coerce')
                        today_records = df_all[
                            (df_all['Mitarbeiter'] == selected_employee) &
                            (df_all['Zeitstempel'].dt.date == today)
                        ].sort_values('Zeitstempel')

                        if not today_records.empty:
                            last_action = today_records.iloc[-1]['Aktion']
                            if last_action != ACTION_CHECK_OUT:
                                can_check_in = False

                    if not can_check_in:
                        st.warning("Sie sind bereits eingestempelt! Bitte erst ausstempeln.")
                    else:
                        time_logged = save_log(selected_employee, ACTION_CHECK_IN)
                        st.success(f"Eingestempelt um {time_logged.strftime('%Y-%m-%d %H:%M:%S')}")
                        if is_late_arrival(time_logged):
                            st.warning(f"⚠️ Verspätung! (nach {WORK_START_TIME.strftime('%H:%M')})")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                            upload_monthly_summary_to_gsheet()
                        except Exception:
                            pass
                        st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Einstempeln: {e}")

        with col2:
            if st.button("🔴 Ausstempeln", use_container_width=True):
                try:
                    df_all = load_data()
                    today = datetime.now().date()
                    can_check_out = False
                    error_message = ""

                    if not df_all.empty:
                        df_all['Zeitstempel'] = pd.to_datetime(df_all['Zeitstempel'], errors='coerce')
                        today_records = df_all[
                            (df_all['Mitarbeiter'] == selected_employee) &
                            (df_all['Zeitstempel'].dt.date == today)
                        ].sort_values('Zeitstempel')

                        if today_records.empty:
                            error_message = "Sie haben sich heute noch nicht eingestempelt!"
                        else:
                            last_action = today_records.iloc[-1]['Aktion']
                            if last_action == ACTION_CHECK_OUT:
                                error_message = "Sie sind bereits ausgestempelt!"
                            elif last_action in [ACTION_CHECK_IN, ACTION_BREAK_END, ACTION_SITE_VISIT_END]:
                                can_check_out = True
                            elif last_action == ACTION_BREAK_START:
                                error_message = "Bitte beenden Sie erst Ihre Pause!"
                            elif last_action == ACTION_SITE_VISIT_START:
                                error_message = "Bitte beenden Sie erst Ihren Außendienst!"
                    else:
                        error_message = "Sie haben sich heute noch nicht eingestempelt!"

                    if not can_check_out:
                        st.warning(error_message)
                    else:
                        time_logged = save_log(selected_employee, ACTION_CHECK_OUT)
                        st.info(f"Ausgestempelt um {time_logged.strftime('%Y-%m-%d %H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                            upload_monthly_summary_to_gsheet()
                        except Exception:
                            pass
                        st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Ausstempeln: {e}")

        # Pausen- und Außendienstschaltflächen
        st.write("**Pause & Außendienst:**")
        col3, col4, col5, col6 = st.columns(4)

        with col3:
            if st.button("☕ Pause starten", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action in [ACTION_CHECK_IN, ACTION_BREAK_END, ACTION_SITE_VISIT_END]:
                        time_logged = save_log(selected_employee, ACTION_BREAK_START)
                        st.success(f"Pause gestartet um {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    elif last_action == ACTION_BREAK_START:
                        st.warning("Bereits in der Pause!")
                    elif last_action == ACTION_SITE_VISIT_START:
                        st.warning("Bitte erst Außendienst beenden!")
                    else:
                        st.warning("Bitte erst einstempeln!")
                except Exception as e:
                    st.error(f"Fehler beim Starten der Pause: {e}")

        with col4:
            if st.button("☕ Pause beenden", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action == ACTION_BREAK_START:
                        time_logged = save_log(selected_employee, ACTION_BREAK_END)
                        st.success(f"Pause beendet um {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    else:
                        st.warning("Sie sind nicht in der Pause!")
                except Exception as e:
                    st.error(f"Fehler beim Beenden der Pause: {e}")

        with col5:
            if st.button("🚗 Außendienst starten", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action in [ACTION_CHECK_IN, ACTION_BREAK_END, ACTION_SITE_VISIT_END]:
                        time_logged = save_log(selected_employee, ACTION_SITE_VISIT_START)
                        st.success(f"Außendienst gestartet um {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    elif last_action == ACTION_SITE_VISIT_START:
                        st.warning("Bereits im Außendienst!")
                    elif last_action == ACTION_BREAK_START:
                        st.warning("Bitte erst Pause beenden!")
                    else:
                        st.warning("Bitte erst einstempeln!")
                except Exception as e:
                    st.error(f"Fehler beim Starten des Außendienstes: {e}")

        with col6:
            if st.button("🚗 Außendienst beenden", use_container_width=True):
                try:
                    last_action, _ = get_employee_status(selected_employee)
                    if last_action == ACTION_SITE_VISIT_START:
                        time_logged = save_log(selected_employee, ACTION_SITE_VISIT_END)
                        st.success(f"Außendienst beendet um {time_logged.strftime('%H:%M:%S')}")
                        try:
                            df_all = load_data()
                            upload_df_to_gsheet(df_all)
                        except Exception:
                            pass
                        st.rerun()
                    else:
                        st.warning("Sie sind nicht im Außendienst!")
                except Exception as e:
                    st.error(f"Fehler beim Beenden des Außendienstes: {e}")

    with tab2:
        # Persönliche Historie
        st.subheader("📜 Meine Zeithistorie")

        # Zeitraumauswahl
        history_days = st.selectbox("Historie anzeigen für:", [7, 14, 30, 60, 90], index=2, format_func=lambda x: f"Letzte {x} Tage")

        history_df = get_employee_history(selected_employee, days=history_days)

        if not history_df.empty:
            # Zusammenfassungsstatistiken
            col_stat1, col_stat2, col_stat3 = st.columns(3)

            sessions_df, total_hours, break_hours, site_hours = calculate_work_sessions(history_df)

            with col_stat1:
                st.metric("Gesamtstunden", f"{total_hours:.1f}h")
            with col_stat2:
                st.metric("Arbeitseinheiten", len(sessions_df))
            with col_stat3:
                overtime = max(0, total_hours - (history_days / 7 * 5 * STANDARD_WORK_HOURS))
                st.metric("Geschätzte Überstunden", f"{overtime:.1f}h")

            st.divider()

            # Arbeitseinheiten-Tabelle
            st.write("**Arbeitseinheiten:**")
            if not sessions_df.empty:
                display_sessions = sessions_df.copy()
                display_sessions['Datum'] = display_sessions['Einstempeln'].dt.strftime('%Y-%m-%d')
                display_sessions['Einstempeln'] = display_sessions['Einstempeln'].dt.strftime('%H:%M:%S')
                display_sessions['Ausstempeln'] = display_sessions['Ausstempeln'].dt.strftime('%H:%M:%S')
                display_sessions['Stunden'] = display_sessions['Stunden'].round(2)
                display_sessions['Pausenzeit'] = display_sessions['Pausenzeit'].round(2)
                display_sessions = display_sessions[['Datum', 'Einstempeln', 'Ausstempeln', 'Stunden', 'Pausenzeit']]
                st.dataframe(display_sessions, use_container_width=True)
            else:
                st.info("Keine abgeschlossenen Arbeitseinheiten in diesem Zeitraum.")

            st.divider()

            # Detailliertes Aktivitätsprotokoll
            with st.expander("📋 Detailliertes Aktivitätsprotokoll"):
                display_history = history_df.copy()
                display_history['Zeitstempel'] = display_history['Zeitstempel'].dt.strftime('%Y-%m-%d %H:%M:%S')
                display_history = display_history[['Zeitstempel', 'Aktion']]
                st.dataframe(display_history, use_container_width=True)

            # Probleme prüfen
            st.divider()
            st.write("**⚠️ Mögliche Probleme:**")

            history_df_sorted = history_df.sort_values('Zeitstempel')
            all_issues = []

            for date in history_df_sorted['Zeitstempel'].dt.date.unique():
                day_records = history_df_sorted[history_df_sorted['Zeitstempel'].dt.date == date].sort_values('Zeitstempel')
                date_str = date.strftime('%Y-%m-%d')

                # Aktionen zählen
                check_ins = day_records[day_records['Aktion'] == ACTION_CHECK_IN]
                check_outs = day_records[day_records['Aktion'] == ACTION_CHECK_OUT]
                break_starts = day_records[day_records['Aktion'] == ACTION_BREAK_START]
                break_ends = day_records[day_records['Aktion'] == ACTION_BREAK_END]
                site_starts = day_records[day_records['Aktion'] == ACTION_SITE_VISIT_START]
                site_ends = day_records[day_records['Aktion'] == ACTION_SITE_VISIT_END]

                # Problem 1: Fehlendes Ausstempeln
                if len(check_ins) > len(check_outs):
                    all_issues.append({
                        'Datum': date_str,
                        'Problem': '🔴 Fehlendes Ausstempeln',
                        'Details': f'{len(check_ins)} Einstempelungen, {len(check_outs)} Ausstempelungen'
                    })

                # Problem 2: Fehlendes Einstempeln
                if len(check_outs) > len(check_ins):
                    all_issues.append({
                        'Datum': date_str,
                        'Problem': '🔴 Fehlendes Einstempeln',
                        'Details': f'{len(check_ins)} Einstempelungen, {len(check_outs)} Ausstempelungen'
                    })

                # Problem 3: Unbeendete Pause
                if len(break_starts) > len(break_ends):
                    all_issues.append({
                        'Datum': date_str,
                        'Problem': '☕ Unbeendete Pause',
                        'Details': f'{len(break_starts)} Pausenstarts, {len(break_ends)} Pausenenden'
                    })

                # Problem 4: Pausenende ohne Start
                if len(break_ends) > len(break_starts):
                    all_issues.append({
                        'Datum': date_str,
                        'Problem': '☕ Pausenende ohne Start',
                        'Details': f'{len(break_starts)} Pausenstarts, {len(break_ends)} Pausenenden'
                    })

                # Problem 5: Unbeendeter Außendienst
                if len(site_starts) > len(site_ends):
                    all_issues.append({
                        'Datum': date_str,
                        'Problem': '🚗 Unbeendeter Außendienst',
                        'Details': f'{len(site_starts)} Außendienststarts, {len(site_ends)} Außendienstenden'
                    })

                # Problem 6: Außendienstende ohne Start
                if len(site_ends) > len(site_starts):
                    all_issues.append({
                        'Datum': date_str,
                        'Problem': '🚗 Außendienstende ohne Start',
                        'Details': f'{len(site_starts)} Außendienststarts, {len(site_ends)} Außendienstenden'
                    })

                # Problem 7: Verspätung
                if not check_ins.empty:
                    first_check_in = check_ins.iloc[0]['Zeitstempel']
                    if is_late_arrival(first_check_in):
                        all_issues.append({
                            'Datum': date_str,
                            'Problem': '⏰ Verspätung',
                            'Details': f'Eingestempelt um {first_check_in.strftime("%H:%M:%S")} (nach {WORK_START_TIME.strftime("%H:%M")})'
                        })

                # Problem 8: Sehr kurzer Arbeitstag (weniger als 4 Stunden)
                if len(check_ins) == len(check_outs) and len(check_ins) > 0:
                    day_sessions, day_hours, _, _ = calculate_work_sessions(day_records)
                    if day_hours < 4 and day_hours > 0:
                        all_issues.append({
                            'Datum': date_str,
                            'Problem': '📉 Kurzer Arbeitstag',
                            'Details': f'Nur {day_hours:.1f} Stunden gearbeitet'
                        })

                # Problem 9: Sehr langer Arbeitstag (mehr als 12 Stunden)
                if len(check_ins) == len(check_outs) and len(check_ins) > 0:
                    day_sessions, day_hours, _, _ = calculate_work_sessions(day_records)
                    if day_hours > 12:
                        all_issues.append({
                            'Datum': date_str,
                            'Problem': '⚠️ Übermäßig langer Tag',
                            'Details': f'{day_hours:.1f} Stunden (mehr als 12h)'
                        })

                # Problem 10: Ausstempeln vor Einstempeln
                if not check_ins.empty and not check_outs.empty:
                    first_in = check_ins.iloc[0]['Zeitstempel']
                    first_out = check_outs.iloc[0]['Zeitstempel']
                    if first_out < first_in:
                        all_issues.append({
                            'Datum': date_str,
                            'Problem': '🔄 Ausstempeln vor Einstempeln',
                            'Details': f'Aus um {first_out.strftime("%H:%M")}, Ein um {first_in.strftime("%H:%M")}'
                        })

                # Problem 11: Sehr lange Pause (mehr als 2 Stunden)
                if not break_starts.empty and not break_ends.empty:
                    for i in range(min(len(break_starts), len(break_ends))):
                        break_duration = (break_ends.iloc[i]['Zeitstempel'] - break_starts.iloc[i]['Zeitstempel']).total_seconds() / 3600
                        if break_duration > 2:
                            all_issues.append({
                                'Datum': date_str,
                                'Problem': '☕ Lange Pause',
                                'Details': f'Pause dauerte {break_duration:.1f} Stunden'
                            })
                            break

                # Problem 12: Wochenendarbeit
                if date.weekday() >= 5:
                    day_name = 'Samstag' if date.weekday() == 5 else 'Sonntag'
                    all_issues.append({
                        'Datum': date_str,
                        'Problem': '📅 Wochenendarbeit',
                        'Details': f'Arbeit am {day_name}'
                    })

            if all_issues:
                issues_df = pd.DataFrame(all_issues)
                st.dataframe(issues_df, use_container_width=True, hide_index=True)
                st.caption("Kontaktieren Sie Ihren Administrator, um Probleme zu korrigieren.")
            else:
                st.success("Keine Probleme in Ihren Zeitaufzeichnungen gefunden!")

        else:
            st.info("Keine Historie für den ausgewählten Zeitraum verfügbar.")

    with tab3:
        # Einstellungen-Tab - Passwort ändern
        st.subheader("⚙️ Kontoeinstellungen")

        st.write("**Passwort ändern:**")
        current_pwd = st.text_input("Aktuelles Passwort:", type="password", key="current_pwd")
        new_pwd1 = st.text_input("Neues Passwort:", type="password", key="new_pwd1")
        new_pwd2 = st.text_input("Neues Passwort bestätigen:", type="password", key="new_pwd2")

        if st.button("🔐 Passwort ändern"):
            if not current_pwd or not new_pwd1 or not new_pwd2:
                st.warning("Bitte alle Felder ausfüllen.")
            elif new_pwd1 != new_pwd2:
                st.error("Neue Passwörter stimmen nicht überein!")
            else:
                employee_name = authenticate_employee(st.session_state.logged_in_username, current_pwd)
                if employee_name:
                    success, message = change_employee_password(st.session_state.logged_in_username, new_pwd1)
                    if success:
                        st.success("Passwort erfolgreich geändert!")
                    else:
                        st.error(message)
                else:
                    st.error("Aktuelles Passwort ist falsch!")

    # Fußzeile
    st.divider()
    st.info("✅ Ihre Anwesenheit wird erfasst. Vielen Dank!")
    st.caption("Bei Problemen oder Korrekturen wenden Sie sich bitte an Ihren Administrator.")
