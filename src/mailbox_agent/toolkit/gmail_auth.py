"""Per-account OAuth for Gmail + Drive.

Each Gmail account gets its own token file under TOKENS_DIR, keyed by the
account_id you choose when onboarding (e.g. "personal", "work"). One Google
Cloud OAuth client (client_secret.json) is shared across all accounts - you
just run the consent flow once per account and pick that account in the
browser window that opens.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from mailbox_agent import config


def _token_path(account_id: str) -> Path:
    return Path(config.TOKENS_DIR) / f"{account_id}.json"


def run_oauth_flow(account_id: str) -> Credentials:
    """Interactive, one-time-per-account. Opens a browser for consent."""
    client_secret = Path(config.GOOGLE_CLIENT_SECRET_PATH)
    if not client_secret.exists():
        raise FileNotFoundError(
            f"Missing {client_secret}. Download an OAuth 'Desktop app' client "
            "from Google Cloud Console and save it there. See README.md."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), config.ALL_SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = _token_path(account_id)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


def load_credentials(account_id: str) -> Credentials:
    token_path = _token_path(account_id)
    if not token_path.exists():
        raise FileNotFoundError(
            f"No token for account '{account_id}'. Run: mailbox-agent-add-account "
            f"--id {account_id} --email <address>"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), config.ALL_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds
