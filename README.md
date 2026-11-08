# Hospital Management Service

A Django REST Framework API backed by PostgreSQL. It provides patient accounts and profiles, approved doctor workspaces, consent-gated records, private documents, hospital and doctor directories, moderated reviews, and append-only audit logs.

> **Sensitive-data notice:** This repository is a learning and starter service, not a compliance certification. Do not store real patient information until your organization has reviewed privacy, retention, encryption-at-rest, backup, access, and legal requirements.

## What is included

- Email/password registration and short-lived JWT access tokens; administrator login also requires TOTP.
- Patient profile ownership and role-based API permissions.
- Append-only audit records that store action names and field names, not passwords or medical-record contents.
- Explicit, expiring, revocable patient consent for doctor access.
- Doctor applications that remain unapproved until an administrator approves them.
- Immutable, versioned medical records and a tested PostgreSQL backup/restore workflow.
- Private, randomly named PDF/PNG/JPEG uploads (10 MiB maximum) with authenticated downloads.
- Searchable, paginated hospital and approved-doctor directories.
- One review per closed visit, moderation, reporting, and report throttling.
- Gunicorn, Nginx/TLS configuration, CI security checks, and an SSH deployment workflow.

For a complete explanation of the implementation, follow the [beginner guide](docs/BEGINNER_GUIDE.md).

## Run locally with Docker

Requirements: Docker Engine and the Docker Compose plugin.

1. Copy the example environment file:

   ```sh
   cp .env.example .env
   ```

2. Generate values for `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, and `FIELD_ENCRYPTION_KEY`, and replace the example values in `.env`. For example:

   ```sh
   python3 -c "import secrets; print(secrets.token_urlsafe(64))"
   python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
   ```

   Use the first command for `DJANGO_SECRET_KEY`; the second produces a Fernet key for `FIELD_ENCRYPTION_KEY`. Keep the encryption key stable: it is needed to decrypt stored administrator TOTP secrets.

3. Build and start the application:

   ```sh
   docker compose up -d --build --wait
   ```

   The web container waits for PostgreSQL, runs database migrations and `collectstatic`, and then starts Gunicorn. The local API is at `http://127.0.0.1:8000`; health is at `/api/health/`.

4. Create an administrator interactively and enroll its TOTP authenticator:

   ```sh
   docker compose exec web python manage.py create_admin admin@example.com
   docker compose exec web python manage.py setup_2fa admin@example.com
   ```

   `setup_2fa` prints a provisioning URI. Treat it as a secret and add it to an authenticator app. No administrator account or password is embedded in the source.

Interactive Swagger UI is available at `/api/docs/`; the OpenAPI schema is at `/api/schema/`. Both endpoints are covered by an API test.

## API map

| Area | Main routes |
|---|---|
| Authentication | `/api/auth/register/`, `/login/`, `/login/2fa/`, `/refresh/`, `/logout/`, `/me/` |
| Patient profile and consent | `/api/patients/me/`, `/api/patients/consents/` |
| Own audit history | `/api/audit/my-logs/` (patients only) |
| Admin audit history | `/api/audit/logs/` (admins only) |
| Directories | `/api/hospitals/`, `/api/doctors/`; doctor application: `/api/doctors/apply/` |
| Visits and records | `/api/care/visits/`, `/api/care/records/`, `/api/care/documents/` |
| Reviews | `/api/reviews/`, `/api/reviews/{id}/report/` |
| Admin APIs | `/api/admin/hospitals/`, `/api/admin/doctors/`, `/api/admin/visits/`, `/api/admin/reviews/` |

Search directories with `name`, `city`, `specialty`, `hospital`, or `min_rating` as applicable. Lists return three results by default; `page_size` may be between 1 and 50. Only approved doctors and approved reviews appear publicly. Documents are never served from a public media URL.

## Tests and checks

```sh
docker compose exec web pytest -q
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py spectacular --validate --fail-on-warn
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.prod web python manage.py check --deploy
python3 -m ruff check .
./scripts/test-db-backup-restore.sh
python3 scripts/load-sanity.py
```

CI runs the Django tests with coverage reporting, a real PostgreSQL backup/restore check, a small concurrent health-endpoint check, Django production checks, Ruff, Bandit, `pip-audit` against runtime dependencies, and a Trivy image scan. Successful coverage reports are uploaded as the `coverage-report` workflow artifact. The audit tests also fail if a protected API view is added without the audit mixin. `requirements.txt` contains production dependencies; `requirements-dev.txt` adds test and scanner tools.

## Database backups

Create a compressed PostgreSQL backup:

```sh
./scripts/backup-db.sh
```

Restore into a **new** database so the current database is not overwritten:

```sh
./scripts/restore-db.sh backups/hospital-YYYYMMDDTHHMMSSZ.dump hospital_restore
```

After verifying the restored database, follow your operational cutover procedure to point the application at it. Backups are ignored by Git; store and protect them according to your data-retention policy.

## Production and deployment

- Set `DJANGO_SETTINGS_MODULE=config.settings.prod`, `DJANGO_DEBUG=false`, a strong `DJANGO_SECRET_KEY`, comma-separated `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and database/encryption secrets.
- Provision TLS certificate files at `deploy/tls/fullchain.pem` and `deploy/tls/privkey.pem`. The production Nginx overlay redirects HTTP to HTTPS and proxies only API/static routes. It deliberately does not expose `/media/`.
- Start the production stack with:

  ```sh
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
  ```

- Configure the host timer in [hospital-health-restart.timer](deploy/hospital-health-restart.timer) and [hospital-health-restart.service](deploy/hospital-health-restart.service) to restart unhealthy web or Nginx containers.
- The deploy workflow runs after successful CI on `main`. Prepare the server at `/opt/hospital-management-service`, install Docker Compose and TLS files, and add GitHub Actions secrets for `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `FIELD_ENCRYPTION_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. App secrets are transferred over SSH and written to the server's ignored `.env` file with restrictive permissions.

The deployment workflow assumes the production branch is named `main` and the server checkout path is `/opt/hospital-management-service`. Adjust those values if your hosting setup differs.
