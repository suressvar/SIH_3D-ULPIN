from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import Kind, Source


class Contract(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)


class ObjectCreate(Contract):
    kind: Kind
    label: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None
    existing_ulpin: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{14}$")
    floor_number: int | None = None
    semantic_type: str | None = Field(default=None, max_length=40)
    is_synthetic: bool = False

    @model_validator(mode="after")
    def hierarchy(self):
        if (self.kind == Kind.PARCEL) != (self.parent_id is None):
            raise ValueError("Only a parcel has no parent")
        if self.existing_ulpin and self.kind != Kind.PARCEL:
            raise ValueError("Existing ULPIN belongs to the parcel only")
        if self.floor_number is not None and self.kind != Kind.FLOOR:
            raise ValueError("floor_number belongs to a floor")
        return self


class ObjectOut(ObjectCreate):
    id: UUID
    lifecycle: str
    parcel_id: UUID | None
    created_by: UUID
    created_at: datetime


class GeometryCreate(Contract):
    footprint: dict[str, Any]
    source_crs: str = Field(min_length=1, max_length=80)
    metric_srid: int = Field(gt=0)
    z_min: float | None = None
    z_max: float | None = None
    elevation_reference: str | None = Field(default=None, min_length=1, max_length=160)
    height_estimated: bool = False
    source_category: Source
    source_dataset_id: UUID | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    method: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def heights(self):
        if (self.z_min is None) != (self.z_max is None):
            raise ValueError("Provide both vertical bounds or neither")
        if self.z_min is not None:
            if self.z_max is None or self.z_max <= self.z_min:
                raise ValueError("z_max must exceed z_min")
            if not self.elevation_reference:
                raise ValueError("Vertical bounds require an elevation reference")
        elif self.height_estimated or self.elevation_reference:
            raise ValueError("No height metadata without height bounds")
        return self


class GeometryOut(Contract):
    id: UUID
    object_id: UUID
    version: int
    footprint: dict[str, Any]
    horizontal_crs: str
    metric_srid: int
    source_crs: str
    transformation: dict
    z_min: float | None
    z_max: float | None
    elevation_reference: str | None
    height_estimated: bool
    source_category: Source
    source_dataset_id: UUID | None
    confidence: float | None
    method: str
    geometry_hash: str
    validity: str
    created_at: datetime
    created_by: UUID


class DatasetOut(Contract):
    id: UUID
    filename: str
    media_type: str
    source_category: Source
    sha256: str
    byte_size: int
    status: str
    inspection: dict
    error_message: str | None
    is_synthetic: bool
    created_at: datetime
    created_by: UUID


class JobCreate(Contract):
    kind: Literal[
        "INGEST_GEOJSON",
        "VALIDATE_PRISM",
        "SUGGEST_BUILDINGS",
        "SUGGEST_UNITS",
        "ESTIMATE_HEIGHT",
        "SUGGEST_LEVELS",
        "EXPORT_ASSETS",
    ]
    input_dataset_id: UUID | None = None
    geometry_id: UUID | None = None

    @model_validator(mode="after")
    def input_contract(self):
        if self.kind == "INGEST_GEOJSON":
            if not self.input_dataset_id or self.geometry_id:
                raise ValueError("Ingestion requires only input_dataset_id")
        elif self.kind == "VALIDATE_PRISM" and (
            not self.geometry_id or self.input_dataset_id
        ):
            raise ValueError("Validation requires only geometry_id")
        return self


class JobOut(JobCreate):
    parameters: dict
    id: UUID
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    progress: int
    output_assets: list
    result: dict
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    created_by: UUID


class EvidenceCreate(Contract):
    object_id: UUID
    dataset_id: UUID
    description: str = Field(min_length=3, max_length=3000)


class EvidenceOut(EvidenceCreate):
    id: UUID
    created_at: datetime
    created_by: UUID


class RightCreate(Contract):
    object_id: UUID
    evidence_id: UUID
    right_type: Literal[
        "RECORDED_OWNERSHIP", "SHARED_USE", "ACCESS", "EASEMENT", "RESTRICTION"
    ]
    party_reference: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=3, max_length=3000)
    is_synthetic: bool = False


class RightOut(RightCreate):
    id: UUID
    created_at: datetime
    created_by: UUID


class ReviewCreate(Contract):
    geometry_id: UUID
    validation_job_id: UUID


class DecisionCreate(Contract):
    decision: Literal["ACCEPTED_PROTOTYPE", "RETURNED"]
    reason: str = Field(min_length=5, max_length=3000)


class ReviewOut(Contract):
    id: UUID
    object_id: UUID
    geometry_id: UUID
    validation_job_id: UUID
    status: str
    submitted_by: UUID
    created_at: datetime


class DecisionOut(DecisionCreate):
    id: UUID
    review_id: UUID
    reviewer_id: UUID
    created_at: datetime


class IdentityOut(Contract):
    id: UUID
    object_id: UUID
    issued_geometry_id: UUID
    identifier: str
    label: Literal["Proposed 3D ULPIN"]
    scheme_version: str
    created_at: datetime


class IssueOut(Contract):
    id: UUID
    job_id: UUID
    geometry_id: UUID
    related_geometry_id: UUID | None
    status: str
    code: str
    severity: str
    message: str
    details: dict
    created_at: datetime


class AuditOut(Contract):
    id: UUID
    actor_id: UUID
    action: str
    entity_type: str
    entity_id: UUID
    detail: dict
    created_at: datetime
