"""Append-only governance history and explicitly scoped rights."""

from pathlib import Path

from alembic import op

revision = "0005_governance"
down_revision = "0004_identity_reuse"
branch_labels = None
depends_on = None


def upgrade():
    for statement in (
        Path(__file__)
        .with_suffix(".sql")
        .read_text(encoding="utf-8")
        .split("-- ASTRA STATEMENT")
    ):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError(
        "Governance history is retained; use a reviewed forward migration."
    )
