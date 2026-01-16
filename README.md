# TimeKeeper - Employee Time Registration App

A Streamlit-based employee time tracking application that stores data in Google Sheets.

## Features

- Employee check-in/check-out with multiple sessions per day
- Break and site visit tracking
- Admin panel for managing employees and downloading reports
- Excel export for payroll (simple summary with total hours)
- Late arrival detection
- Work session history and issue detection

## Setup Instructions

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Google Sheets API**:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Sheets API"
   - Click "Enable"

### 2. Create a Service Account

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Fill in the service account details and click "Create"
4. Skip the optional steps and click "Done"
5. Click on the newly created service account email
6. Go to "Keys" tab > "Add Key" > "Create new key"
7. Select "JSON" and click "Create"
8. Save the downloaded JSON file securely

### 3. Create a Google Sheet

1. Create a new Google Sheet
2. Add these headers in Row 1: `Employee`, `Action`, `Timestamp`
3. Share the sheet with your service account email (found in the JSON file as `client_email`) with **Editor** access
4. Copy the Sheet URL

### 4. Deploy to Streamlit Cloud

1. Push this repository to GitHub
2. Go to [Streamlit Cloud](https://share.streamlit.io/)
3. Connect your GitHub repository
4. In App Settings > Secrets, add your configuration:

```toml
ADMIN_PASSWORD = "your_secure_admin_password"
SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service%40your-project.iam.gserviceaccount.com"
```

Copy all values from your downloaded JSON key file into the `[gcp_service_account]` section.

### 5. Local Development (Optional)

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
2. Fill in your actual values
3. Run: `pip install -r requirements.txt`
4. Run: `streamlit run app.py`

## Default Employees

The app comes with default test employees:
- alice / alice123
- bob / bob123
- charlie / charlie123
- diana / diana123

You can add/remove employees through the Admin panel.

## Files

- `app.py` - Main application
- `requirements.txt` - Python dependencies
- `.streamlit/secrets.toml.example` - Example secrets configuration
- `.gitignore` - Git ignore rules (secrets are excluded)

## Security Notes

- Never commit `secrets.toml` or JSON key files to version control
- Change the default admin password
- Change or remove default employee passwords in production
