"""Append-only governance records, separate from authoritative spatial geometry."""

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import SCHEMA, AuditEvent, Base, ProcessingJob, Record, ReviewCase


class WorkflowEvent(Record, Base):
    __tablename__ = "workflow_events"
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    geometry_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.geometry_versions.id"), index=True
    )
    before_state: Mapped[str] = mapped_column(String(30))
    after_state: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    validation_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.processing_jobs.id")
    )
    review_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.review_decisions.id")
    )
    __table_args__ = (
        CheckConstraint(
            "after_state IN ('DRAFT','VALIDATION','VALIDATED','REVIEW','ACCEPTED','CORRECTION_REQUIRED')",
            name="workflow_state",
        ),
    )


class RightScope(Record, Base):
    __tablename__ = "right_scopes"
    right_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.property_rights.id"), index=True
    )
    related_object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )
    __table_args__ = (UniqueConstraint("right_id", "related_object_id"),)


class PropertyAnnotation(Record, Base):
    __tablename__ = "property_annotations"
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.spatial_objects.id"), index=True
    )
    display_label: Mapped[str] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(500))
    land_use: Mapped[str | None] = mapped_column(String(100))
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.evidence.id"))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id"), index=True
    )


# Hot read paths used by the case/history APIs. Spatial GiST indexes already exist.


Index(
    "ix_workflow_object_sequence",
    WorkflowEvent.object_id,
    WorkflowEvent.sequence.desc(),
)
Index(
    "ix_annotation_object_sequence",
    PropertyAnnotation.object_id,
    PropertyAnnotation.sequence.desc(),
)
Index(
    "ix_audit_entity_time",
    AuditEvent.entity_id,
    AuditEvent.created_at.desc(),
    AuditEvent.id.desc(),
)
Index(
    "ix_job_geometry_kind_time",
    ProcessingJob.geometry_id,
    ProcessingJob.kind,
    ProcessingJob.created_at.desc(),
)
Index("ix_review_object_time", ReviewCase.object_id, ReviewCase.created_at.desc())
