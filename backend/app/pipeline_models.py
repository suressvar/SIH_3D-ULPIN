"""Additive phase-two records; the existing spatial hierarchy remains authoritative."""

from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import SCHEMA, Base, Record


class SpatialSuggestion(Record, Base):
    __tablename__ = "spatial_suggestions"
    parent_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.source_datasets.id"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.processing_jobs.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(160))
    footprint = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    source_category: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    __table_args__ = (
        CheckConstraint("kind IN ('BUILDING','UNIT','SHARED')", name="suggestion_kind"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="suggestion_confidence",
        ),
        CheckConstraint(
            "ST_IsValid(footprint) AND NOT ST_IsEmpty(footprint)",
            name="suggestion_valid",
        ),
    )


class SuggestionDecision(Record, Base):
    __tablename__ = "suggestion_decisions"
    suggestion_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_suggestions.id"), unique=True
    )
    geometry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), index=True
    )
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            "decision IN ('ADOPTED_AS_DRAFT','REJECTED')", name="suggestion_decision"
        ),
    )


class HeightObservation(Record, Base):
    __tablename__ = "height_observations"
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.source_datasets.id"), index=True
    )
    secondary_dataset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.source_datasets.id"), index=True
    )
    height_value: Mapped[float] = mapped_column(Float)
    base_elevation: Mapped[float] = mapped_column(Float)
    height_source: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float | None] = mapped_column(Float)
    vertical_reference: Mapped[str] = mapped_column(String(160))
    estimated: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict] = mapped_column(JSONB)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            "height_value > 0 AND height_value < 'Infinity'::float8",
            name="positive_height",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="height_confidence"
        ),
    )


class IdentityVersion(Record, Base):
    __tablename__ = "identity_versions"
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.ulpin_identities.id"), index=True
    )
    geometry_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), unique=True
    )
    canonical_code: Mapped[str] = mapped_column(String(100), index=True)
    geometry_hash: Mapped[str] = mapped_column(String(64))
    identity_inputs: Mapped[dict] = mapped_column(JSONB)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )


class GeometryChange(Record, Base):
    __tablename__ = "geometry_changes"
    operation: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.evidence.id"), index=True
    )
    review_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.review_decisions.id"), index=True
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            "operation IN ('REPLACE','SPLIT','MERGE')", name="change_operation"
        ),
    )


class ChangeMember(Record, Base):
    __tablename__ = "change_members"
    change_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_changes.id"), index=True
    )
    geometry_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), index=True
    )
    direction: Mapped[str] = mapped_column(String(10))
    __table_args__ = (
        CheckConstraint("direction IN ('BEFORE','AFTER')", name="change_direction"),
        UniqueConstraint("change_id", "geometry_id", "direction"),
    )


class AssetBundle(Record, Base):
    __tablename__ = "asset_bundles"
    parcel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.processing_jobs.id"), index=True
    )
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    placement: Mapped[dict] = mapped_column(JSONB)
    manifest: Mapped[dict] = mapped_column(JSONB)
    validation: Mapped[dict] = mapped_column(JSONB)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )


class GeometryAttestation(Record, Base):
    __tablename__ = "geometry_attestations"
    geometry_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), index=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.evidence.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('SURVEY_VERIFIED','PLAN_VERIFIED')", name="attestation_status"
        ),
    )
