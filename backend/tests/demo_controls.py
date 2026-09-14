"""Synthetic data controls for the explicitly isolated local demo host only."""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text

from app.auth import current_user, roles
from app.config import get_settings
from app.db import get_session
from app.models import AppUser, Base, ProcessingJob, SourceDataset, SpatialObject
from app.pipeline_models import AssetBundle
from app.repositories import audit
from app.storage import local_path

router = APIRouter(prefix="/demo", tags=["local demo"])
lock = threading.Lock()
state_path = Path("data/ui-test/dataset-operation.json")
running = False


def guard():
    if (
        os.getenv("ASTRA_UI_TEST") != "1"
        or get_settings().environment != "test"
        or not get_settings().database_url.endswith("/astra_ui_test")
        or get_settings().storage_backend != "local"
    ):
        raise HTTPException(404, "Local demo controls unavailable")


def save(value):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(state_path)


@router.get("")
def status(user: AppUser = Depends(current_user)):
    guard()
    with get_session() as db:
        count = len(
            list(
                db.scalars(
                    select(SpatialObject.id).where(SpatialObject.is_synthetic.is_(True))
                )
            )
        )
    operation = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"status": "IDLE"}
    )
    if operation.get("status") == "RUNNING" and not running:
        operation = {
            "status": "FAILED",
            "error": "Operation interrupted. Inspect data before retrying.",
        }
    return {"available": True, "synthetic_objects": count, "operation": operation}


@router.post("/seed", status_code=202)
def seed(user: AppUser = Depends(roles("surveyor", "officer", "admin"))):
    guard()
    global running
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "A demo operation is already running")
    running = True
    save(
        {
            "status": "RUNNING",
            "action": "SEED",
            "started_at": datetime.now(UTC).isoformat(),
        }
    )

    def work():
        global running
        try:
            from app.judge_demo import seed_judge

            result = seed_judge()
            save({"status": "COMPLETED", "action": "SEED", "result": result})
        except Exception as error:
            save({"status": "FAILED", "action": "SEED", "error": str(error)[:500]})
        finally:
            running = False
            lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"status": "RUNNING"}


@router.delete("")
def clear(user: AppUser = Depends(roles("surveyor", "officer", "admin"))):
    guard()
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the demo operation to finish")
    try:
        with get_session() as db, db.begin():
            # Fixed ORM table inventory, never a client-supplied SQL identifier.
            tables = [
                t
                for t in Base.metadata.tables.values()
                if t.schema == "cadastre"
                and t.name not in {"app_users", "audit_events"}
            ]
            names = ", ".join('cadastre."' + t.name + '"' for t in tables)
            db.execute(text("LOCK TABLE " + names + " IN ACCESS EXCLUSIVE MODE"))
            for model in (SpatialObject, SourceDataset):
                if db.scalar(
                    select(model.id).where(model.is_synthetic.is_(False)).limit(1)
                ):
                    raise HTTPException(
                        409, "Real records exist. Bulk demo deletion is disabled."
                    )
            if db.scalar(
                select(ProcessingJob.id)
                .where(ProcessingJob.status.in_(["RUNNING", "QUEUED"]))
                .limit(1)
            ):
                raise HTTPException(409, "Wait for processing jobs to finish")
            keys = set(db.scalars(select(SourceDataset.object_key)))
            for bundle in db.scalars(select(AssetBundle)):
                for value in bundle.manifest.get("files", {}).values():
                    if isinstance(value, dict) and value.get("key"):
                        keys.add(value["key"])
            paths = [local_path(key) for key in keys]
            count = len(list(db.scalars(select(SpatialObject.id))))
            # Intentional local fixture reset; no CASCADE and no trigger changes.
            db.execute(text("TRUNCATE TABLE " + names))
            audit(
                db,
                user.id,
                "SYNTHETIC_DATA_DELETED",
                user,
                {"objects": count, "files": len(paths)},
            )
        failures = []
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failures.append(str(path))
        result = {
            "status": "COMPLETED" if not failures else "FAILED",
            "action": "DELETE",
            "deleted_objects": count,
            "remaining_files": failures,
        }
        save(result)
        return result
    finally:
        lock.release()
