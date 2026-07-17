"""
One-time Gmail authorization for OutreachIQ.

Setup (once):
  1. console.cloud.google.com -> new project -> enable "Gmail API".
  2. APIs & Services -> OAuth consent screen -> External -> Testing mode,
     add your Gmail address as a test user.
  3. Credentials -> Create OAuth client ID -> Desktop app -> download JSON,
     save it as client_secret.json in this folder.
  4. Run:  python authorize_gmail.py
     A browser opens, grant access. A token.json is written and reused after.

Scopes requested: gmail.send + gmail.readonly only. No delete/modify scope.
"""

import os
import sys

from config import GMAIL_CLIENT_SECRET_FILE, GMAIL_TOKEN_FILE, GMAIL_SCOPES


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing libraries. Run:\n  pip install google-api-python-client google-auth-oauthlib")
        return 1

    if not os.path.exists(GMAIL_CLIENT_SECRET_FILE):
        print(f"Missing {GMAIL_CLIENT_SECRET_FILE}.")
        print("Download an OAuth 'Desktop app' client from Google Cloud Console and save it there.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CLIENT_SECRET_FILE, GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    with open(GMAIL_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print(f"Authorized. Token saved to {GMAIL_TOKEN_FILE}")
    print("Scopes:", ", ".join(GMAIL_SCOPES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
