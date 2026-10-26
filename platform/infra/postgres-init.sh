#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
 -v analytics_pass="$ANALYTICS_PASSWORD" -v checkpoint_pass="$CHECKPOINT_PASSWORD" \
 -v readonly_pass="$ANALYSIS_PASSWORD" -v dify_pass="$DIFY_DB_PASSWORD" -v plugin_pass="$DIFY_PLUGIN_DB_PASSWORD" <<'SQL'
CREATE ROLE talent_analytics LOGIN PASSWORD :'analytics_pass';
CREATE ROLE talent_checkpoint LOGIN PASSWORD :'checkpoint_pass';
CREATE ROLE talent_readonly LOGIN PASSWORD :'readonly_pass';
CREATE ROLE dify LOGIN PASSWORD :'dify_pass';
CREATE ROLE dify_plugin LOGIN PASSWORD :'plugin_pass';
CREATE DATABASE talent_analytics OWNER talent_analytics;
CREATE DATABASE talent_checkpoint OWNER talent_checkpoint;
CREATE DATABASE dify OWNER dify;
CREATE DATABASE dify_plugin OWNER dify_plugin;
REVOKE CONNECT ON DATABASE talent_analytics FROM PUBLIC;
REVOKE CONNECT ON DATABASE talent_checkpoint FROM PUBLIC;
REVOKE CONNECT ON DATABASE dify FROM PUBLIC;
REVOKE CONNECT ON DATABASE dify_plugin FROM PUBLIC;
GRANT CONNECT ON DATABASE talent_analytics TO talent_readonly;
\connect talent_analytics
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO talent_readonly;

ALTER ROLE talent_readonly SET default_transaction_read_only = on;
ALTER ROLE talent_readonly SET statement_timeout = '15000';
SQL

