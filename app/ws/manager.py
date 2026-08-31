"""
WebSocket manager for real-time upload progress.
Handles client connections, broadcasts progress updates, and tracks upload state.
"""
import asyncio
import json
import logging
import time
import uuid
import datetime
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class UploadPhase(str, Enum):
    QUEUED = "queued"
    READING = "reading"
    SPLITTING = "splitting"
    UPLOADING = "uploading"      # uploading chunk to Google Drive
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class FileUploadState:
    """Tracks the state of a single file upload."""
    upload_id: str
    filename: str
    file_size: int
    mime_type: str
    description: str = ""
    tags: str = ""
    folder_path: str = "/"

    phase: UploadPhase = UploadPhase.QUEUED
    progress: float = 0.0           # 0.0 to 100.0
    bytes_processed: int = 0
    speed_bytes_per_sec: float = 0.0
    eta_seconds: Optional[float] = None
    error_message: str = ""

    # Chunk tracking
    total_chunks: int = 0
    current_chunk: int = 0
    chunk_size: int = 0

    # Result
    file_id: Optional[int] = None
    is_split: bool = False
    num_chunks_uploaded: int = 0
    chunks_info: list = field(default_factory=list)

    # Timing
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "upload_id": self.upload_id,
            "filename": self.filename,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "phase": self.phase.value,
            "progress": round(self.progress, 1),
            "bytes_processed": self.bytes_processed,
            "speed_bps": round(self.speed_bytes_per_sec),
            "eta_seconds": round(self.eta_seconds) if self.eta_seconds else None,
            "error": self.error_message,
            "total_chunks": self.total_chunks,
            "current_chunk": self.current_chunk,
            "chunk_size": self.chunk_size,
            "file_id": self.file_id,
            "is_split": self.is_split,
            "num_chunks_uploaded": self.num_chunks_uploaded,
            "chunks": self.chunks_info,
            "elapsed": round(time.time() - self.started_at, 1) if self.started_at else 0,
        }

    def update_progress(self, bytes_done: int, phase: UploadPhase = None):
        if phase:
            self.phase = phase
        self.bytes_processed = bytes_done
        if self.file_size > 0:
            self.progress = min(100.0, (bytes_done / self.file_size) * 100)

        # Calculate speed and ETA
        if self.started_at:
            elapsed = time.time() - self.started_at
            if elapsed > 0:
                self.speed_bytes_per_sec = bytes_done / elapsed
                remaining = self.file_size - bytes_done
                if self.speed_bytes_per_sec > 0:
                    self.eta_seconds = remaining / self.speed_bytes_per_sec
                else:
                    self.eta_seconds = None


class UploadManager:
    """Manages WebSocket connections and upload state."""

    def __init__(self):
        # upload_id -> WebSocket connection
        self._connections: Dict[str, WebSocket] = {}
        # upload_id -> FileUploadState
        self._uploads: Dict[str, FileUploadState] = {}
        # All active upload IDs
        self._active: Set[str] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection and return upload_id."""
        await websocket.accept()
        upload_id = str(uuid.uuid4())[:12]

        async with self._lock:
            self._connections[upload_id] = websocket
            self._active.add(upload_id)

        logger.info(f"WebSocket connected: {upload_id}")
        return upload_id

    def disconnect(self, upload_id: str):
        """Remove a WebSocket connection."""
        self._connections.pop(upload_id, None)
        self._active.discard(upload_id)
        logger.info(f"WebSocket disconnected: {upload_id}")

    async def send(self, upload_id: str, message: dict):
        """Send a JSON message to a specific client."""
        ws = self._connections.get(upload_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to {upload_id}: {e}")
                self.disconnect(upload_id)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        disconnected = []
        for uid, ws in self._connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(uid)
        for uid in disconnected:
            self.disconnect(uid)

    # ─────────── Upload State Management ───────────

    def create_upload(self, upload_id: str, filename: str, file_size: int,
                      mime_type: str = "", description: str = "",
                      tags: str = "", folder_path: str = "/") -> FileUploadState:
        """Register a new file upload."""
        state = FileUploadState(
            upload_id=upload_id,
            filename=filename,
            file_size=file_size,
            mime_type=mime_type,
            description=description,
            tags=tags,
            folder_path=folder_path,
            started_at=time.time(),
        )
        self._uploads[upload_id] = state
        return state

    def get_upload(self, upload_id: str) -> Optional[FileUploadState]:
        return self._uploads.get(upload_id)

    def remove_upload(self, upload_id: str):
        self._uploads.pop(upload_id, None)

    def get_all_uploads(self) -> list:
        return [s.to_dict() for s in self._uploads.values()]

    # ─────────── Progress Helpers ───────────

    async def update_and_broadcast(self, upload_id: str, **kwargs):
        """Update upload state and broadcast progress to client."""
        state = self._uploads.get(upload_id)
        if not state:
            return

        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)

        await self.send(upload_id, {
            "type": "progress",
            **state.to_dict(),
        })

    async def complete_upload(self, upload_id: str, file_id: int,
                               is_split: bool, num_chunks: int, chunks: list):
        """Mark upload as complete and notify client."""
        state = self._uploads.get(upload_id)
        if not state:
            return

        state.phase = UploadPhase.COMPLETE
        state.progress = 100.0
        state.bytes_processed = state.file_size
        state.file_id = file_id
        state.is_split = is_split
        state.num_chunks_uploaded = num_chunks
        state.chunks_info = chunks
        state.completed_at = time.time()

        await self.send(upload_id, {
            "type": "complete",
            **state.to_dict(),
        })

    async def error_upload(self, upload_id: str, message: str):
        """Mark upload as failed and notify client."""
        state = self._uploads.get(upload_id)
        if not state:
            return

        state.phase = UploadPhase.ERROR
        state.error_message = message
        state.completed_at = time.time()

        await self.send(upload_id, {
            "type": "error",
            **state.to_dict(),
        })

    async def cancel_upload(self, upload_id: str):
        """Cancel an in-progress upload."""
        state = self._uploads.get(upload_id)
        if state:
            state.phase = UploadPhase.CANCELLED
            await self.send(upload_id, {
                "type": "cancelled",
                **state.to_dict(),
            })
        self.remove_upload(upload_id)


# Singleton instance
upload_manager = UploadManager()
