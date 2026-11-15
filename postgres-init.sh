#!/bin/sh
set -eu

psql \
    --set=ON_ERROR_STOP=1 \
    --set=app_password="$APP_DB_PASSWORD" \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE rtla_app LOGIN PASSWORD :'app_password';
CREATE DATABASE signaldesk OWNER rtla_app;
SQL
