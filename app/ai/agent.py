"""
AI Agent: manages file storage decisions, search, splitting, and assembly.
Acts as the intermediary between the GUI, database, and Google Drive.
"""
import io
import os
import math
import logging
import datetime
from typing import Optional, List, Tuple, BinaryIO

from sqlalchemy.orm import Session

from app.database import manager as db
from app.database.models import ChunkStatus
from app.drive.gdrive import (
    get_drive_service, get_drive_quota, upload_file_to_drive,
    download_file_from_drive, delete_file_from_drive
)
from app.drive.splitter import FileSplitter, FileReassembler, DEFAULT_CHUNK_SIZE
from app.utils.crypto import decrypt, md5_hash

logger = logging.getLogger(__name__)


class StorageAI:
    """
    AI-powered storage management agent.
    Responsibilities:
    1. Decide whether to split a file and how
    2. Choose the best drive(s) for each chunk
    3. Upload and track chunks
    4. Search for files across all drives
    5. Reassemble files on download
    """

    def __init__(self, db_session: Session):
        self.db = db_session
        self.splitter = FileSplitter()

    # ──────────────────────── UPLOAD ────────────────────────

    def store_file(self, file_obj: BinaryIO, filename: str,
                   mime_type: str = "application/octet-stream",
                   description: str = None, tags: list = None,
                   folder_path: str = "/") -> dict:
        """
        Store a file across drives. Auto-splits if >10GB.
        Returns VirtualFile info.
        """
        # Read file content to calculate size and hash
        content = file_obj.read()
        file_size = len(content)
        file_hash = md5_hash(content)
        file_obj.seek(0)

        # Check for duplicate
        existing = db.search_files(self.db, file_hash)
        if existing:
            for vf in existing:
                if vf.md5_hash == file_hash:
                    return {
                        "status": "duplicate",
                        "file_id": vf.id,
                        "message": f"File already stored as '{vf.filename}' (ID: {vf.id})"
                    }

        # Decide: split or not?
        should_split = file_size > DEFAULT_CHUNK_SIZE
        chunk_size = DEFAULT_CHUNK_SIZE
        chunks_info = []

        if should_split:
            # Get available drives and optimal chunk size
            from app.database.models import DriveStorage
            accounts = db.get_all_accounts(self.db)
            available = []
            for acc in accounts:
                ds = self.db.query(DriveStorage).filter(
                    DriveStorage.account_id == acc.id
                ).first()
                if ds:
                    available.append(ds.available_space_bytes)

            if not available:
                return {"status": "error", "message": "No authorized drives available"}

            chunk_size = FileSplitter.get_optimal_chunk_size(available)
            chunks_info = FileSplitter.calculate_split(file_size, chunk_size)
        else:
            chunks_info = [{"index": 0, "offset": 0, "size": file_size}]

        # Create virtual file record
        vf = db.create_virtual_file(
            self.db,
            filename=filename,
            original_size=file_size,
            mime_type=mime_type,
            md5_hash=file_hash,
            is_split=should_split,
            chunk_size=chunk_size if should_split else None,
            num_chunks=len(chunks_info),
            description=description,
            tags=tags,
            folder_path=folder_path,
        )

        # Upload each chunk to the best available drive
        uploaded_chunks = []
        for chunk_info in chunks_info:
            idx = chunk_info["index"]
            size = chunk_info["size"]

            # Read chunk data
            chunk_data = content[idx * chunk_size:(idx + 1) * chunk_size]
            chunk_stream = io.BytesIO(chunk_data)
            chunk_hash = md5_hash(chunk_data)

            # Find best drive
            account = db.find_best_drive(self.db, size)
            if not account:
                # Try with minimum space
                account = db.find_best_drive(self.db, 100 * 1024 * 1024)
                if not account:
                    db.delete_virtual_file(self.db, vf.id)
                    return {"status": "error", "message": "No drive with enough space"}

            # Get Drive service and upload
            try:
                service, creds = get_drive_service(
                    account.access_token,
                    account.refresh_token,
                    account.client_id,
                    account.client_secret,
                    account.token_expiry,
                )

                chunk_filename = f"{filename}.part{idx:04d}" if should_split else filename
                drive_filename = f"gdmulti/{filename}/{chunk_filename}" if should_split else f"gdmulti/{filename}"

                result = upload_file_to_drive(
                    service, chunk_stream, drive_filename, mime_type
                )

                # Record chunk in database
                fc = db.create_file_chunk(
                    self.db,
                    virtual_file_id=vf.id,
                    account_id=account.id,
                    chunk_index=idx,
                    chunk_size=size,
                    google_drive_file_id=result["google_drive_file_id"],
                    google_drive_filename=drive_filename,
                    md5_hash=chunk_hash,
                )

                # Update drive usage
                quota = get_drive_quota(service)
                db.update_drive_space(self.db, account.id,
                                       quota["total_bytes"], quota["used_bytes"],
                                       quota["available_bytes"])

                uploaded_chunks.append(fc)

            except Exception as e:
                logger.error(f"Upload failed for chunk {idx}: {e}")
                continue

        if not uploaded_chunks:
            db.delete_virtual_file(self.db, vf.id)
            return {"status": "error", "message": "All chunk uploads failed"}

        # Update tags if provided
        if tags:
            vf.tags = tags
            search_text = f"{filename} {' '.join(tags)} {description or ''}"
            from app.database.models import SearchIndex
            si = SearchIndex(virtual_file_id=vf.id, search_text=search_text.lower())
            self.db.add(si)
            self.db.commit()

        return {
            "status": "success",
            "file_id": vf.id,
            "filename": filename,
            "size": file_size,
            "is_split": should_split,
            "num_chunks": len(uploaded_chunks),
            "chunks": [
                {
                    "index": c.chunk_index,
                    "size": c.chunk_size,
                    "drive": c.account.email,
                }
                for c in uploaded_chunks
            ]
        }

    # ──────────────────────── DOWNLOAD ────────────────────────

    def retrieve_file(self, file_id: int, output_path: str = None) -> dict:
        """
        Download and reassemble a file from its chunks.
        """
        vf = db.get_virtual_file(self.db, file_id)
        if not vf:
            return {"status": "error", "message": "File not found"}

        chunks = db.get_chunks_for_file(self.db, file_id)
        if not chunks:
            return {"status": "error", "message": "No chunks found for file"}

        chunk_streams = []
        for chunk in chunks:
            try:
                account = chunk.account
                service, _ = get_drive_service(
                    account.access_token,
                    account.refresh_token,
                    account.client_id,
                    account.client_secret,
                    account.token_expiry,
                )

                stream = io.BytesIO()
                bytes_downloaded = download_file_from_drive(
                    service, chunk.google_drive_file_id, stream
                )
                stream.seek(0)
                chunk_streams.append({
                    "index": chunk.chunk_index,
                    "stream": stream,
                })

            except Exception as e:
                logger.error(f"Download failed for chunk {chunk.chunk_index}: {e}")
                return {"status": "error", "message": f"Download failed: {e}"}

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as out:
                md5 = FileReassembler.reassemble(
                    [{"index": c["index"], "stream": c["stream"]} for c in chunk_streams],
                    output_path
                )
        else:
            # Return as in-memory stream
            merged = io.BytesIO()
            for cs in sorted(chunk_streams, key=lambda c: c["index"]):
                merged.write(cs["stream"].read())
            merged.seek(0)

        return {
            "status": "success",
            "file_id": vf.id,
            "filename": vf.filename,
            "original_size": vf.original_size,
            "output_path": output_path,
        }

    # ──────────────────────── SEARCH ────────────────────────

    def search(self, query: str) -> List[dict]:
        """Search for files by name, tag, or description."""
        results = db.search_files(self.db, query)
        return [
            {
                "file_id": vf.id,
                "filename": vf.filename,
                "size": vf.original_size,
                "is_split": vf.is_split,
                "num_chunks": vf.num_chunks,
                "tags": vf.tags or [],
                "folder": vf.folder_path,
                "created_at": vf.created_at.isoformat(),
            }
            for vf in results
        ]

    # ──────────────────────── FILE LOCATION ────────────────────────

    def get_file_location(self, file_id: int) -> dict:
        """Get detailed location info for a file (which drives, which chunks)."""
        report = db.get_chunk_locations_report(self.db, file_id)
        if not report:
            return {"status": "error", "message": "File not found"}
        return report

    # ──────────────────────── DELETE ────────────────────────

    def delete_file(self, file_id: int) -> dict:
        """Delete a file and all its chunks from all drives."""
        vf = db.get_virtual_file(self.db, file_id)
        if not vf:
            return {"status": "error", "message": "File not found"}

        chunks = db.get_chunks_for_file(self.db, file_id)
        deleted_count = 0

        for chunk in chunks:
            try:
                account = chunk.account
                service, _ = get_drive_service(
                    account.access_token,
                    account.refresh_token,
                    account.client_id,
                    account.client_secret,
                    account.token_expiry,
                )
                if chunk.google_drive_file_id:
                    delete_file_from_drive(service, chunk.google_drive_file_id)
                    deleted_count += 1

                # Update drive quota
                quota = get_drive_quota(service)
                db.update_drive_space(self.db, account.id,
                                       quota["total_bytes"], quota["used_bytes"],
                                       quota["available_bytes"])

            except Exception as e:
                logger.error(f"Failed to delete chunk: {e}")

        db.delete_virtual_file(self.db, file_id)

        return {
            "status": "success",
            "message": f"Deleted {deleted_count} chunks from drives",
        }

    # ──────────────────────── SYNC QUOTAS ────────────────────────

    def sync_drive_quotas(self) -> List[dict]:
        """Sync quota info from all authorized drives."""
        accounts = db.get_all_accounts(self.db)
        results = []

        for account in accounts:
            if not account.is_authorized:
                continue
            try:
                service, _ = get_drive_service(
                    account.access_token,
                    account.refresh_token,
                    account.client_id,
                    account.client_secret,
                    account.token_expiry,
                )
                quota = get_drive_quota(service)
                db.update_drive_space(
                    self.db, account.id,
                    quota["total_bytes"], quota["used_bytes"],
                    quota["available_bytes"]
                )
                results.append({
                    "email": account.email,
                    "total": quota["total_bytes"],
                    "used": quota["used_bytes"],
                    "available": quota["available_bytes"],
                    "status": "ok",
                })
            except Exception as e:
                results.append({
                    "email": account.email,
                    "status": "error",
                    "message": str(e),
                })

        return results
