#!/bin/sh
set -eu

timestamp="$(date -u +%Y%m%d%H%M%S)"
backup_file="$(mktemp)"
restore_db="restore_check_${timestamp}_$$"
created_db=0

cleanup() {
    exit_status=$?
    cleanup_status=0
    trap - EXIT HUP INT TERM
    if [ "$created_db" -eq 1 ]; then
        docker compose exec -T db sh -c \
            'dropdb -U "$POSTGRES_USER" "$1"' sh "$restore_db" || cleanup_status=$?
    fi
    rm -f "$backup_file"
    if [ "$exit_status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
        exit "$cleanup_status"
    fi
    exit "$exit_status"
}
trap cleanup EXIT

docker compose exec -T db sh -c \
    'pg_dump -U "$POSTGRES_USER" --format=custom --no-owner --no-acl "$POSTGRES_DB"' > "$backup_file"
docker compose exec -T db sh -c \
    'createdb -U "$POSTGRES_USER" "$1"' sh "$restore_db"
created_db=1
docker compose exec -T db sh -c \
    'pg_restore -U "$POSTGRES_USER" --no-owner --no-acl --dbname="$1"' \
    sh "$restore_db" < "$backup_file"
migration_count="$(
    docker compose exec -T db sh -c \
        'psql -U "$POSTGRES_USER" --tuples-only --no-align --dbname="$1" -c "SELECT COUNT(*) FROM django_migrations"' \
        sh "$restore_db" | tr -d '[:space:]'
)"
if [ -z "$migration_count" ] || [ "$migration_count" -lt 1 ]; then
    echo "Restored database did not contain Django migrations." >&2
    exit 1
fi
printf 'Backup and restore verified (%s migration records).\n' "$migration_count"
