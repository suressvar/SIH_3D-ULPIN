"""Add assistive processing, property changes and asset bundles without replacing phase one."""

from pathlib import Path

from alembic import op

revision = "0003_pipeline"
down_revision = "0002_provenance_guards"
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
        "Pipeline history must not be deleted; use a reviewed forward migration."
    )
