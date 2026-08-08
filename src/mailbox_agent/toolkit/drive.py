"""Google Drive backup for messages about to be trashed.

Uses the `drive.file` scope (least privilege - the app can only see files
and folders it creates itself, not your whole Drive).
"""

import io
import re
import zipfile
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from mailbox_agent import config
from mailbox_agent.toolkit.gmail_auth import load_credentials
from mailbox_agent.toolkit.models import BackupManifest, EmailSummary
from mailbox_agent.toolkit.retry import retry_read


def get_service(account_id: str):
    creds = load_credentials(account_id)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _safe_name(text: str, max_len: int = 60) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]", "", text)[:max_len].strip()
    return cleaned or "untitled"


@retry_read
def _find_folder(service, query: str) -> dict:
    return service.files().list(q=query, fields="files(id, name)").execute()


def ensure_folder(service, name: str, parent_id: str | None = None) -> str:
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    files = _find_folder(service, query).get("files", [])
    if files:
        return files[0]["id"]

    # Deliberately not retried: Drive does not enforce unique folder names,
    # so blindly retrying a create() whose response was merely lost (rather
    # than genuinely failed) risks creating a duplicate folder next to the
    # first. A real failure here aborts the sweep before anything in Gmail
    # is touched, which is the safe direction to fail in.
    body: dict[str, str | list[str]] = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    created = service.files().create(body=body, fields="id").execute()
    return created["id"]


def backup_messages_to_drive(
    gmail_service, drive_service, account_id: str, messages: list[EmailSummary], get_raw_message_fn
) -> BackupManifest:
    year = datetime.utcnow().strftime("%Y")
    root_id = ensure_folder(drive_service, config.DRIVE_BACKUP_ROOT_FOLDER)
    account_folder_id = ensure_folder(drive_service, account_id, parent_id=root_id)
    year_folder_id = ensure_folder(drive_service, year, parent_id=account_folder_id)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for msg in messages:
            raw = get_raw_message_fn(gmail_service, msg.id)
            filename = f"{msg.id}_{_safe_name(msg.subject)}.eml"
            zf.writestr(filename, raw)
    buffer.seek(0)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"backup_{account_id}_{timestamp}.zip"
    media = MediaIoBaseUpload(buffer, mimetype="application/zip", resumable=False)
    # Deliberately not retried: an upload is not idempotent (a lost response
    # after a successful write would duplicate the backup on retry). If this
    # raises, the sweep aborts here - before any approval request goes out
    # and long before anything in Gmail is touched - so the failure mode is
    # "nothing happened, try the sweep again," not data loss or duplication.
    created = (
        drive_service.files()
        .create(
            body={"name": file_name, "parents": [year_folder_id]},
            media_body=media,
            fields="id, webViewLink",
        )
        .execute()
    )

    return BackupManifest(
        drive_file_id=created["id"],
        drive_file_link=created.get("webViewLink", ""),
        message_count=len(messages),
        message_ids=[m.id for m in messages],
    )
