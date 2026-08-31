"""
Database manager: connection, session, and CRUD operations.
"""
import os
import datetime
from typing import Optional, List, Tuple
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import sessionmaker, Session

from app.database.models import (
    Base, Account, DriveStorage, VirtualFile, FileChunk,
    SearchIndex, ChunkStatus, Folder
)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "gdrive_multi.db")
DATABASE_URL = f"sqlite:///{os.path.abspath(DB_PATH)}"


def get_engine():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return create_engine(DATABASE_URL, echo=False)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency for DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ──────────────────────────── Account CRUD ────────────────────────────

def create_account(db: Session, email: str, password_encrypted: str) -> Account:
    acc = Account(email=email, password_encrypted=password_encrypted)
    db.add(acc)
    db.flush()
    ds = DriveStorage(account_id=acc.id)
    db.add(ds)
    db.commit()
    db.refresh(acc)
    return acc


def get_account_by_email(db: Session, email: str) -> Optional[Account]:
    return db.query(Account).filter(Account.email == email).first()


def get_account_by_id(db: Session, account_id: int) -> Optional[Account]:
    return db.query(Account).filter(Account.id == account_id).first()


def get_all_accounts(db: Session) -> List[Account]:
    return db.query(Account).filter(Account.is_active == True).all()


def update_account_tokens(db: Session, account_id: int, access_token: str,
                           refresh_token: str, token_expiry: datetime.datetime,
                           client_id: str = None, client_secret: str = None):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if acc:
        acc.access_token = access_token
        acc.refresh_token = refresh_token
        acc.token_expiry = token_expiry
        acc.is_authorized = True
        if client_id:
            acc.client_id = client_id
        if client_secret:
            acc.client_secret = client_secret
        db.commit()
    return acc


def delete_account(db: Session, account_id: int):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if acc:
        acc.is_active = False
        db.commit()
    return acc


# ──────────────────────────── Drive Storage CRUD ────────────────────────────

def update_drive_space(db: Session, account_id: int, total: int, used: int, available: int):
    ds = db.query(DriveStorage).filter(DriveStorage.account_id == account_id).first()
    if ds:
        ds.total_space_bytes = total
        ds.used_space_bytes = used
        ds.available_space_bytes = available
        ds.last_synced_at = datetime.datetime.utcnow()
        db.commit()
    return ds


def get_drive_storage_summary(db: Session) -> dict:
    """Get aggregated storage across all drives."""
    result = db.query(
        func.sum(DriveStorage.total_space_bytes),
        func.sum(DriveStorage.used_space_bytes),
        func.sum(DriveStorage.available_space_bytes),
    ).first()
    return {
        "total_bytes": result[0] or 0,
        "used_bytes": result[1] or 0,
        "available_bytes": result[2] or 0,
    }


def get_all_drive_storages(db: Session) -> List[DriveStorage]:
    return db.query(DriveStorage).all()


def find_best_drive(db: Session, size_bytes: int) -> Optional[Account]:
    """Find the drive account with enough available space."""
    accounts = db.query(Account).join(DriveStorage).filter(
        Account.is_active == True,
        Account.is_authorized == True,
        DriveStorage.available_space_bytes >= size_bytes
    ).order_by(DriveStorage.available_space_bytes.desc()).first()
    return accounts


# ──────────────────────────── Folder CRUD ────────────────────────────

def create_folder(db: Session, name: str, path: str, parent_path: str = "/") -> Folder:
    """Create a folder. Also auto-creates any missing parent folders."""
    # Auto-create parent folders
    parts = [p for p in parent_path.split("/") if p]
    for i in range(len(parts)):
        p_path = "/" + "/".join(parts[:i + 1])
        p_name = parts[i]
        existing = db.query(Folder).filter(Folder.path == p_path).first()
        if not existing:
            pp = "/" + "/".join(parts[:i]) if i > 0 else "/"
            db.add(Folder(name=p_name, path=p_path, parent_path=pp))
    db.commit()

    # Create the target folder
    existing = db.query(Folder).filter(Folder.path == path).first()
    if existing:
        return existing

    folder = Folder(name=name, path=path, parent_path=parent_path)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def get_folder_by_path(db: Session, path: str) -> Optional[Folder]:
    return db.query(Folder).filter(Folder.path == path).first()


def get_child_folders(db: Session, parent_path: str = "/") -> List[Folder]:
    return db.query(Folder).filter(Folder.parent_path == parent_path).order_by(Folder.name).all()


def get_folder_tree(db: Session) -> dict:
    """Build a nested folder tree from all folders."""
    all_folders = db.query(Folder).order_by(Folder.path).all()
    all_files = db.query(VirtualFile).all()

    # Build tree: {path: {name, children: {}, file_count}}
    tree = {"/": {"name": "/", "children": {}, "file_count": 0, "folder_id": None}}

    for f in all_folders:
        tree[f.path] = {
            "name": f.name,
            "children": {},
            "file_count": 0,
            "folder_id": f.id,
        }

    # Count files per folder
    for vf in all_files:
        fp = vf.folder_path or "/"
        if fp in tree:
            tree[fp]["file_count"] += 1

    # Build parent-child relationships
    for f in all_folders:
        if f.parent_path in tree:
            tree[f.parent_path]["children"][f.path] = tree[f.path]

    return tree


def get_all_folders_flat(db: Session) -> List[dict]:
    """Get all folders as a flat list with metadata."""
    folders = db.query(Folder).order_by(Folder.path).all()
    all_files = db.query(VirtualFile).all()

    file_counts = {}
    for vf in all_files:
        fp = vf.folder_path or "/"
        file_counts[fp] = file_counts.get(fp, 0) + 1

    result = [{"path": "/", "name": "/", "parent_path": None, "file_count": file_counts.get("/", 0)}]
    for f in folders:
        result.append({
            "path": f.path,
            "name": f.name,
            "parent_path": f.parent_path,
            "file_count": file_counts.get(f.path, 0),
        })
    return result


def delete_folder(db: Session, path: str):
    """Delete a folder (only if empty of subfolders). Files keep their folder_path."""
    folder = db.query(Folder).filter(Folder.path == path).first()
    if folder:
        db.delete(folder)
        db.commit()
    return folder


# ──────────────────────────── VirtualFile CRUD ────────────────────────────

def create_virtual_file(db: Session, filename: str, original_size: int,
                         mime_type: str = None, md5_hash: str = None,
                         is_split: bool = False, chunk_size: int = None,
                         num_chunks: int = 1, description: str = None,
                         tags: list = None, folder_path: str = "/") -> VirtualFile:
    vf = VirtualFile(
        filename=filename,
        original_size=original_size,
        mime_type=mime_type,
        md5_hash=md5_hash,
        is_split=is_split,
        chunk_size=chunk_size,
        num_chunks=num_chunks,
        description=description,
        tags=tags,
        folder_path=folder_path,
    )
    db.add(vf)
    db.commit()
    db.refresh(vf)

    # Update search index
    search_text = f"{filename} {' '.join(tags or [])} {description or ''}"
    si = SearchIndex(virtual_file_id=vf.id, search_text=search_text.lower())
    db.add(si)
    db.commit()

    return vf


def get_virtual_file(db: Session, file_id: int) -> Optional[VirtualFile]:
    return db.query(VirtualFile).filter(VirtualFile.id == file_id).first()


def search_files(db: Session, query: str, folder: str = None) -> List[VirtualFile]:
    """Search files by name, tags, or description."""
    q = f"%{query.lower()}%"
    subq = select(SearchIndex.virtual_file_id).where(
        SearchIndex.search_text.ilike(q)
    )

    vf_query = db.query(VirtualFile).filter(VirtualFile.id.in_(subq))
    if folder:
        vf_query = vf_query.filter(VirtualFile.folder_path == folder)
    return vf_query.all()


def get_files_in_folder(db: Session, folder_path: str = "/") -> List[VirtualFile]:
    return db.query(VirtualFile).filter(VirtualFile.folder_path == folder_path).all()


def get_all_files(db: Session) -> List[VirtualFile]:
    return db.query(VirtualFile).all()


def delete_virtual_file(db: Session, file_id: int):
    vf = db.query(VirtualFile).filter(VirtualFile.id == file_id).first()
    if vf:
        # Mark chunks as deleted
        for chunk in vf.chunks:
            chunk.status = ChunkStatus.DELETED
        db.delete(vf)
        db.commit()
    return vf


# ──────────────────────────── FileChunk CRUD ────────────────────────────

def create_file_chunk(db: Session, virtual_file_id: int, account_id: int,
                       chunk_index: int, chunk_size: int,
                       google_drive_file_id: str = None,
                       google_drive_filename: str = None,
                       md5_hash: str = None) -> FileChunk:
    fc = FileChunk(
        virtual_file_id=virtual_file_id,
        account_id=account_id,
        chunk_index=chunk_index,
        chunk_size=chunk_size,
        status=ChunkStatus.UPLOADED,
        google_drive_file_id=google_drive_file_id,
        google_drive_filename=google_drive_filename,
        md5_hash=md5_hash,
    )
    db.add(fc)
    db.commit()
    db.refresh(fc)
    return fc


def get_chunks_for_file(db: Session, virtual_file_id: int) -> List[FileChunk]:
    return db.query(FileChunk).filter(
        FileChunk.virtual_file_id == virtual_file_id,
        FileChunk.status != ChunkStatus.DELETED
    ).order_by(FileChunk.chunk_index).all()


def get_all_chunks(db: Session) -> List[FileChunk]:
    return db.query(FileChunk).filter(FileChunk.status != ChunkStatus.DELETED).all()


def get_chunk_locations_report(db: Session, virtual_file_id: int) -> dict:
    """Report where each chunk of a file is stored."""
    vf = get_virtual_file(db, virtual_file_id)
    if not vf:
        return None
    chunks = get_chunks_for_file(db, virtual_file_id)
    return {
        "file_id": vf.id,
        "filename": vf.filename,
        "original_size": vf.original_size,
        "is_split": vf.is_split,
        "num_chunks": len(chunks),
        "chunks": [
            {
                "chunk_index": c.chunk_index,
                "chunk_size": c.chunk_size,
                "drive_account": c.account.email if c.account else "unknown",
                "google_drive_file_id": c.google_drive_file_id,
                "status": c.status.value,
            }
            for c in chunks
        ]
    }
