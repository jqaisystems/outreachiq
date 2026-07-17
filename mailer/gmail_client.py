"""
Gmail API client for OutreachIQ.

Scopes are deliberately minimal:
  - gmail.send      -> send emails
  - gmail.readonly  -> read replies (capture only, never modify or delete)

We never request gmail.modify, so the application has no permission to trash,
delete, or alter anything in the mailbox. "Never delete emails" is enforced at
the OAuth scope level, not just in code.

One-time auth:  python authorize_gmail.py
Token is cached in token.json (gitignored) and refreshes automatically.
"""

import base64
import os
from email.mime.text import MIMEText

from config import (
    GMAIL_CLIENT_SECRET_FILE,
    GMAIL_TOKEN_FILE,
    GMAIL_SCOPES,
    GMAIL_SENDER,
)

# google libraries are imported lazily so the rest of the server runs even if
# they are not installed yet.


class GmailNotConfigured(RuntimeError):
    """Raised when Gmail credentials / token are missing."""


def _load_credentials():
    """Return valid google credentials or raise GmailNotConfigured."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise GmailNotConfigured(
            "Google API libraries not installed. Run: "
            "pip install google-api-python-client google-auth-oauthlib"
        ) from e

    if not os.path.exists(GMAIL_TOKEN_FILE):
        raise GmailNotConfigured(
            "Gmail not authorized. Run: python authorize_gmail.py"
        )

    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_FILE, GMAIL_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(GMAIL_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    if not creds or not creds.valid:
        raise GmailNotConfigured("Gmail token invalid. Re-run: python authorize_gmail.py")
    return creds


def _service():
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=_load_credentials(), cache_discovery=False)


def is_configured() -> bool:
    """True if a token exists and the libraries are importable."""
    try:
        _load_credentials()
        return True
    except GmailNotConfigured:
        return False
    except Exception:
        return False


def status() -> dict:
    """Lightweight status for the dashboard Stats tab."""
    have_secret = os.path.exists(GMAIL_CLIENT_SECRET_FILE)
    have_token = os.path.exists(GMAIL_TOKEN_FILE)
    try:
        import google.oauth2.credentials  # noqa: F401
        libs = True
    except ImportError:
        libs = False
    if not libs:
        state = "libs_missing"
    elif not have_secret:
        state = "no_client_secret"
    elif not have_token:
        state = "not_authorized"
    elif is_configured():
        state = "ok"
    else:
        state = "token_invalid"
    return {
        "state": state,
        "ok": state == "ok",
        "sender": GMAIL_SENDER,
        "scopes": GMAIL_SCOPES,
    }


def send_email(to: str, subject: str, body_text: str,
               thread_id: str | None = None) -> dict:
    """Send a plain-text email. Returns {message_id, thread_id}.

    body_text should already include the signature. If thread_id is given the
    message is sent as a reply within that Gmail thread.
    """
    service = _service()
    message = MIMEText(body_text, "plain", "utf-8")
    message["to"] = to
    message["subject"] = subject
    if GMAIL_SENDER:
        message["from"] = GMAIL_SENDER

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id

    sent = service.users().messages().send(userId="me", body=payload).execute()
    return {
        "message_id": sent.get("id", ""),
        "thread_id": sent.get("threadId", ""),
    }


def list_replies(thread_ids: list[str]) -> list[dict]:
    """For each thread, return inbound (received) messages newer than the
    thread's first message. Read-only.

    Returns: [{thread_id, message_id, from, snippet, received_at}]
    """
    if not thread_ids:
        return []
    service = _service()

    # Identify our own address so we can distinguish inbound from our sends.
    me = (GMAIL_SENDER or "").lower()
    if not me:
        try:
            profile = service.users().getProfile(userId="me").execute()
            me = (profile.get("emailAddress") or "").lower()
        except Exception:
            me = ""

    replies = []
    for tid in thread_ids:
        if not tid:
            continue
        try:
            thread = service.users().threads().get(
                userId="me", id=tid, format="metadata",
                metadataHeaders=["From", "Date"],
            ).execute()
        except Exception:
            continue
        messages = thread.get("messages", [])
        for msg in messages:
            headers = {h["name"].lower(): h["value"]
                       for h in msg.get("payload", {}).get("headers", [])}
            sender = (headers.get("from", "") or "").lower()
            label_ids = msg.get("labelIds", [])
            is_inbound = "SENT" not in label_ids and (not me or me not in sender)
            if not is_inbound:
                continue
            replies.append({
                "thread_id": tid,
                "message_id": msg.get("id", ""),
                "from": headers.get("from", ""),
                "snippet": msg.get("snippet", ""),
                "received_at": headers.get("date", ""),
            })
    return replies
