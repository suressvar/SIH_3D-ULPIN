CREATE EXTENSION IF NOT EXISTS postgis;
-- ASTRA STATEMENT
CREATE SCHEMA cadastre;
-- ASTRA STATEMENT

CREATE TABLE cadastre.app_users (
	role VARCHAR(20) NOT NULL, 
	active BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT user_role CHECK (role IN ('viewer','surveyor','officer','admin'))
)

;
-- ASTRA STATEMENT

CREATE TABLE cadastre.audit_events (
	actor_id UUID NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	entity_type VARCHAR(80) NOT NULL, 
	entity_id UUID NOT NULL, 
	detail JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_audit_events_action ON cadastre.audit_events (action);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_audit_events_actor_id ON cadastre.audit_events (actor_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_audit_events_entity_id ON cadastre.audit_events (entity_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.source_datasets (
	filename VARCHAR(255) NOT NULL, 
	media_type VARCHAR(100) NOT NULL, 
	source_category VARCHAR(30) NOT NULL, 
	object_key VARCHAR(500) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	byte_size INTEGER NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	inspection JSONB NOT NULL, 
	error_message TEXT, 
	is_synthetic BOOLEAN NOT NULL, 
	created_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT dataset_source CHECK (source_category IN ('SURVEY','APPROVED_PLAN','LIDAR','DRONE_IMAGERY','DEM_DSM','AI_ESTIMATE','MANUAL','DERIVED')), 
	CONSTRAINT dataset_status CHECK (status IN ('UPLOADED','READY','REJECTED','EVIDENCE_ONLY')), 
	CONSTRAINT dataset_size CHECK (byte_size > 0), 
	UNIQUE (object_key), 
	FOREIGN KEY(created_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_source_datasets_created_by ON cadastre.source_datasets (created_by);
-- ASTRA STATEMENT

CREATE TABLE cadastre.spatial_objects (
	kind VARCHAR(20) NOT NULL, 
	label VARCHAR(160) NOT NULL, 
	parent_id UUID, 
	parcel_id UUID, 
	existing_ulpin VARCHAR(14), 
	floor_number INTEGER, 
	is_synthetic BOOLEAN NOT NULL, 
	created_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT object_kind CHECK (kind IN ('PARCEL','BUILDING','FLOOR','UNIT','UNDERGROUND','SHARED','EASEMENT','INFRASTRUCTURE')), 
	CONSTRAINT object_root CHECK ((kind = 'PARCEL' AND parent_id IS NULL AND parcel_id IS NULL) OR (kind <> 'PARCEL' AND parent_id IS NOT NULL AND parcel_id IS NOT NULL)), 
	CONSTRAINT no_self_parent CHECK (parent_id IS NULL OR parent_id <> id), 
	CONSTRAINT parent_ulpin_format CHECK (existing_ulpin IS NULL OR (kind = 'PARCEL' AND existing_ulpin ~ '^[A-Za-z0-9]{14}$')), 
	CONSTRAINT floor_number_kind CHECK (floor_number IS NULL OR kind = 'FLOOR'), 
	FOREIGN KEY(parent_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(parcel_id) REFERENCES cadastre.spatial_objects (id), 
	UNIQUE (existing_ulpin), 
	FOREIGN KEY(created_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_objects_created_by ON cadastre.spatial_objects (created_by);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_objects_kind ON cadastre.spatial_objects (kind);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_objects_parcel_id ON cadastre.spatial_objects (parcel_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_objects_parent_id ON cadastre.spatial_objects (parent_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.evidence (
	object_id UUID NOT NULL, 
	dataset_id UUID NOT NULL, 
	description TEXT NOT NULL, 
	created_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(object_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(dataset_id) REFERENCES cadastre.source_datasets (id), 
	FOREIGN KEY(created_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_evidence_created_by ON cadastre.evidence (created_by);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_evidence_dataset_id ON cadastre.evidence (dataset_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_evidence_object_id ON cadastre.evidence (object_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.geometry_versions (
	object_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	footprint geometry(POLYGON,4326) NOT NULL, 
	metric_footprint geometry(POLYGON,-1) NOT NULL, 
	shell geometry(POLYHEDRALSURFACEZ,-1), 
	horizontal_crs VARCHAR(80) NOT NULL, 
	metric_srid INTEGER NOT NULL, 
	source_crs VARCHAR(80) NOT NULL, 
	transformation JSONB NOT NULL, 
	z_min FLOAT, 
	z_max FLOAT, 
	elevation_reference VARCHAR(160), 
	height_estimated BOOLEAN NOT NULL, 
	source_category VARCHAR(30) NOT NULL, 
	source_dataset_id UUID, 
	confidence FLOAT, 
	method TEXT NOT NULL, 
	geometry_hash VARCHAR(64) NOT NULL, 
	validity VARCHAR(40) NOT NULL, 
	created_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (object_id, version), 
	UNIQUE (id, object_id), 
	CONSTRAINT positive_version CHECK (version > 0), 
	CONSTRAINT geometry_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
	CONSTRAINT geometry_source CHECK (source_category IN ('SURVEY','APPROVED_PLAN','LIDAR','DRONE_IMAGERY','DEM_DSM','AI_ESTIMATE','MANUAL','DERIVED')), 
	CONSTRAINT footprint_valid CHECK (ST_IsValid(footprint) AND NOT ST_IsEmpty(footprint)), 
	CONSTRAINT metric_footprint_valid CHECK (ST_IsValid(metric_footprint) AND ST_SRID(metric_footprint) = metric_srid), 
	CONSTRAINT vertical_extent CHECK ((z_min IS NULL AND z_max IS NULL AND shell IS NULL) OR (z_min IS NOT NULL AND z_max IS NOT NULL AND z_max > z_min AND elevation_reference IS NOT NULL AND shell IS NOT NULL AND ST_SRID(shell) = metric_srid)), 
	FOREIGN KEY(object_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(source_dataset_id) REFERENCES cadastre.source_datasets (id), 
	FOREIGN KEY(created_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX idx_geometry_versions_footprint ON cadastre.geometry_versions USING gist (footprint);
-- ASTRA STATEMENT
CREATE INDEX idx_geometry_versions_metric_footprint ON cadastre.geometry_versions USING gist (metric_footprint);
-- ASTRA STATEMENT
CREATE INDEX idx_geometry_versions_shell ON cadastre.geometry_versions USING gist (shell);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_versions_created_by ON cadastre.geometry_versions (created_by);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_versions_object_id ON cadastre.geometry_versions (object_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_geometry_versions_source_dataset_id ON cadastre.geometry_versions (source_dataset_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.spatial_relationships (
	source_id UUID NOT NULL, 
	target_id UUID NOT NULL, 
	relation VARCHAR(40) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT relationship_type CHECK (relation IN ('AFFECTS','SERVES','SHARED_BY','PREDECESSOR')), 
	CONSTRAINT relationship_distinct CHECK (source_id <> target_id), 
	UNIQUE (source_id, target_id, relation), 
	FOREIGN KEY(source_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(target_id) REFERENCES cadastre.spatial_objects (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_relationships_source_id ON cadastre.spatial_relationships (source_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_spatial_relationships_target_id ON cadastre.spatial_relationships (target_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.processing_jobs (
	kind VARCHAR(40) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	progress INTEGER NOT NULL, 
	input_dataset_id UUID, 
	geometry_id UUID, 
	output_assets JSONB NOT NULL, 
	result JSONB NOT NULL, 
	error_message TEXT, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	dispatched_at TIMESTAMP WITH TIME ZONE, 
	created_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT job_kind CHECK (kind IN ('INGEST_GEOJSON','VALIDATE_PRISM')), 
	CONSTRAINT job_status CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')), 
	CONSTRAINT job_progress CHECK (progress BETWEEN 0 AND 100), 
	CONSTRAINT job_completion CHECK (status <> 'COMPLETED' OR (progress = 100 AND completed_at IS NOT NULL)), 
	CONSTRAINT job_input CHECK ((kind = 'INGEST_GEOJSON' AND input_dataset_id IS NOT NULL AND geometry_id IS NULL) OR (kind = 'VALIDATE_PRISM' AND geometry_id IS NOT NULL AND input_dataset_id IS NULL)), 
	FOREIGN KEY(input_dataset_id) REFERENCES cadastre.source_datasets (id), 
	FOREIGN KEY(geometry_id) REFERENCES cadastre.geometry_versions (id), 
	FOREIGN KEY(created_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_processing_jobs_created_by ON cadastre.processing_jobs (created_by);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_processing_jobs_geometry_id ON cadastre.processing_jobs (geometry_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_processing_jobs_input_dataset_id ON cadastre.processing_jobs (input_dataset_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_processing_jobs_status ON cadastre.processing_jobs (status);
-- ASTRA STATEMENT

CREATE TABLE cadastre.property_rights (
	object_id UUID NOT NULL, 
	evidence_id UUID NOT NULL, 
	right_type VARCHAR(30) NOT NULL, 
	party_reference VARCHAR(200) NOT NULL, 
	description TEXT NOT NULL, 
	is_synthetic BOOLEAN NOT NULL, 
	created_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT right_type CHECK (right_type IN ('RECORDED_OWNERSHIP','SHARED_USE','EASEMENT','RESTRICTION')), 
	FOREIGN KEY(object_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(evidence_id) REFERENCES cadastre.evidence (id), 
	FOREIGN KEY(created_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_property_rights_created_by ON cadastre.property_rights (created_by);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_property_rights_evidence_id ON cadastre.property_rights (evidence_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_property_rights_object_id ON cadastre.property_rights (object_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.ulpin_identities (
	object_id UUID NOT NULL, 
	issued_geometry_id UUID NOT NULL, 
	identifier VARCHAR(100) NOT NULL, 
	label VARCHAR(40) NOT NULL, 
	scheme_version VARCHAR(30) NOT NULL, 
	created_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(issued_geometry_id, object_id) REFERENCES cadastre.geometry_versions (id, object_id), 
	CONSTRAINT identity_label CHECK (label = 'Proposed 3D ULPIN'), 
	UNIQUE (object_id), 
	FOREIGN KEY(object_id) REFERENCES cadastre.spatial_objects (id), 
	UNIQUE (identifier), 
	FOREIGN KEY(created_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_ulpin_identities_created_by ON cadastre.ulpin_identities (created_by);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_ulpin_identities_issued_geometry_id ON cadastre.ulpin_identities (issued_geometry_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.review_cases (
	object_id UUID NOT NULL, 
	geometry_id UUID NOT NULL, 
	validation_job_id UUID NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	submitted_by UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(geometry_id, object_id) REFERENCES cadastre.geometry_versions (id, object_id), 
	UNIQUE (geometry_id, validation_job_id), 
	CONSTRAINT review_status CHECK (status IN ('SUBMITTED','ACCEPTED_PROTOTYPE','RETURNED')), 
	FOREIGN KEY(object_id) REFERENCES cadastre.spatial_objects (id), 
	FOREIGN KEY(validation_job_id) REFERENCES cadastre.processing_jobs (id), 
	FOREIGN KEY(submitted_by) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_review_cases_geometry_id ON cadastre.review_cases (geometry_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_review_cases_object_id ON cadastre.review_cases (object_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_review_cases_submitted_by ON cadastre.review_cases (submitted_by);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_review_cases_validation_job_id ON cadastre.review_cases (validation_job_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.validation_issues (
	job_id UUID NOT NULL, 
	geometry_id UUID NOT NULL, 
	related_geometry_id UUID, 
	code VARCHAR(60) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	message TEXT NOT NULL, 
	details JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT issue_severity CHECK (severity IN ('ERROR','WARNING','INFO')), 
	FOREIGN KEY(job_id) REFERENCES cadastre.processing_jobs (id), 
	FOREIGN KEY(geometry_id) REFERENCES cadastre.geometry_versions (id), 
	FOREIGN KEY(related_geometry_id) REFERENCES cadastre.geometry_versions (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_validation_issues_geometry_id ON cadastre.validation_issues (geometry_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_validation_issues_job_id ON cadastre.validation_issues (job_id);
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_validation_issues_related_geometry_id ON cadastre.validation_issues (related_geometry_id);
-- ASTRA STATEMENT

CREATE TABLE cadastre.review_decisions (
	review_id UUID NOT NULL, 
	decision VARCHAR(30) NOT NULL, 
	reason TEXT NOT NULL, 
	reviewer_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT decision_type CHECK (decision IN ('ACCEPTED_PROTOTYPE','RETURNED')), 
	UNIQUE (review_id), 
	FOREIGN KEY(review_id) REFERENCES cadastre.review_cases (id), 
	FOREIGN KEY(reviewer_id) REFERENCES cadastre.app_users (id)
)

;
-- ASTRA STATEMENT
CREATE INDEX ix_cadastre_review_decisions_reviewer_id ON cadastre.review_decisions (reviewer_id);
-- ASTRA STATEMENT
CREATE FUNCTION cadastre.check_hierarchy() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p cadastre.spatial_objects;
BEGIN
  IF TG_OP = 'UPDATE' AND (NEW.parent_id IS DISTINCT FROM OLD.parent_id OR NEW.parcel_id IS DISTINCT FROM OLD.parcel_id OR NEW.kind <> OLD.kind OR NEW.is_synthetic <> OLD.is_synthetic) THEN
    RAISE EXCEPTION 'Spatial hierarchy and synthetic classification are immutable';
  END IF;
  IF NEW.kind = 'PARCEL' THEN RETURN NEW; END IF;
  SELECT * INTO STRICT p FROM cadastre.spatial_objects WHERE id=NEW.parent_id;
  IF NEW.parcel_id IS DISTINCT FROM (CASE WHEN p.kind='PARCEL' THEN p.id ELSE p.parcel_id END) THEN
    RAISE EXCEPTION 'Invalid root parcel';
  END IF;
  IF NEW.is_synthetic <> p.is_synthetic THEN RAISE EXCEPTION 'Synthetic designation differs from parent'; END IF;
  IF NOT (
    (NEW.kind='BUILDING' AND p.kind='PARCEL') OR
    (NEW.kind='FLOOR' AND p.kind='BUILDING') OR
    (NEW.kind='UNIT' AND p.kind='FLOOR') OR
    (NEW.kind='UNDERGROUND' AND p.kind IN ('PARCEL','BUILDING')) OR
    (NEW.kind='SHARED' AND p.kind IN ('PARCEL','BUILDING','FLOOR')) OR
    (NEW.kind='EASEMENT' AND p.kind='PARCEL') OR
    (NEW.kind='INFRASTRUCTURE' AND p.kind IN ('PARCEL','EASEMENT'))
  ) THEN RAISE EXCEPTION 'Invalid parent kind'; END IF;
  RETURN NEW;
END $$;

-- ASTRA STATEMENT

CREATE TRIGGER spatial_hierarchy BEFORE INSERT OR UPDATE ON cadastre.spatial_objects FOR EACH ROW EXECUTE FUNCTION cadastre.check_hierarchy();

-- ASTRA STATEMENT

CREATE FUNCTION cadastre.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Immutable record: append a new version or event'; END $$;

-- ASTRA STATEMENT

CREATE TRIGGER immutable_geometry BEFORE UPDATE OR DELETE ON cadastre.geometry_versions FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();

-- ASTRA STATEMENT

CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON cadastre.audit_events FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();

-- ASTRA STATEMENT

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON cadastre.evidence FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();

-- ASTRA STATEMENT

CREATE TRIGGER immutable_right BEFORE UPDATE OR DELETE ON cadastre.property_rights FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();

-- ASTRA STATEMENT

CREATE TRIGGER immutable_decision BEFORE UPDATE OR DELETE ON cadastre.review_decisions FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();

-- ASTRA STATEMENT

CREATE TRIGGER immutable_identity BEFORE UPDATE OR DELETE ON cadastre.ulpin_identities FOR EACH ROW EXECUTE FUNCTION cadastre.reject_mutation();

-- ASTRA STATEMENT

CREATE FUNCTION cadastre.check_evidence_right() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE property_synthetic boolean; evidence_object uuid; dataset_synthetic boolean; dataset_status text;
BEGIN
  SELECT is_synthetic INTO STRICT property_synthetic FROM cadastre.spatial_objects WHERE id=NEW.object_id;
  IF TG_TABLE_NAME='evidence' THEN
    SELECT is_synthetic,status INTO STRICT dataset_synthetic,dataset_status FROM cadastre.source_datasets WHERE id=NEW.dataset_id;
    IF property_synthetic <> dataset_synthetic OR dataset_status NOT IN ('READY','EVIDENCE_ONLY') THEN RAISE EXCEPTION 'Invalid evidence source'; END IF;
  ELSE
    SELECT object_id INTO STRICT evidence_object FROM cadastre.evidence WHERE id=NEW.evidence_id;
    IF evidence_object <> NEW.object_id OR property_synthetic <> NEW.is_synthetic THEN RAISE EXCEPTION 'Right evidence mismatch'; END IF;
  END IF;
  RETURN NEW;
END $$;

-- ASTRA STATEMENT

CREATE TRIGGER check_evidence BEFORE INSERT ON cadastre.evidence FOR EACH ROW EXECUTE FUNCTION cadastre.check_evidence_right();

-- ASTRA STATEMENT

CREATE TRIGGER check_right BEFORE INSERT ON cadastre.property_rights FOR EACH ROW EXECUTE FUNCTION cadastre.check_evidence_right();

-- ASTRA STATEMENT

REVOKE ALL ON SCHEMA cadastre FROM PUBLIC;

-- ASTRA STATEMENT

REVOKE ALL ON ALL TABLES IN SCHEMA cadastre FROM PUBLIC;

-- ASTRA STATEMENT

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cadastre FROM PUBLIC;

-- ASTRA STATEMENT

DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='cadastre' LOOP
    EXECUTE format('ALTER TABLE cadastre.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    -- Only the private backend role gets a policy. Supabase anon/authenticated do not.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='astra_app') THEN
      EXECUTE format('CREATE POLICY backend_access ON cadastre.%I TO astra_app USING (true) WITH CHECK (true)', t.tablename);
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='astra_app') THEN
    GRANT USAGE ON SCHEMA cadastre TO astra_app;
    GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA cadastre TO astra_app;
    REVOKE INSERT ON cadastre.app_users FROM astra_app;
    GRANT UPDATE(label) ON cadastre.spatial_objects TO astra_app;
    GRANT UPDATE ON cadastre.source_datasets,cadastre.processing_jobs,cadastre.review_cases TO astra_app;
  END IF;
END $$;
