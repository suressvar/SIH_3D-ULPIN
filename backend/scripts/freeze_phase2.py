"""One-time authoring of the additive migration snapshot."""

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.pipeline_models  # noqa: F401
from app.models import Base

new_tables = {
    "spatial_suggestions",
    "suggestion_decisions",
    "height_observations",
    "identity_versions",
    "geometry_changes",
    "change_members",
    "asset_bundles",
    "geometry_attestations",
}
statements = [
    "ALTER TABLE cadastre.spatial_objects ADD COLUMN semantic_type varchar(40), ADD COLUMN lifecycle varchar(20) NOT NULL DEFAULT 'ACTIVE', ADD CONSTRAINT object_lifecycle CHECK (lifecycle IN ('ACTIVE','SUPERSEDED'));",
    "ALTER TABLE cadastre.processing_jobs ADD COLUMN parameters jsonb NOT NULL DEFAULT '{}';",
    "ALTER TABLE cadastre.processing_jobs DROP CONSTRAINT job_kind, DROP CONSTRAINT job_input;",
    "ALTER TABLE cadastre.processing_jobs ADD CONSTRAINT job_kind CHECK (kind IN ('INGEST_GEOJSON','VALIDATE_PRISM','SUGGEST_BUILDINGS','SUGGEST_UNITS','ESTIMATE_HEIGHT','SUGGEST_LEVELS','EXPORT_ASSETS'));",
    "ALTER TABLE cadastre.processing_jobs ADD CONSTRAINT job_input CHECK ((kind='INGEST_GEOJSON' AND input_dataset_id IS NOT NULL AND geometry_id IS NULL) OR (kind='VALIDATE_PRISM' AND geometry_id IS NOT NULL AND input_dataset_id IS NULL) OR (kind IN ('SUGGEST_BUILDINGS','SUGGEST_UNITS','ESTIMATE_HEIGHT','SUGGEST_LEVELS') AND input_dataset_id IS NOT NULL AND geometry_id IS NULL) OR (kind='EXPORT_ASSETS' AND input_dataset_id IS NULL AND geometry_id IS NULL));",
    "ALTER TABLE cadastre.validation_issues ADD COLUMN affected_geometry geometry(GEOMETRY,4326), ADD COLUMN status varchar(20) NOT NULL DEFAULT 'OPEN', DROP CONSTRAINT issue_severity;",
    "ALTER TABLE cadastre.validation_issues ADD CONSTRAINT issue_severity CHECK (severity IN ('INFO','WARNING','ERROR','CRITICAL')), ADD CONSTRAINT issue_status CHECK (status IN ('OPEN','ACKNOWLEDGED'));",
    "CREATE INDEX validation_affected_gist ON cadastre.validation_issues USING gist(affected_geometry);",
]
for table in Base.metadata.sorted_tables:
    if table.name in new_tables:
        statements.append(
            str(CreateTable(table).compile(dialect=postgresql.dialect())) + ";"
        )
        statements.extend(
            str(CreateIndex(i).compile(dialect=postgresql.dialect())) + ";"
            for i in sorted(table.indexes, key=lambda x: x.name)
        )
for name in sorted(new_tables):
    statements.extend(
        [
            f"ALTER TABLE cadastre.{name} ENABLE ROW LEVEL SECURITY;",
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE ON cadastre.{name} FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();",
        ]
    )
statements.append("""
DO $$ DECLARE t text; BEGIN
IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='astra_app') THEN
  FOREACH t IN ARRAY ARRAY['spatial_suggestions','suggestion_decisions','height_observations','identity_versions','geometry_changes','change_members','asset_bundles','geometry_attestations'] LOOP
    EXECUTE format('CREATE POLICY backend_access ON cadastre.%I TO astra_app USING (true) WITH CHECK (true)',t);
    EXECUTE format('GRANT SELECT,INSERT ON cadastre.%I TO astra_app',t);
  END LOOP;
  GRANT UPDATE(lifecycle,semantic_type) ON cadastre.spatial_objects TO astra_app;
  GRANT UPDATE(status) ON cadastre.validation_issues TO astra_app;
END IF;
END $$;
""")
Path(__file__).parents[1].joinpath("migrations/versions/0003_pipeline.sql").write_text(
    "\n-- ASTRA STATEMENT\n".join(statements), encoding="utf-8"
)
