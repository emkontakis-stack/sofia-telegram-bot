"""
google_tools.py — Google Calendar & Gmail για τη Σοφία
Αποθηκεύει tokens στο ~/.secretary/google_token.json
Credentials από ~/.secretary/google_credentials.json
"""
import json
import base64
import email as email_lib
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime, timezone, timedelta

TOKEN_PATH = Path.home() / ".secretary" / "google_token.json"
CREDS_PATH = Path.home() / ".secretary" / "google_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

def _get_creds():
    import os
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"Δεν βρέθηκε {CREDS_PATH}\n"
                    "Κατέβασε το credentials.json από Google Cloud Console και αποθήκευσέ το εκεί."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return creds

def get_calendar_events(days: int = 1) -> dict:
    """Επιστρέφει events ημερολογίου για τις επόμενες X μέρες."""
    try:
        from googleapiclient.discovery import build
        creds = _get_creds()
        service = build("calendar", "v3", credentials=creds)

        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        ).execute()

        events = result.get("items", [])
        formatted = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start:
                dt = datetime.fromisoformat(start)
                time_str = dt.strftime("%d/%m %H:%M")
            else:
                time_str = start
            formatted.append({
                "title": e.get("summary", "(χωρίς τίτλο)"),
                "time": time_str,
                "location": e.get("location", ""),
                "description": (e.get("description", "") or "")[:200],
            })
        return {"success": True, "count": len(formatted), "events": formatted}
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Calendar error: {e}"}

def send_email(to: str, subject: str, body: str) -> dict:
    """Στέλνει email μέσω Gmail."""
    try:
        from googleapiclient.discovery import build
        creds = _get_creds()
        service = build("gmail", "v1", credentials=creds)

        msg = MIMEText(body, "plain", "utf-8")
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "message": f"Email στάλθηκε στο {to}"}
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Gmail error: {e}"}

def setup_google():
    """Interactive setup για Google OAuth."""
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║        ΣΟΦΙΑ — Google Calendar & Gmail Setup         ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print("Βήματα:")
    print("1. Πήγαινε στο: https://console.cloud.google.com/")
    print("2. Δημιούργησε project → Enable APIs: Gmail API, Google Calendar API")
    print("3. OAuth 2.0 Credentials → Desktop app → Download JSON")
    print(f"4. Αποθήκευσε το ως: {CREDS_PATH}\n")

    if not CREDS_PATH.exists():
        print(f"⚠  Δεν βρέθηκε: {CREDS_PATH}")
        print("Αποθήκευσε πρώτα το credentials.json και ξανατρέξε.")
        return False

    print("✓ Credentials βρέθηκαν. Ξεκινά OAuth login στον browser...")
    try:
        _get_creds()
        print("✓ Google login επιτυχές! Tokens αποθηκεύτηκαν.")
        return True
    except Exception as e:
        print(f"✗ Σφάλμα: {e}")
        return False

# Tool definitions για τον Claude
GOOGLE_TOOL_DEFINITIONS = [
    {
        "name": "get_calendar_events",
        "description": "Επιστρέφει events από το Google Calendar. Χρήση πριν κλήση για να ελέγξεις αν ο Μάνος είναι ελεύθερος, ή για morning briefing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Πόσες μέρες μπροστά να κοιτάξει (default: 1)"},
            },
        },
    },
    {
        "name": "send_email",
        "description": "Στέλνει email μέσω Gmail. Χρήση για follow-up μετά κλήση ή αποστολή πληροφοριών.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Email παραλήπτη"},
                "subject": {"type": "string", "description": "Θέμα email"},
                "body": {"type": "string", "description": "Κείμενο email στα ελληνικά"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]
