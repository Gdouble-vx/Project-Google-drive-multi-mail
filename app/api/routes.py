"""
FastAPI routes for Project Google Drive Multi Mail.
"""
import io
import os
import json
import logging
import asyncio
import datetime
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy.orm import Session

from app.database import manager as db
from app.database.models import Account
from app.ai.agent import StorageAI
from app.drive.gdrive import (
    get_drive_service, get_drive_quota, setup_oauth_for_account,
    REDIRECT_URI
)
from app.utils.crypto import encrypt, decrypt

logger = logging.getLogger(__name__)

app = FastAPI(title="Google Drive Multi Mail", version="1.0.0")

# Mount static files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def get_db_session():
    db_session = db.SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


# ──────────────────────── GUI ROUTES ────────────────────────

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


# ──────────────────────── ACCOUNT API ────────────────────────

@app.post("/api/accounts")
async def add_account(
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_db_session)
):
    """Add a new Google account."""
    existing = db.get_account_by_email(session, email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    encrypted_pw = encrypt(password)
    account = db.create_account(session, email, encrypted_pw)
    return {"status": "success", "account_id": account.id, "email": email}


@app.get("/api/accounts")
async def list_accounts(session: Session = Depends(get_db_session)):
    """List all active accounts."""
    accounts = db.get_all_accounts(session)
    result = []
    for acc in accounts:
        result.append({
            "id": acc.id,
            "email": acc.email,
            "is_authorized": acc.is_authorized,
            "created_at": acc.created_at.isoformat(),
        })
    return {"accounts": result}


@app.get("/api/accounts/{account_id}")
async def get_account(account_id: int, session: Session = Depends(get_db_session)):
    """Get account details."""
    acc = db.get_account_by_id(session, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return {
        "id": acc.id,
        "email": acc.email,
        "is_authorized": acc.is_authorized,
        "is_active": acc.is_active,
        "created_at": acc.created_at.isoformat(),
    }


@app.delete("/api/accounts/{account_id}")
async def remove_account(account_id: int, session: Session = Depends(get_db_session)):
    """Deactivate an account."""
    acc = db.delete_account(session, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "success"}


# ──────────────────────── OAuth ────────────────────────

@app.get("/api/auth/url/{account_id}")
async def get_auth_url(account_id: int, session: Session = Depends(get_db_session)):
    """Get OAuth2 authorization URL for an account."""
    acc = db.get_account_by_id(session, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    import base64
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=["https://www.googleapis.com/auth/drive"],
        redirect_uri=REDIRECT_URI,
    )
    # Encode account_id into state parameter
    state = base64.urlsafe_b64encode(str(account_id).encode()).decode()
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return {"auth_url": auth_url, "account_id": account_id}


@app.get("/api/auth/callback")
async def auth_callback(code: str = Query(...), state: str = Query(None)):
    """OAuth2 callback handler - exchanges code for tokens and saves to account."""
    import base64
    from google_auth_oauthlib.flow import Flow
    from app.drive.gdrive import get_drive_quota, SCOPES
    from datetime import datetime

    session = db.SessionLocal()
    try:
        # Decode account_id from state
        account_id = int(base64.urlsafe_b64decode(state).decode()) if state else None
        if not account_id:
            raise HTTPException(status_code=400, detail="Invalid state parameter")

        # Exchange code for tokens
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
                    "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Save tokens to account
        token_expiry = creds.expiry if creds.expiry else datetime.utcnow()
        db.update_account_tokens(
            session, account_id,
            access_token=creds.token,
            refresh_token=creds.refresh_token,
            token_expiry=token_expiry,
            client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        )

        # Try to sync quota immediately
        try:
            from app.sync.background import run_sync_once
            run_sync_once()
        except Exception:
            pass

        acc = db.get_account_by_id(session, account_id)
        return {
            "status": "success",
            "message": f"Successfully connected {acc.email if acc else 'account'} to Google Drive!",
            "account_id": account_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Auth failed: {e}")
    finally:
        session.close()


# ──────────────────────── DRIVE / QUOTA API ────────────────────────

@app.get("/api/drives")
async def list_drives(session: Session = Depends(get_db_session)):
    """List all drive storages with quota info."""
    storages = db.get_all_drive_storages(session)
    results = []
    for ds in storages:
        acc = db.get_account_by_id(session, ds.account_id)
        results.append({
            "account_id": ds.account_id,
            "email": acc.email if acc else "unknown",
            "total_bytes": ds.total_space_bytes,
            "used_bytes": ds.used_space_bytes,
            "available_bytes": ds.available_space_bytes,
            "last_synced": ds.last_synced_at.isoformat() if ds.last_synced_at else None,
        })
    return {"drives": results}


@app.get("/api/drives/summary")
async def drive_summary(session: Session = Depends(get_db_session)):
    """Get aggregated storage summary."""
    summary = db.get_drive_storage_summary(session)
    return summary


@app.post("/api/drives/sync")
async def sync_drives(session: Session = Depends(get_db_session)):
    """Sync quota info from all authorized drives (manual trigger)."""
    from app.sync.background import run_sync_once, get_sync_status
    import concurrent.futures

    # Run sync in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_sync_once)
    return {"triggered": True, "result": result}


@app.get("/api/drives/sync/status")
async def sync_status():
    """Get background sync status and history."""
    from app.sync.background import get_sync_status
    return get_sync_status()


# ──────────────────────── FOLDER API ────────────────────────

@app.get("/api/folders")
async def list_folders(session: Session = Depends(get_db_session)):
    """List all folders as flat list."""
    folders = db.get_all_folders_flat(session)
    return {"folders": folders}


@app.get("/api/folders/tree")
async def folder_tree(session: Session = Depends(get_db_session)):
    """Get the full folder tree."""
    tree = db.get_folder_tree(session)
    return {"tree": tree}


@app.post("/api/folders")
async def create_folder_api(
    name: str = Form(...),
    parent_path: str = Form("/"),
    session: Session = Depends(get_db_session)
):
    """Create a new folder."""
    path = parent_path.rstrip("/") + "/" + name if parent_path != "/" else "/" + name
    existing = db.get_folder_by_path(session, path)
    if existing:
        raise HTTPException(status_code=400, detail="Folder already exists")
    folder = db.create_folder(session, name, path, parent_path)
    return {"status": "success", "path": folder.path, "name": folder.name}


@app.delete("/api/folders/{path:path}")
async def delete_folder_api(path: str, session: Session = Depends(get_db_session)):
    """Delete a folder."""
    path = "/" + path if not path.startswith("/") else path
    folder = db.delete_folder(session, path)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"status": "success"}


# ──────────────────────── FILE API ────────────────────────

@app.get("/api/uploads")
async def list_uploads():
    """List all active uploads with progress."""
    from app.ws.manager import upload_manager
    return {"uploads": upload_manager.get_all_uploads()}


@app.websocket("/ws/upload")
async def websocket_upload(websocket: WebSocket):
    """
    WebSocket upload endpoint.
    
    Protocol:
    1. Server accepts connection, sends {type: "connected", upload_id: "..."}
    2. Client sends {type: "start", filename, file_size, mime_type, ...}
    3. Server acknowledges {type: "started", upload_id, ...}
    4. Client sends binary chunks: {type: "chunk", index: N} followed by binary data
       OR sends the entire file as binary frames
    5. Server processes each chunk, uploads to Drive, sends progress
    6. Client sends {type: "finish"} when all data sent
    7. Server sends {type: "complete", file_id, ...}
    """
    from app.ws.manager import upload_manager, UploadPhase
    from app.drive.splitter import FileSplitter, DEFAULT_CHUNK_SIZE
    import hashlib

    upload_id = await upload_manager.connect(websocket)

    try:
        # Phase 1: Wait for file metadata
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "start":
                # Client is starting a new upload
                filename = msg.get("filename", "unknown")
                file_size = int(msg.get("file_size", 0))
                mime_type = msg.get("mime_type", "application/octet-stream")
                description = msg.get("description", "")
                tags = msg.get("tags", "")
                folder_path = msg.get("folder_path", "/")

                # Create upload state
                state = upload_manager.create_upload(
                    upload_id, filename, file_size, mime_type,
                    description, tags, folder_path
                )

                # Calculate chunks
                should_split = file_size > DEFAULT_CHUNK_SIZE
                if should_split:
                    chunks_info = FileSplitter.calculate_split(file_size, DEFAULT_CHUNK_SIZE)
                    state.total_chunks = len(chunks_info)
                    state.chunk_size = DEFAULT_CHUNK_SIZE
                else:
                    state.total_chunks = 1
                    state.chunk_size = file_size

                await upload_manager.send(upload_id, {
                    "type": "started",
                    **state.to_dict(),
                })

                # Phase 2: Receive file data chunks
                all_data = bytearray()
                chunks_received = 0

                while True:
                    chunk_msg = await websocket.receive()

                    if chunk_msg["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect()

                    # Binary frame = file data
                    if "bytes" in chunk_msg and chunk_msg["bytes"]:
                        data = chunk_msg["bytes"]
                        all_data.extend(data)
                        chunks_received += 1

                        # Update read progress
                        read_pct = min(80.0, (len(all_data) / max(file_size, 1)) * 80)
                        await upload_manager.update_and_broadcast(
                            upload_id,
                            phase=UploadPhase.READING,
                            progress=read_pct,
                            bytes_processed=len(all_data),
                        )

                    # JSON frame = control message
                    elif "text" in chunk_msg and chunk_msg["text"]:
                        ctrl = json.loads(chunk_msg["text"])
                        ctrl_type = ctrl.get("type", "")

                        if ctrl_type == "finish":
                            # All data received, start processing
                            break

                        elif ctrl_type == "cancel":
                            await upload_manager.cancel_upload(upload_id)
                            return

                # Phase 3: Process and upload to Google Drive
                await upload_manager.update_and_broadcast(
                    upload_id,
                    phase=UploadPhase.SPLITTING,
                    progress=80,
                )

                # Get DB session and agent
                session = db.SessionLocal()
                try:
                    agent = StorageAI(session)
                    file_obj = io.BytesIO(bytes(all_data))

                    tag_list = [t.strip() for t in tags.split(",")] if tags else None

                    # The agent.store_file will handle splitting + Drive upload
                    # We wrap it with progress callbacks
                    tag_list_str = tags

                    await upload_manager.update_and_broadcast(
                        upload_id,
                        phase=UploadPhase.UPLOADING,
                        progress=85,
                    )

                    # Run the actual store in thread pool to not block WebSocket
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        lambda: agent.store_file(
                            io.BytesIO(bytes(all_data)),
                            filename=filename,
                            mime_type=mime_type,
                            description=description,
                            tags=tag_list,
                            folder_path=folder_path,
                        )
                    )

                    if result.get("status") == "error":
                        await upload_manager.error_upload(upload_id, result.get("message", "Upload failed"))
                    elif result.get("status") == "duplicate":
                        await upload_manager.error_upload(upload_id, result.get("message", "Duplicate file"))
                    else:
                        await upload_manager.complete_upload(
                            upload_id,
                            file_id=result.get("file_id"),
                            is_split=result.get("is_split", False),
                            num_chunks=result.get("num_chunks", 1),
                            chunks=result.get("chunks", []),
                        )

                finally:
                    session.close()

                # Reset for next potential file on same connection
                # (client can send another "start" message)

            elif msg_type == "close":
                await websocket.close()
                return

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {upload_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await upload_manager.error_upload(upload_id, str(e))
    finally:
        upload_manager.disconnect(upload_id)


@app.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    description: str = Form(None),
    tags: str = Form(None),  # comma-separated
    folder_path: str = Form("/"),
    session: Session = Depends(get_db_session)
):
    """Upload a file. Auto-splits if >10GB."""
    agent = StorageAI(session)

    content = await file.read()
    file_obj = io.BytesIO(content)

    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    result = agent.store_file(
        file_obj,
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        description=description,
        tags=tag_list,
        folder_path=folder_path,
    )

    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@app.get("/api/files")
async def list_files(
    folder: str = Query("/", alias="folder"),
    session: Session = Depends(get_db_session)
):
    """List files in a folder."""
    files = db.get_files_in_folder(session, folder)
    return {
        "files": [
            {
                "file_id": vf.id,
                "filename": vf.filename,
                "size": vf.original_size,
                "is_split": vf.is_split,
                "num_chunks": vf.num_chunks,
                "tags": vf.tags or [],
                "folder": vf.folder_path,
                "mime_type": vf.mime_type,
                "created_at": vf.created_at.isoformat(),
            }
            for vf in files
        ]
    }


@app.get("/api/files/all")
async def list_all_files(session: Session = Depends(get_db_session)):
    """List all files."""
    files = db.get_all_files(session)
    return {
        "files": [
            {
                "file_id": vf.id,
                "filename": vf.filename,
                "size": vf.original_size,
                "is_split": vf.is_split,
                "num_chunks": vf.num_chunks,
                "tags": vf.tags or [],
                "folder": vf.folder_path,
                "mime_type": vf.mime_type,
                "created_at": vf.created_at.isoformat(),
            }
            for vf in files
        ]
    }


@app.get("/api/files/{file_id}")
async def get_file_info(file_id: int, session: Session = Depends(get_db_session)):
    """Get detailed file info."""
    vf = db.get_virtual_file(session, file_id)
    if not vf:
        raise HTTPException(status_code=404, detail="File not found")

    agent = StorageAI(session)
    location = agent.get_file_location(file_id)

    return {
        "file_id": vf.id,
        "filename": vf.filename,
        "size": vf.original_size,
        "is_split": vf.is_split,
        "num_chunks": vf.num_chunks,
        "chunk_size": vf.chunk_size,
        "tags": vf.tags or [],
        "description": vf.description,
        "folder": vf.folder_path,
        "mime_type": vf.mime_type,
        "md5_hash": vf.md5_hash,
        "created_at": vf.created_at.isoformat(),
        "locations": location,
    }


@app.get("/api/files/{file_id}/download")
async def download_file(file_id: int, session: Session = Depends(get_db_session)):
    """Download a file - streams the actual file content to the client."""
    import io as _io
    from starlette.responses import StreamingResponse
    from app.drive.gdrive import download_file_from_drive, get_drive_service
    from app.database.models import ChunkStatus

    vf = db.get_virtual_file(session, file_id)
    if not vf:
        raise HTTPException(status_code=404, detail="File not found")

    chunks = db.get_chunks_for_file(session, file_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="No chunks found for this file")

    try:
        # For single-chunk files, stream directly from Drive
        if len(chunks) == 1:
            chunk = chunks[0]
            account = chunk.account
            service, _ = get_drive_service(
                account.access_token, account.refresh_token,
                account.client_id, account.client_secret, account.token_expiry,
            )
            stream = _io.BytesIO()
            download_file_from_drive(service, chunk.google_drive_file_id, stream)
            stream.seek(0)

            mime = vf.mime_type or 'application/octet-stream'
            return StreamingResponse(
                iter([stream.read()]),
                media_type=mime,
                headers={
                    "Content-Disposition": f'attachment; filename="{vf.filename}"',
                    "Content-Length": str(vf.original_size),
                }
            )

        # For split files, merge chunks then stream
        else:
            merged = _io.BytesIO()
            for chunk in sorted(chunks, key=lambda c: c.chunk_index):
                account = chunk.account
                service, _ = get_drive_service(
                    account.access_token, account.refresh_token,
                    account.client_id, account.client_secret, account.token_expiry,
                )
                chunk_stream = _io.BytesIO()
                download_file_from_drive(service, chunk.google_drive_file_id, chunk_stream)
                chunk_stream.seek(0)
                merged.write(chunk_stream.read())

            merged.seek(0)
            mime = vf.mime_type or 'application/octet-stream'
            return StreamingResponse(
                iter([merged.read()]),
                media_type=mime,
                headers={
                    "Content-Disposition": f'attachment; filename="{vf.filename}"',
                    "Content-Length": str(vf.original_size),
                }
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


class BatchMoveRequest(BaseModel):
    file_ids: List[int]
    folder_path: str


@app.patch("/api/files/{file_id}/move")
async def move_file(
    file_id: int,
    folder_path: str = Form(...),
    session: Session = Depends(get_db_session)
):
    """Move a file to a different folder."""
    vf = db.get_virtual_file(session, file_id)
    if not vf:
        raise HTTPException(status_code=404, detail="File not found")

    # Normalize path
    folder_path = folder_path.rstrip("/") if folder_path != "/" else "/"
    if not folder_path.startswith("/"):
        folder_path = "/" + folder_path

    vf.folder_path = folder_path
    session.commit()
    session.refresh(vf)

    return {
        "status": "success",
        "file_id": vf.id,
        "filename": vf.filename,
        "folder_path": vf.folder_path,
    }


@app.patch("/api/files/batch-move")
async def batch_move_files(
    request: BatchMoveRequest,
    session: Session = Depends(get_db_session)
):
    """Move multiple files to a different folder."""
    # Normalize path
    folder_path = request.folder_path.rstrip("/") if request.folder_path != "/" else "/"
    if not folder_path.startswith("/"):
        folder_path = "/" + folder_path

    moved = []
    errors = []
    for fid in request.file_ids:
        vf = db.get_virtual_file(session, fid)
        if not vf:
            errors.append({"file_id": fid, "error": "File not found"})
            continue
        vf.folder_path = folder_path
        moved.append({"file_id": fid, "filename": vf.filename})

    session.commit()

    return {
        "status": "success",
        "moved": len(moved),
        "errors": len(errors),
        "files": moved,
        "error_details": errors,
        "folder_path": folder_path,
    }


class CopyFileRequest(BaseModel):
    folder_path: str
    new_filename: Optional[str] = None


@app.post("/api/files/{file_id}/copy")
async def copy_file(
    file_id: int,
    request: CopyFileRequest,
    session: Session = Depends(get_db_session)
):
    """Copy a file's metadata to a new folder (same chunks, new VirtualFile record)."""
    vf = db.get_virtual_file(session, file_id)
    if not vf:
        raise HTTPException(status_code=404, detail="File not found")

    # Normalize path
    folder_path = request.folder_path.rstrip("/") if request.folder_path != "/" else "/"
    if not folder_path.startswith("/"):
        folder_path = "/" + folder_path

    new_filename = request.new_filename or vf.filename

    # Create new VirtualFile with same properties
    new_vf = db.create_virtual_file(
        session,
        filename=new_filename,
        original_size=vf.original_size,
        mime_type=vf.mime_type,
        md5_hash=vf.md5_hash,
        is_split=vf.is_split,
        chunk_size=vf.chunk_size,
        num_chunks=vf.num_chunks,
        description=vf.description,
        tags=list(vf.tags) if vf.tags else None,
        folder_path=folder_path,
    )

    # Copy chunk records (same Drive file IDs, new VirtualFile reference)
    chunks = db.get_chunks_for_file(session, file_id)
    for chunk in chunks:
        db.create_file_chunk(
            session,
            virtual_file_id=new_vf.id,
            account_id=chunk.account_id,
            chunk_index=chunk.chunk_index,
            chunk_size=chunk.chunk_size,
            google_drive_file_id=chunk.google_drive_file_id,
            google_drive_filename=chunk.google_drive_filename,
            md5_hash=chunk.md5_hash,
        )

    return {
        "status": "success",
        "file_id": new_vf.id,
        "filename": new_vf.filename,
        "folder_path": new_vf.folder_path,
    }


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: int, session: Session = Depends(get_db_session)):
    """Delete a file and all its chunks."""
    agent = StorageAI(session)
    result = agent.delete_file(file_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.get("/api/files/{file_id}/location")
async def file_location(file_id: int, session: Session = Depends(get_db_session)):
    """Get chunk location report for a file."""
    agent = StorageAI(session)
    report = agent.get_file_location(file_id)
    if "error" in str(report.get("status", "")):
        raise HTTPException(status_code=404, detail="File not found")
    return report


@app.get("/api/files/{file_id}/preview")
async def file_preview(file_id: int, session: Session = Depends(get_db_session)):
    """
    Get file content for inline preview.
    Returns base64 data for images, plain text for text/code, or metadata for others.
    Max preview size: 5MB.
    """
    import base64
    import mimetypes

    vf = db.get_virtual_file(session, file_id)
    if not vf:
        raise HTTPException(status_code=404, detail="File not found")

    mime = vf.mime_type or mimetypes.guess_type(vf.filename)[0] or "application/octet-stream"

    # Define previewable types
    TEXT_TYPES = {"text/", "application/json", "application/xml", "application/javascript",
                  "application/x-python", "application/x-yaml", "text/x-"}
    IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml", "image/bmp"}
    PDF_TYPES = {"application/pdf"}
    CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
                  ".xml", ".yaml", ".yml", ".md", ".txt", ".csv", ".sql",
                  ".sh", ".bash", ".bat", ".c", ".cpp", ".h", ".java",
                  ".go", ".rs", ".rb", ".php", ".swift", ".kt"}

    ext = "." + vf.filename.rsplit(".", 1)[-1].lower() if "." in vf.filename else ""

    is_text = any(mime.startswith(t) for t in TEXT_TYPES) or ext in CODE_EXTS
    is_image = mime in IMAGE_TYPES
    is_pdf = mime in PDF_TYPES

    MAX_PREVIEW = 5 * 1024 * 1024  # 5MB

    if not (is_text or is_image or is_pdf):
        return {
            "previewable": False,
            "mime_type": mime,
            "filename": vf.filename,
            "message": f"Cannot preview {mime} files",
        }

    if vf.original_size > MAX_PREVIEW:
        return {
            "previewable": False,
            "mime_type": mime,
            "filename": vf.filename,
            "message": f"File too large for preview ({formatBytes(vf.original_size)}, max {formatBytes(MAX_PREVIEW)})",
        }

    try:
        # Download the file content
        agent = StorageAI(session)
        import io
        chunks = db.get_chunks_for_file(session, file_id)
        if not chunks:
            return {"previewable": False, "message": "No chunks found"}

        # For single-chunk files, download directly
        chunk = chunks[0]
        account = chunk.account
        service, _ = get_drive_service(
            account.access_token, account.refresh_token,
            account.client_id, account.client_secret, account.token_expiry,
        )
        stream = io.BytesIO()
        from app.drive.gdrive import download_file_from_drive
        download_file_from_drive(service, chunk.google_drive_file_id, stream)
        stream.seek(0)
        content = stream.read()

        if is_image:
            b64 = base64.b64encode(content).decode()
            return {
                "previewable": True,
                "type": "image",
                "mime_type": mime,
                "data": f"data:{mime};base64,{b64}",
                "filename": vf.filename,
                "size": vf.original_size,
            }
        elif is_pdf:
            b64 = base64.b64encode(content).decode()
            return {
                "previewable": True,
                "type": "pdf",
                "mime_type": mime,
                "data": f"data:application/pdf;base64,{b64}",
                "filename": vf.filename,
                "size": vf.original_size,
            }
        else:  # text/code
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
            return {
                "previewable": True,
                "type": "text",
                "mime_type": mime,
                "content": text,
                "filename": vf.filename,
                "size": vf.original_size,
                "language": ext.lstrip("."),
            }

    except Exception as e:
        return {
            "previewable": False,
            "message": f"Preview failed: {str(e)}",
        }


def formatBytes(bytes_val):
    if not bytes_val or bytes_val == 0:
        return '0 B'
    k = 1024
    sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    i = min(len(sizes) - 1, int(__import__('math').log(bytes_val) / __import__('math').log(k)))
    return f"{bytes_val / k**i:.2f} {sizes[i]}"


# ──────────────────────── SEARCH API ────────────────────────

@app.get("/api/search")
async def search_files(
    q: str = Query(..., description="Search query"),
    session: Session = Depends(get_db_session)
):
    """Search files by name, tags, or description."""
    agent = StorageAI(session)
    results = agent.search(q)
    return {"query": q, "results": results}


# ──────────────────────── HEALTH ────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Google Drive Multi Mail"}
