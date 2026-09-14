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
