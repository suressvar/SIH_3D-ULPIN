"""Immutable phase-one baseline. SQL is frozen, not imported from live models."""

from pathlib import Path

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    source = Path(__file__).with_name("0001_schema.sql").read_text(encoding="utf-8")
    # Marker-delimited statements also handle PL/pgSQL bodies containing semicolons.
    for statement in source.split("-- ASTRA STATEMENT"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError(
        "Destructive baseline downgrade is disabled. Restore a reviewed backup instead."
    )
