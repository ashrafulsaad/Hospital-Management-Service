#!/bin/sh
set -eu

backup_dir="${BACKUP_DIR:-backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${backup_dir}/hospital-${timestamp}.dump"

mkdir -p "$backup_dir"
docker compose exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" --format=custom --no-owner --no-acl "$POSTGRES_DB"' > "$backup_file"
printf 'Database backup written to %s\n' "$backup_file"
