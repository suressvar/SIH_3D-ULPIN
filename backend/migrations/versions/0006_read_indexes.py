"""Indexes for audited case/history read paths; no data changes."""

from alembic import op

revision = "0006_read_indexes"
down_revision = "0005_governance"
branch_labels = None
depends_on = None


def upgrade():
    for sql in [
        "CREATE INDEX ix_workflow_object_sequence ON cadastre.workflow_events (object_id, sequence DESC)",
        "CREATE INDEX ix_annotation_object_sequence ON cadastre.property_annotations (object_id, sequence DESC)",
        "CREATE INDEX ix_audit_entity_time ON cadastre.audit_events (entity_id, created_at DESC, id DESC)",
        "CREATE INDEX ix_job_geometry_kind_time ON cadastre.processing_jobs (geometry_id, kind, created_at DESC)",
        "CREATE INDEX ix_review_object_time ON cadastre.review_cases (object_id, created_at DESC)",
    ]:
        op.execute(sql)


def downgrade():
    for name in [
        "ix_workflow_object_sequence",
        "ix_annotation_object_sequence",
        "ix_audit_entity_time",
        "ix_job_geometry_kind_time",
        "ix_review_object_time",
    ]:
        op.drop_index(name, schema="cadastre")
