ALTER TABLE cadastre.spatial_objects ADD COLUMN semantic_type varchar(40), ADD COLUMN lifecycle varchar(20) NOT NULL DEFAULT 'ACTIVE', ADD CONSTRAINT object_lifecycle CHECK (lifecycle IN ('ACTIVE','SUPERSEDED'));
-- ASTRA STATEMENT
ALTER TABLE cadastre.processing_jobs ADD COLUMN parameters jsonb NOT NULL DEFAULT '{}';
-- ASTRA STATEMENT
ALTER TABLE cadastre.processing_jobs DROP CONSTRAINT job_kind, DROP CONSTRAINT job_input;
-- ASTRA STATEMENT
ALTER TABLE cadastre.processing_jobs ADD CONSTRAINT job_kind CHECK (kind IN ('INGEST_GEOJSON','VALIDATE_PRISM','SUGGEST_BUILDINGS','SUGGEST_UNITS','ESTIMATE_HEIGHT','SUGGEST_LEVELS','EXPORT_ASSETS'));
-- ASTRA STATEMENT
ALTER TABLE cadastre.processing_jobs ADD CONSTRAINT job_input CHECK ((kind='INGEST_GEOJSON' AND input_dataset_id IS NOT NULL AND geometry_id IS NULL) OR (kind='VALIDATE_PRISM' AND geometry_id IS NOT NULL AND input_dataset_id IS NULL) OR (kind IN ('SUGGEST_BUILDINGS','SUGGEST_UNITS','ESTIMATE_HEIGHT','SUGGEST_LEVELS') AND input_dataset_id IS NOT NULL AND geometry_id IS NULL) OR (kind='EXPORT_ASSETS' AND input_dataset_id IS NULL AND geometry_id IS NULL));
-- ASTRA STATEMENT
ALTER TABLE cadastre.validation_issues ADD COLUMN affected_geometry geometry(GEOMETRY,4326), ADD COLUMN status varchar(20) NOT NULL DEFAULT 'OPEN', DROP CONSTRAINT issue_severity;
-- ASTRA STATEMENT
ALTER TABLE cadastre.validation_issues ADD CONSTRAINT issue_severity CHECK (severity IN ('INFO','WARNING','ERROR','CRITICAL')), ADD CONSTRAINT issue_status CHECK (status IN ('OPEN','ACKNOWLEDGED'));
-- ASTRA STATEMENT
CREATE INDEX validation_affected_gist ON cadastre.validation_issues USING gist(affected_geometry);
-- ASTRA STATEMENT

CREATE TABLE cadastre.height_observations (
	object_id UUID NOT NULL, 
	dataset_id UUID NOT NULL, 
	secondary_dataset_id UUID, 
	height_value FLOAT NOT NULL, 
	base_elevation FLOAT NOT NULL, 
	height_source VARCHAR(30) NOT NULL, 
	confidence FLOAT, 
	vertical_reference VARCHAR(160) NOT NULL, 
	estimated BOOLEAN NOT NULL, 
	details JSONB NOT NULL, 
	actor_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT positive_height CHECK (height_value > 0 AND height_value < 'Infinity'::float8), 
	CONSTRAINT height_confidence CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1), 
	FOREIGN KEY(object_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(dataset_id) REFERENCES cadastre.source_datasets (id), 
	FOREIGN KEY(secondary_dataset_id) REFERENCES cadastre.source_datasets (id), 
	FOREIGN KEY(actor_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_height_observations_actor_id ON cadastre.height_observations (actor_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_height_observations_dataset_id ON cadastre.height_observations (dataset_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_height_observations_object_id ON cadastre.height_observations (object_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_height_observations_secondary_dataset_id ON cadastre.height_observations (secondary_dataset_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.geometry_attestations (
	geometry_id UUID NOT NULL, 
	evidence_id UUID NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT attestation_status CHECK (status IN ('SURVEY_VERIFIED','PLAN_VERIFIED')), 
	FOREIGN KEY(geometry_id) REFERENCES cadastre.geometry_versions (id), 
	FOREIGN KEY(evidence_id) REFERENCES cadastre.evidence (id), 
	FOREIGN KEY(actor_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_attestations_actor_id ON cadastre.geometry_attestations (actor_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_attestations_evidence_id ON cadastre.geometry_attestations (evidence_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_attestations_geometry_id ON cadastre.geometry_attestations (geometry_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.asset_bundles (
	parcel_id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	cache_key VARCHAR(64) NOT NULL, 
	snapshot JSONB NOT NULL, 
	placement JSONB NOT NULL, 
	manifest JSONB NOT NULL, 
	validation JSONB NOT NULL, 
	actor_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(parcel_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(job_id) REFERENCES cadastre.processing_jobs (id), 
	UNIQUE (cache_key), 
	FOREIGN KEY(actor_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_asset_bundles_actor_id ON cadastre.asset_bundles (actor_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_asset_bundles_job_id ON cadastre.asset_bundles (job_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_asset_bundles_parcel_id ON cadastre.asset_bundles (parcel_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.identity_versions (
	identity_id UUID NOT NULL, 
	geometry_id UUID NOT NULL, 
	canonical_code VARCHAR(100) NOT NULL, 
	geometry_hash VARCHAR(64) NOT NULL, 
	identity_inputs JSONB NOT NULL, 
	actor_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(identity_id) REFERENCES cadastre.ulpin_identities (id), 
	UNIQUE (geometry_id), 
	FOREIGN KEY(geometry_id) REFERENCES cadastre.geometry_versions (id), 
	UNIQUE (canonical_code), 
	FOREIGN KEY(actor_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_identity_versions_actor_id ON cadastre.identity_versions (actor_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_identity_versions_identity_id ON cadastre.identity_versions (identity_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.spatial_suggestions (
	parent_id UUID NOT NULL, 
	dataset_id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	label VARCHAR(160) NOT NULL, 
	footprint geometry(POLYGON,4326) NOT NULL, 
	source_category VARCHAR(30) NOT NULL, 
	confidence FLOAT, 
	method TEXT NOT NULL, 
	parameters JSONB NOT NULL, 
	is_synthetic BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT suggestion_kind CHECK (kind IN ('BUILDING','UNIT','SHARED')), 
	CONSTRAINT suggestion_confidence CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1), 
	CONSTRAINT suggestion_valid CHECK (ST_IsValid(footprint) AND NOT ST_IsEmpty(footprint)), 
	FOREIGN KEY(parent_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(dataset_id) REFERENCES cadastre.source_datasets (id), 
	FOREIGN KEY(job_id) REFERENCES cadastre.processing_jobs (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX idx_spatial_suggestions_footprint ON cadastre.spatial_suggestions USING gist (footprint);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_suggestions_dataset_id ON cadastre.spatial_suggestions (dataset_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_suggestions_job_id ON cadastre.spatial_suggestions (job_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_suggestions_parent_id ON cadastre.spatial_suggestions (parent_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.suggestion_decisions (
	suggestion_id UUID NOT NULL, 
	geometry_id UUID, 
	decision VARCHAR(30) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT suggestion_decision CHECK (decision IN ('ADOPTED_AS_DRAFT','REJECTED')), 
	UNIQUE (suggestion_id), 
	FOREIGN KEY(suggestion_id) REFERENCES cadastre.spatial_suggestions (id), 
	FOREIGN KEY(geometry_id) REFERENCES cadastre.geometry_versions (id), 
	FOREIGN KEY(actor_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_suggestion_decisions_actor_id ON cadastre.suggestion_decisions (actor_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_suggestion_decisions_geometry_id ON cadastre.suggestion_decisions (geometry_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.geometry_changes (
	operation VARCHAR(20) NOT NULL, 
	reason TEXT NOT NULL, 
	evidence_id UUID NOT NULL, 
	review_decision_id UUID, 
	actor_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT change_operation CHECK (operation IN ('REPLACE','SPLIT','MERGE')), 
	FOREIGN KEY(evidence_id) REFERENCES cadastre.evidence (id), 
	FOREIGN KEY(review_decision_id) REFERENCES cadastre.review_decisions (id), 
	FOREIGN KEY(actor_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_changes_actor_id ON cadastre.geometry_changes (actor_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_changes_evidence_id ON cadastre.geometry_changes (evidence_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_changes_review_decision_id ON cadastre.geometry_changes (review_decision_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.change_members (
	change_id UUID NOT NULL, 
	geometry_id UUID NOT NULL, 
	direction VARCHAR(10) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT change_direction CHECK (direction IN ('BEFORE','AFTER')), 
	UNIQUE (change_id, geometry_id, direction), 
	FOREIGN KEY(change_id) REFERENCES cadastre.geometry_changes (id), 
	FOREIGN KEY(geometry_id) REFERENCES cadastre.geometry_versions (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_change_members_change_id ON cadastre.change_members (change_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_change_members_geometry_id ON cadastre.change_members (geometry_id);
-- ASTRA STATEMENT
ALTER TABLE cadastre.asset_bundles ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_asset_bundles BEFORE UPDATE OR DELETE ON cadastre.asset_bundles FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT
ALTER TABLE cadastre.change_members ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_change_members BEFORE UPDATE OR DELETE ON cadastre.change_members FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT
ALTER TABLE cadastre.geometry_attestations ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_geometry_attestations BEFORE UPDATE OR DELETE ON cadastre.geometry_attestations FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT
ALTER TABLE cadastre.geometry_changes ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_geometry_changes BEFORE UPDATE OR DELETE ON cadastre.geometry_changes FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT
ALTER TABLE cadastre.height_observations ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_height_observations BEFORE UPDATE OR DELETE ON cadastre.height_observations FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT
ALTER TABLE cadastre.identity_versions ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_identity_versions BEFORE UPDATE OR DELETE ON cadastre.identity_versions FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT
ALTER TABLE cadastre.spatial_suggestions ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_spatial_suggestions BEFORE UPDATE OR DELETE ON cadastre.spatial_suggestions FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT
ALTER TABLE cadastre.suggestion_decisions ENABLE ROW LEVEL SECURITY;
-- ASTRA STATEMENT
CREATE TRIGGER immutable_suggestion_decisions BEFORE UPDATE OR DELETE ON cadastre.suggestion_decisions FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();
-- ASTRA STATEMENT

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
