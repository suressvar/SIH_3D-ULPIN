-- Local development ONLY. Production credentials must be provisioned separately.
CREATE ROLE astra_app LOGIN PASSWORD 'astra_app_local' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE astra_test OWNER astra;
