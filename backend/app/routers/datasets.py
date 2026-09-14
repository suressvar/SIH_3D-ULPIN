from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, roles
from app.config import get_settings
from app.db import get_db
from app.models import AppUser, Source, SourceDataset
from app.repositories import require
from app.schemas import DatasetOut
from app.services.ingestion import register_dataset
from app.storage import download_stream

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("", response_model=DatasetOut, status_code=201)
async def upload(
    file: UploadFile = File(),
    source_category: Source = Form(),
    intent: Literal["parcel", "evidence"] = Form(),
    metric_srid: int | None = Form(None),
    source_crs: str | None = Form(None),
    is_synthetic: bool = Form(False),
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("surveyor", "admin")),
):
    data = await file.read(get_settings().max_upload_bytes + 1)
    await file.close()
    if not data or len(data) > get_settings().max_upload_bytes:
        raise HTTPException(413, "Empty upload or file exceeds configured size limit")
    # File names are display metadata only; never used as a storage path.
    return register_dataset(
        db,
        data,
        (file.filename or "upload").replace("\\", "/").split("/")[-1],
        source_category,
        user.id,
        is_synthetic,
        intent,
        source_crs,
        metric_srid,
    )


@router.get("", response_model=list[DatasetOut])
def listing(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return list(
        db.scalars(
            select(SourceDataset)
            .order_by(SourceDataset.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/{dataset_id}", response_model=DatasetOut)
def detail(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return require(db, SourceDataset, dataset_id)


@router.get("/{dataset_id}/original")
def original(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    dataset = require(db, SourceDataset, dataset_id)
    return StreamingResponse(
        download_stream(dataset.object_key),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{dataset.id}.bin"',
            "X-Content-Type-Options": "nosniff",
        },
    )
