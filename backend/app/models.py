from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "cadastre"


class Kind(StrEnum):
    PARCEL = "PARCEL"
    BUILDING = "BUILDING"
    FLOOR = "FLOOR"
    UNIT = "UNIT"
    UNDERGROUND = "UNDERGROUND"
    SHARED = "SHARED"
    EASEMENT = "EASEMENT"
    INFRASTRUCTURE = "INFRASTRUCTURE"


class Source(StrEnum):
    SURVEY = "SURVEY"
    APPROVED_PLAN = "APPROVED_PLAN"
    LIDAR = "LIDAR"
    DRONE_IMAGERY = "DRONE_IMAGERY"
    DEM_DSM = "DEM_DSM"
    AI_ESTIMATE = "AI_ESTIMATE"
    MANUAL = "MANUAL"
    DERIVED = "DERIVED"


def values(enum):
    return ",".join(f"'{v.value}'" for v in enum)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AppUser(Record, Base):
    __tablename__ = "app_users"
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint(
            "role IN ('viewer','surveyor','officer','admin')", name="user_role"
        ),
    )


class SpatialObject(Record, Base):
    __tablename__ = "spatial_objects"
    kind: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(160))
    semantic_type: Mapped[str | None] = mapped_column(String(40))
    lifecycle: Mapped[str] = mapped_column(
        String(20), default="ACTIVE", server_default="ACTIVE"
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    parcel_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    existing_ulpin: Mapped[str | None] = mapped_column(String(14), unique=True)
    floor_number: Mapped[int | None] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(f"kind IN ({values(Kind)})", name="object_kind"),
        CheckConstraint(
            "(kind = 'PARCEL' AND parent_id IS NULL AND parcel_id IS NULL) OR (kind <> 'PARCEL' AND parent_id IS NOT NULL AND parcel_id IS NOT NULL)",
            name="object_root",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="no_self_parent"),
        CheckConstraint(
            "existing_ulpin IS NULL OR (kind = 'PARCEL' AND existing_ulpin ~ '^[A-Za-z0-9]{14}$')",
            name="parent_ulpin_format",
        ),
        CheckConstraint(
            "floor_number IS NULL OR kind = 'FLOOR'", name="floor_number_kind"
        ),
    )


class SpatialRelationship(Record, Base):
    __tablename__ = "spatial_relationships"
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    relation: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        CheckConstraint(
            "relation IN ('AFFECTS','SERVES','SHARED_BY','PREDECESSOR')",
            name="relationship_type",
        ),
        CheckConstraint("source_id <> target_id", name="relationship_distinct"),
        UniqueConstraint("source_id", "target_id", "relation"),
    )


class SourceDataset(Record, Base):
    __tablename__ = "source_datasets"
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    source_category: Mapped[str] = mapped_column(String(30))
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="UPLOADED")
    inspection: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            f"source_category IN ({values(Source)})", name="dataset_source"
        ),
        CheckConstraint(
            "status IN ('UPLOADED','READY','REJECTED','EVIDENCE_ONLY')",
            name="dataset_status",
        ),
        CheckConstraint("byte_size > 0", name="dataset_size"),
    )


class GeometryVersion(Record, Base):
    __tablename__ = "geometry_versions"
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    footprint = mapped_column(
        Geometry("POLYGON", srid=4326, spatial_index=True), nullable=False
    )
    metric_footprint = mapped_column(
        Geometry("POLYGON", srid=-1, spatial_index=True), nullable=False
    )
    shell = mapped_column(
        Geometry("POLYHEDRALSURFACEZ", srid=-1, dimension=3, spatial_index=True),
        nullable=True,
    )
    horizontal_crs: Mapped[str] = mapped_column(String(80), default="EPSG:4326")
    metric_srid: Mapped[int] = mapped_column(Integer)
    source_crs: Mapped[str] = mapped_column(String(80))
    transformation: Mapped[dict] = mapped_column(JSONB)
    z_min: Mapped[float | None] = mapped_column(Float)
    z_max: Mapped[float | None] = mapped_column(Float)
    elevation_reference: Mapped[str | None] = mapped_column(String(160))
    height_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    source_category: Mapped[str] = mapped_column(String(30))
    source_dataset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.source_datasets.id"), index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(Text)
    geometry_hash: Mapped[str] = mapped_column(String(64))
    validity: Mapped[str] = mapped_column(String(40), default="FOOTPRINT_VALID")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        UniqueConstraint("object_id", "version"),
        UniqueConstraint("id", "object_id"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "(z_min IS NULL OR z_min NOT IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8)) AND (z_max IS NULL OR z_max NOT IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8))",
            name="finite_vertical_bounds",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="geometry_confidence",
        ),
        CheckConstraint(
            f"source_category IN ({values(Source)})", name="geometry_source"
        ),
        CheckConstraint(
            "ST_IsValid(footprint) AND NOT ST_IsEmpty(footprint)",
            name="footprint_valid",
        ),
        CheckConstraint(
            "ST_IsValid(metric_footprint) AND ST_SRID(metric_footprint) = metric_srid",
            name="metric_footprint_valid",
        ),
        CheckConstraint(
            "(z_min IS NULL AND z_max IS NULL AND shell IS NULL) OR (z_min IS NOT NULL AND z_max IS NOT NULL AND z_max > z_min AND elevation_reference IS NOT NULL AND shell IS NOT NULL AND ST_SRID(shell) = metric_srid)",
            name="vertical_extent",
        ),
    )


class Evidence(Record, Base):
    __tablename__ = "evidence"
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.source_datasets.id"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )


class PropertyRight(Record, Base):
    __tablename__ = "property_rights"
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.evidence.id"), index=True
    )
    right_type: Mapped[str] = mapped_column(String(30))
    party_reference: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            "right_type IN ('RECORDED_OWNERSHIP','SHARED_USE','ACCESS','EASEMENT','RESTRICTION')",
            name="right_type",
        ),
    )


class ProcessingJob(Record, Base):
    __tablename__ = "processing_jobs"
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    input_dataset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.source_datasets.id"), index=True
    )
    geometry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), index=True
    )
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    output_assets: Mapped[list] = mapped_column(JSONB, default=list)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            "kind IN ('INGEST_GEOJSON','VALIDATE_PRISM','SUGGEST_BUILDINGS','SUGGEST_UNITS','ESTIMATE_HEIGHT','SUGGEST_LEVELS','EXPORT_ASSETS')",
            name="job_kind",
        ),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="job_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="job_progress"),
        CheckConstraint(
            "status <> 'COMPLETED' OR (progress = 100 AND completed_at IS NOT NULL)",
            name="job_completion",
        ),
        CheckConstraint(
            "(kind = 'INGEST_GEOJSON' AND input_dataset_id IS NOT NULL AND geometry_id IS NULL) OR (kind = 'VALIDATE_PRISM' AND geometry_id IS NOT NULL AND input_dataset_id IS NULL) OR (kind IN ('SUGGEST_BUILDINGS','SUGGEST_UNITS','ESTIMATE_HEIGHT','SUGGEST_LEVELS') AND input_dataset_id IS NOT NULL AND geometry_id IS NULL) OR (kind='EXPORT_ASSETS' AND input_dataset_id IS NULL AND geometry_id IS NULL)",
            name="job_input",
        ),
    )


class ValidationIssue(Record, Base):
    __tablename__ = "validation_issues"
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.processing_jobs.id"), index=True
    )
    geometry_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), index=True
    )
    related_geometry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), index=True
    )
    affected_geometry = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="OPEN", server_default="OPEN"
    )
    code: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        CheckConstraint(
            "severity IN ('ERROR','WARNING','INFO','CRITICAL')", name="issue_severity"
        ),
    )


class ULPINIdentity(Record, Base):
    __tablename__ = "ulpin_identities"
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), unique=True
    )
    issued_geometry_id: Mapped[UUID] = mapped_column(index=True)
    identifier: Mapped[str] = mapped_column(String(100), unique=True)
    label: Mapped[str] = mapped_column(String(40), default="Proposed 3D ULPIN")
    scheme_version: Mapped[str] = mapped_column(String(30), default="ASTRA-PROTOTYPE-1")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["issued_geometry_id", "object_id"],
            [f"{SCHEMA}.geometry_versions.id", f"{SCHEMA}.geometry_versions.object_id"],
        ),
        CheckConstraint("label = 'Proposed 3D ULPIN'", name="identity_label"),
    )


class ReviewCase(Record, Base):
    __tablename__ = "review_cases"
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    geometry_id: Mapped[UUID] = mapped_column(index=True)
    validation_job_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.processing_jobs.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="SUBMITTED")
    submitted_by: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["geometry_id", "object_id"],
            [f"{SCHEMA}.geometry_versions.id", f"{SCHEMA}.geometry_versions.object_id"],
        ),
        UniqueConstraint("geometry_id", "validation_job_id"),
        CheckConstraint(
            "status IN ('SUBMITTED','ACCEPTED_PROTOTYPE','RETURNED')",
            name="review_status",
        ),
    )


class ReviewDecision(Record, Base):
    __tablename__ = "review_decisions"
    review_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.review_cases.id"), unique=True
    )
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            "decision IN ('ACCEPTED_PROTOTYPE','RETURNED')", name="decision_type"
        ),
    )


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[UUID] = mapped_column(index=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
