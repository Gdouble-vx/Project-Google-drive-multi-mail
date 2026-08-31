"""
Google Drive integration:
- OAuth2 authentication (auto-refresh, no CAPTCHA)
- Upload / download files
- Get drive quota info
- List files

Uses google-api-python-client + google-auth-oauthlib for refresh token flow.
"""
import os
import io
import datetime
import logging
from typing import Optional, BinaryIO

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()  # Ensure .env is loaded before reading env vars

from app.utils.crypto import encrypt, decrypt

logger = logging.getLogger(__name__)

# Default Google API scopes
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Default client ID/secret (user should set their own in config)
DEFAULT_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
DEFAULT_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
APP_PORT = int(os.environ.get("PORT", 8095)) or 8095
REDIRECT_URI = f"http://localhost:{APP_PORT}/api/auth/callback"


def get_drive_service(access_token: str, refresh_token: str,
                      client_id: str = None, client_secret: str = None,
                      token_expiry: datetime.datetime = None):
    """Build a Google Drive service with auto-refreshing credentials."""
    cid = client_id or DEFAULT_CLIENT_ID
    csecret = client_secret or DEFAULT_CLIENT_SECRET

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cid,
        client_secret=csecret,
        scopes=SCOPES,
    )

    if creds.expired or not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise

    service = build("drive", "v3", credentials=creds)
    return service, creds


def get_drive_quota(service) -> dict:
    """Get drive storage quota information."""
    about = service.about().get(fields="storageQuota").execute()
    quota = about.get("storageQuota", {})
    return {
        "total_bytes": int(quota.get("limit", 0)),
        "used_bytes": int(quota.get("usage", 0)),
        "available_bytes": int(quota.get("limit", 0)) - int(quota.get("usage", 0)),
    }


def upload_file_to_drive(service, file_obj: BinaryIO, filename: str,
                          mime_type: str = "application/octet-stream",
                          folder_id: str = None, chunk_size: int = 5 * 1024 * 1024) -> dict:
    """Upload a file to Google Drive. Returns metadata dict."""
    file_metadata = {"name": filename}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(file_obj, mimetype=mime_type, chunksize=chunk_size, resumable=True)

    result = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,name,mimeType,size",
    ).execute()

    return {
        "google_drive_file_id": result.get("id"),
        "name": result.get("name"),
        "mimeType": result.get("mimeType"),
        "size": int(result.get("size", 0)),
    }


def download_file_from_drive(service, google_drive_file_id: str, output: BinaryIO) -> int:
    """Download a file from Google Drive. Returns bytes downloaded."""
    request = service.files().get_media(fileId=google_drive_file_id)
    downloader = MediaIoBaseDownload(output, request, chunksize=5 * 1024 * 1024)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    # Get file size from the output buffer
    current_pos = output.tell()
    output.seek(0, 2)  # seek to end
    total_bytes = output.tell()
    output.seek(current_pos)  # seek back

    return total_bytes


def delete_file_from_drive(service, google_drive_file_id: str) -> bool:
    """Delete a file from Google Drive."""
    try:
        service.files().delete(fileId=google_drive_file_id).execute()
        return True
    except HttpError as e:
        logger.error(f"Delete failed: {e}")
        return False


def list_files_in_drive(service, folder_id: str = None, page_size: int = 100) -> list:
    """List files in drive (optionally in a specific folder)."""
    query = ""
    if folder_id:
        query = f"'{folder_id}' in parents"

    results = service.files().list(
        q=query,
        pageSize=page_size,
        fields="nextPageToken, files(id, name, mimeType, size, createdTime)",
    ).execute()

    return results.get("files", [])


def create_folder(service, folder_name: str, parent_id: str = None) -> str:
    """Create a folder in Google Drive. Returns folder ID."""
    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        file_metadata["parents"] = [parent_id]

    result = service.files().create(
        body=file_metadata,
        fields="id",
    ).execute()

    return result.get("id")


def setup_oauth_for_account(email: str, auth_code: str,
                             client_id: str = None, client_secret: str = None) -> dict:
    """
    Exchange an authorization code for tokens.
    This is called after the user completes the OAuth consent flow.
    Returns dict with access_token, refresh_token, expiry.
    """
    from google_auth_oauthlib.flow import Flow

    cid = client_id or DEFAULT_CLIENT_ID
    csecret = client_secret or DEFAULT_CLIENT_SECRET

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": cid,
                "client_secret": csecret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = REDIRECT_URI

    flow.fetch_token(code=auth_code)
    creds = flow.credentials

    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
        "client_id": cid,
        "client_secret": csecret,
    }
