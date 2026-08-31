"""
Database models for Project Google Drive Multi Mail
- Account: stores email/password for Google accounts
- DriveStorage: tracks each account's Google Drive usage
- VirtualFile: represents a logical file (may span multiple drives)
- FileChunk: represents a physical chunk stored on a specific drive
- ChunkLocation: maps chunks to their Google Drive file IDs
"""
import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean,
    ForeignKey, JSON, Enum as SAEnum, create_engine, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import enum

Base = declarative_base()


class ChunkStatus(enum.Enum):
    UPLOADED = "uploaded"
    PENDING = "pending"
    FAILED = "failed"
    DELETED = "deleted"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_encrypted = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    is_authorized = Column(Boolean, default=False)  # OAuth completed
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # OAuth tokens (encrypted)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)
    client_id = Column(String(255), nullable=True)
    client_secret = Column(String(255), nullable=True)

    drive_storage = relationship("DriveStorage", back_populates="account", uselist=False)
    chunks = relationship("FileChunk", back_populates="account")


class DriveStorage(Base):
    __tablename__ = "drive_storages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), unique=True, nullable=False)
    total_space_bytes = Column(Integer, default=0)       # e.g. 15 GB free
    used_space_bytes = Column(Integer, default=0)
    available_space_bytes = Column(Integer, default=0)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    account = relationship("Account", back_populates="drive_storage")


class Folder(Base):
    """
    A virtual folder for organizing files.
    """
    __tablename__ = "folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(512), nullable=False)
    path = Column(String(1024), unique=True, nullable=False, index=True)  # full path e.g. /work/projects
    parent_path = Column(String(1024), default="/", index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class VirtualFile(Base):
    """
    A logical file that the user uploaded.
    May be split across multiple FileChunks if >10GB.
    """
    __tablename__ = "virtual_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(512), nullable=False, index=True)
    original_size = Column(Integer, nullable=False)  # bytes
    mime_type = Column(String(255), nullable=True)
    md5_hash = Column(String(64), nullable=True, index=True)
    is_split = Column(Boolean, default=False)
    chunk_size = Column(Integer, nullable=True)  # size of each chunk when split
    num_chunks = Column(Integer, default=1)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)  # list of string tags for search
    folder_path = Column(String(1024), default="/")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    chunks = relationship("FileChunk", back_populates="virtual_file", order_by="FileChunk.chunk_index")


class FileChunk(Base):
    """
    A physical chunk of data stored on a specific drive account.
    """
    __tablename__ = "file_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    virtual_file_id = Column(Integer, ForeignKey("virtual_files.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)  # 0, 1, 2...
    chunk_size = Column(Integer, nullable=False)  # bytes
    status = Column(SAEnum(ChunkStatus), default=ChunkStatus.PENDING)
    google_drive_file_id = Column(String(255), nullable=True)  # file ID on Google Drive
    google_drive_filename = Column(String(512), nullable=True)  # filename on Drive
    md5_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    virtual_file = relationship("VirtualFile", back_populates="chunks")
    account = relationship("Account", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunk_file_index", "virtual_file_id", "chunk_index"),
    )


class SearchIndex(Base):
    """
    Full-text search index for fast file lookup.
    """
    __tablename__ = "search_index"

    id = Column(Integer, primary_key=True, autoincrement=True)
    virtual_file_id = Column(Integer, ForeignKey("virtual_files.id"), nullable=False)
    search_text = Column(Text, nullable=False)  # filename + tags + description
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index("idx_search_text", "search_text"),
    )
