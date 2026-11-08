#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: $0 BACKUP_FILE [NEW_DATABASE_NAME]" >&2
    exit 2
fi

backup_file="$1"
target_db="${2:-hospital_restore}"
case "$target_db" in
    *[!A-Za-z0-9_]*|[0-9]*|"")
        echo "Database name may contain only letters, numbers, and underscores." >&2
        exit 2
        ;;
esac
if [ "${#target_db}" -gt 63 ]; then
    echo "Database names may not exceed 63 characters." >&2
    exit 2
fi
if [ ! -f "$backup_file" ]; then
    echo "Backup file not found: $backup_file" >&2
    exit 2
fi

docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$target_db"
docker compose exec -T db sh -c \
    'pg_restore -U "$POSTGRES_USER" --no-owner --no-acl --dbname="$1"' \
    sh "$target_db" < "$backup_file"
printf 'Restored backup into new database %s; the existing database was not changed.\n' "$target_db"
