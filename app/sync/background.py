"""
Background sync service:
- Periodically syncs Drive storage quota (every hour by default)
- Cleans up stale/failed chunks
- Logs sync history for the dashboard
"""
import asyncio
import logging
import time
import datetime
from typing import Optional

from app.database import manager as db
from app.database.models import Account, DriveStorage, ChunkStatus
from app.drive.gdrive import get_drive_service, get_drive_quota

logger = logging.getLogger(__name__)

# ──────────────────────── Sync State ────────────────────────

_sync_state = {
    "last_sync_at": None,
    "last_sync_duration_seconds": None,
    "last_sync_result": None,       # "ok" | "error" | "no_accounts"
    "total_syncs": 0,
    "consecutive_errors": 0,
    "is_running": False,
    "next_sync_at": None,
}

SYNC_INTERVAL_SECONDS = 3600  # 1 hour
MAX_RETRY_INTERVAL = 86400    # cap backoff at 24 hours


def get_sync_status() -> dict:
    """Return current sync status for the API."""
    return {
        "last_sync_at": _sync_state["last_sync_at"].isoformat() if _sync_state["last_sync_at"] else None,
        "next_sync_at": _sync_state["next_sync_at"].isoformat() if _sync_state["next_sync_at"] else None,
        "last_sync_duration_seconds": _sync_state["last_sync_duration_seconds"],
        "last_sync_result": _sync_state["last_sync_result"],
        "total_syncs": _sync_state["total_syncs"],
        "consecutive_errors": _sync_state["consecutive_errors"],
        "is_running": _sync_state["is_running"],
        "interval_seconds": SYNC_INTERVAL_SECONDS,
    }


# ──────────────────────── Core Sync Logic ────────────────────────

def run_sync_once() -> dict:
    """
    Perform a single sync of all authorized drives.
    Returns a summary dict.
    """
    start = time.time()
    _sync_state["is_running"] = True

    session = db.SessionLocal()
    results = []

    try:
        accounts = db.get_all_accounts(session)
        authorized = [a for a in accounts if a.is_authorized]

        if not authorized:
            _sync_state["last_sync_result"] = "no_accounts"
            _sync_state["last_sync_duration_seconds"] = round(time.time() - start, 2)
            _sync_state["is_running"] = False
            _sync_state["total_syncs"] += 1
            logger.info("Background sync: no authorized accounts, skipping")
            return {"status": "no_accounts", "results": []}

        for account in authorized:
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
                    session, account.id,
                    quota["total_bytes"],
                    quota["used_bytes"],
                    quota["available_bytes"],
                )
                results.append({
                    "email": account.email,
                    "total": quota["total_bytes"],
                    "used": quota["used_bytes"],
                    "available": quota["available_bytes"],
                    "status": "ok",
                })
                logger.info(
                    f"Background sync: {account.email} -> "
                    f"total={quota['total_bytes']}, used={quota['used_bytes']}, "
                    f"free={quota['available_bytes']}"
                )
            except Exception as e:
                results.append({
                    "email": account.email,
                    "status": "error",
                    "message": str(e),
                })
                logger.warning(f"Background sync failed for {account.email}: {e}")

        # Check for stale chunks (pending > 24h)
        stale_cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        stale = session.query(db.FileChunk if hasattr(db, 'FileChunk') else None)
        from app.database.models import FileChunk
        stale_chunks = session.query(FileChunk).filter(
            FileChunk.status == ChunkStatus.PENDING,
            FileChunk.created_at < stale_cutoff,
        ).all()

        if stale_chunks:
            for chunk in stale_chunks:
                chunk.status = ChunkStatus.FAILED
            session.commit()
            logger.info(f"Background sync: marked {len(stale_chunks)} stale chunks as FAILED")

        # Update state
        duration = round(time.time() - start, 2)
        has_errors = any(r["status"] == "error" for r in results)

        _sync_state["last_sync_at"] = datetime.datetime.utcnow()
        _sync_state["last_sync_duration_seconds"] = duration
        _sync_state["last_sync_result"] = "error" if has_errors else "ok"
        _sync_state["total_syncs"] += 1
        _sync_state["is_running"] = False

        if has_errors:
            _sync_state["consecutive_errors"] += 1
        else:
            _sync_state["consecutive_errors"] = 0

        logger.info(
            f"Background sync complete: {len(authorized)} drives, "
            f"{sum(1 for r in results if r['status']=='ok')}/{len(results)} ok, "
            f"took {duration}s"
        )

        return {"status": _sync_state["last_sync_result"], "results": results}

    except Exception as e:
        duration = round(time.time() - start, 2)
        _sync_state["last_sync_at"] = datetime.datetime.utcnow()
        _sync_state["last_sync_duration_seconds"] = duration
        _sync_state["last_sync_result"] = "error"
        _sync_state["consecutive_errors"] += 1
        _sync_state["total_syncs"] += 1
        _sync_state["is_running"] = False
        logger.error(f"Background sync fatal error: {e}")
        return {"status": "error", "message": str(e), "results": []}
    finally:
        session.close()


# ──────────────────────── Background Loop ────────────────────────

async def _sync_loop(interval: int = SYNC_INTERVAL_SECONDS):
    """
    Async loop that runs sync at the given interval.
    Uses exponential backoff on consecutive errors (1h, 2h, 4h, ... up to 24h).
    """
    logger.info(f"Background sync loop started (interval={interval}s)")
    current_interval = interval

    while True:
        _sync_state["next_sync_at"] = datetime.datetime.utcnow() + datetime.timedelta(seconds=current_interval)
        await asyncio.sleep(current_interval)

        logger.info("Background sync: starting scheduled sync...")
        result = run_sync_once()

        # Backoff on errors
        if result.get("status") == "error":
            backoff = min(
                interval * (2 ** _sync_state["consecutive_errors"]),
                MAX_RETRY_INTERVAL,
            )
            current_interval = backoff
            logger.warning(
                f"Background sync: backing off to {current_interval}s "
                f"({_sync_state['consecutive_errors']} consecutive errors)"
            )
        else:
            current_interval = interval


_sync_task: Optional[asyncio.Task] = None


async def start_background_sync(interval: int = SYNC_INTERVAL_SECONDS):
    """Start the background sync task. Called from FastAPI lifespan."""
    global _sync_task
    if _sync_task is not None:
        logger.warning("Background sync already running")
        return
    _sync_task = asyncio.create_task(_sync_loop(interval))
    logger.info("Background sync task created")


async def stop_background_sync():
    """Stop the background sync task. Called from FastAPI lifespan."""
    global _sync_task
    if _sync_task is not None:
        _sync_task.cancel()
        try:
            await _sync_task
        except asyncio.CancelledError:
            pass
        _sync_task = None
        logger.info("Background sync task stopped")
