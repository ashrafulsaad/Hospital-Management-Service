#!/bin/sh
set -eu

for service in web nginx; do
    container_id="$(docker compose ps -q "$service")"
    if [ -z "$container_id" ]; then
        continue
    fi

    state="$(docker inspect --format '{{.State.Status}}' "$container_id")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_id")"
    if [ "$state" != "running" ] || [ "$health" = "unhealthy" ]; then
        docker compose up -d "$service"
    fi
done
