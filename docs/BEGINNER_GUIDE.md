# Beginner Guide: Chunks 0–13

This guide assumes you are new to the project and to Django. Work through it from top to bottom: first start the application, then trace one request, then learn each numbered feature and its tests.

## 1. What this project does

This is a web API. A user sends an HTTP request to a URL; Django routes it to a view; the view checks permission and validates input; a model reads or writes PostgreSQL; and Django returns JSON.

The main technology words:

- **Django** is the Python web framework.
- **Django REST Framework (DRF)** adds serializers, API views, permissions, and JSON responses.
- A **model** describes stored data and becomes a database table.
- A **serializer** converts Python/model values to JSON and validates incoming JSON.
- A **view** handles a request, calls application logic, and returns a response.
- A **migration** is a versioned database schema change.
- **Docker** packages the application; **Compose** starts the web and database containers together.
- **JWT** is a signed token the client sends in the `Authorization: Bearer ...` header.
- A **test** is executable code that checks expected behavior automatically.

## 2. First run

Install Docker Engine and Docker Compose. From the repository folder:

```sh
cp .env.example .env
```

Edit `.env`. Generate a long Django secret and a Fernet encryption key:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Put those values in `DJANGO_SECRET_KEY` and `FIELD_ENCRYPTION_KEY` respectively. Set a strong `POSTGRES_PASSWORD`. Never commit `.env`; it is ignored by Git.

Start the application:

```sh
docker compose up -d --build --wait
docker compose ps
```

Try the health URL in a browser or terminal:

```text
http://127.0.0.1:8000/api/health/
```

The JSON response should report `"status": "ok"` and `"database": "connected"`. The container's startup script applies migrations and gathers static files before starting Gunicorn.

Open `http://127.0.0.1:8000/api/docs/` for the interactive Swagger UI. It lets you inspect the API operations and try requests. The underlying OpenAPI document is available at `http://127.0.0.1:8000/api/schema/`.

To see logs:

```sh
docker compose logs -f web
```

To stop the app without deleting its database:

```sh
docker compose stop
```

Avoid `docker compose down -v` on any database that contains data: `-v` deletes its named volumes.

## 3. Learn the folders

| Folder/file | What you will find there |
|---|---|
| `accounts/` | User model, registration, login, role permissions, administrator commands |
| `patients/` | Patient profile and patient-specific API |
| `care/` | Hospitals, doctor applications, consent, visits, records, documents, and reviews |
| `audit/` | Audit-log model, safe audit-writing helper, and audit API |
| `api/` | Public health endpoint |
| `config/` | URL routing and development/production/test settings |
| `tests/` | API, access-control, immutability, privacy, and audit tests |
| `scripts/` | Container entrypoint, database backup/restore, health recovery, and load check |
| `.github/workflows/` | Continuous integration and server deployment definitions |

A feature generally has a **model** (stored data), **serializer** (input/output contract), **view** (HTTP handling), **URL** (route), **migration** (database structure), and **tests**.

## 4. A request from start to finish

Consider `GET /api/patients/me/`:

1. `config/urls.py` routes `/api/patients/` to `patients/urls.py`.
2. `patients/urls.py` selects `MyProfileView`.
3. The view requires the patient role and looks up the profile using the authenticated user's ID—not an ID supplied in the URL.
4. `PatientProfileSerializer` returns an explicit list of safe profile fields.
5. The view writes an audit event containing the action and field names, not the profile contents.
6. The audit mixin supplies a safe access event for other successful authenticated endpoints that do not already write a more specific one.

The same flow applies elsewhere: URL → permission → validation → service/model → JSON response → audit event.

## Chunk 0 — Project foundation

**Goal:** run a Django API with a database and separate configuration.

- `manage.py` is the command-line entrypoint.
- `config/settings/base.py` holds shared settings.
- `config/settings/dev.py`, `test.py`, and `prod.py` specialize the shared settings.
- `docker-compose.yml` runs PostgreSQL and the web container.
- `api/health.py` checks both the API and database connection.

Configuration comes from environment variables, not hard-coded production credentials. The example file is only a template; change its placeholder secrets.

## Chunk 1 — Accounts and authentication

**Goal:** identify the caller and limit privileges.

- Users sign in with email and password.
- Passwords are hashed by Django; passwords are never placed in audit metadata.
- A patient receives JWT access and refresh tokens. Clients send an access token as `Authorization: Bearer <token>`.
- Refresh tokens rotate and logout blacklists the refresh token.
- Admin sign-in uses a second TOTP step. The regular Django admin site is intentionally not exposed.
- Public registration creates a patient. A request cannot choose the doctor or admin role.

Create an admin interactively:

```sh
docker compose exec web python manage.py create_admin admin@example.com
docker compose exec web python manage.py setup_2fa admin@example.com
```

The first command asks for a password without putting it in the command line. The second prints a TOTP provisioning URI; do not share or log it.

## Chunk 2 — Patient profiles

**Goal:** make patient data ownership explicit.

`GET` and `PATCH /api/patients/me/` operate only on the current patient's profile. There is no patient ID parameter to tamper with. The serializer is a whitelist: it does not accept a replacement user, role, or email. `PUT` and delete are not enabled.

Try registering a synthetic test account, then authenticate and call the profile endpoint. Do not use real medical information for local experiments.

## Chunk 3 — Audit log

**Goal:** produce a safe, append-only record of protected actions.

`audit/models.py` prevents updates and deletes through both model instances and querysets. `audit/services.py` accepts action/resource identifiers and field **names** only. The mixin adds a generic event for successful authenticated API requests; sensitive operations write a more specific event.

The audit tests check:

- profile reads/updates, registration, record corrections, consent, documents, and moderation create entries;
- stored fields contain no passwords or full medical-record text;
- direct and bulk updates/deletes fail;
- every protected API view uses the audit mixin.

When adding an authenticated endpoint, inherit `AuditProtectedRequestMixin`. If the operation touches a known patient/resource, use `log_action` with that subject and safe field names.

## Chunk 4 — Consent

**Goal:** deny doctor access until the patient grants active consent.

Patients can list/grant consent at `/api/patients/consents/` and revoke a grant at `/api/patients/consents/{id}/revoke/`. Each grant has an optional expiration; revocation is stored as a separate event rather than rewriting the grant.

`care/services.py` owns the shared `has_active_consent` check. Doctor visits, records, corrections, and document access all use the same policy. No matching, unexpired, unrevoked grant means **deny**.

Tests freeze time so they can prove a grant is active before expiry, inactive after expiry, and inactive after revocation without waiting in real time.

## Chunk 5 — Doctor approval

**Goal:** make doctor status an administrator-controlled privilege.

Any patient can submit a doctor application at `/api/doctors/apply/`. The account remains a patient and the application remains pending. Only an admin can list applications and approve one at `/api/admin/doctors/` and `/api/admin/doctors/{id}/approve/`. Approval changes both the profile status and account role in one database transaction.

All doctor workspace permissions check for an approved profile. A `role=doctor` value alone is not enough. Tests cover self-registration as a doctor, unapproved doctor access, and an admin approval flow.

## Chunk 6 — Medical records and backups

**Goal:** preserve the history of clinical corrections and prove database recovery.

A visit can have one `MedicalRecord`; its clinical text is stored in numbered `MedicalRecordVersion` rows. The model blocks updating or deleting an existing record/version. A doctor correction creates the next version, so version 1 stays unchanged. There is no record deletion route.

Back up the PostgreSQL database:

```sh
./scripts/backup-db.sh
```

Restore a backup into a **new** database and inspect it before any cutover:

```sh
./scripts/restore-db.sh backups/hospital-your-timestamp.dump hospital_restore
```

CI runs `scripts/test-db-backup-restore.sh`: it creates a temporary database, restores a real dump, checks the migration table, and cleans up only the database it created.

## Chunk 7 — Documents

**Goal:** accept only bounded uploads and never publish private files.

Uploads accept PDF, PNG, and JPEG file signatures up to 10 MiB. The web server has an 11 MiB request cap to allow multipart form overhead; the application still enforces the 10 MiB file limit. Extensions must match detected content. Django sanitizes incoming path components and storage assigns a random UUID filename.

Uploads live in the named `uploads_data` volume. Nginx serves static files only; it has no public media route. A download uses `/api/care/documents/{id}/download/`, checks patient ownership or approved-doctor assignment plus consent, and returns a file attachment.

Tests cover unsupported types, too-large files, mismatched signatures, traversal-like filenames, anonymous downloads, cross-patient downloads, and random stored names.

## Chunk 8 — Access log visibility

**Goal:** patients can inspect only their own audit history.

Patients can use `/api/audit/my-logs/`, which filters by the authenticated patient. `/api/audit/logs/` is administrator-only. Doctors cannot read either feed and no API provides log updates/deletes. The mixin records generic protected accesses; explicit clinical actions associate the audit item with the affected patient where appropriate.

## Chunk 9 — Hospital directory

**Goal:** search hospitals without unbounded queries or results.

`GET /api/hospitals/` is public and supports `name`, `city`, and `specialty` filters. Search fields are validated, unknown parameters are rejected, and ORM filters keep user input out of raw SQL. The database indexes the common search combinations.

The default page has three hospitals; `page_size` is bounded from 1 to 50. Tests combine filters, assert the three-item limit, reject invalid values, and check that a normal page requires only a count and a result query.

Admins add hospitals with `POST /api/admin/hospitals/`.

## Chunk 10 — Doctor directory

**Goal:** present approved doctors without exposing private application details.

`GET /api/doctors/` includes approved profiles only. It supports specialty and hospital filters and a minimum approved-review rating. The response deliberately omits account email and medical license number. Ratings are computed only from approved reviews.

Tests exercise filter/rating behavior and assert private fields are absent from public responses.

## Chunk 11 — Reviews

**Goal:** collect feedback tied to a completed visit and moderate it before publication.

A patient may submit one review for their own closed visit. A unique database constraint enforces one review per visit; new reviews are pending until an administrator approves them. Only approved reviews appear publicly.

Review text has length and basic abusive-term validation. Authenticated reports are rate-limited, and duplicate reports by the same account are rejected. Admin moderation happens at `/api/admin/reviews/{id}/moderate/`.

## Chunk 12 — Admin APIs

**Goal:** separate administrative actions from patient/doctor access.

Admin-only endpoints manage hospitals, review pending doctor applications, approve doctors, create visits, and moderate reviews. They use the admin role permission and are audited. Tests send requests to every admin route as a patient and verify `403 Forbidden`.

`create_admin` is the supported first-admin bootstrap: it prompts for credentials rather than embedding them in code. The admin then enrolls TOTP with `setup_2fa`.

## Chunk 13 — Production hardening

**Goal:** run the API behind HTTPS with secrets and health checks managed outside source control.

- Gunicorn runs as a non-root container user. Nginx is the public entrypoint in the production Compose overlay.
- Nginx redirects HTTP to HTTPS, uses TLS 1.2+, limits request size and request rate, serves static files, and does not publish patient media.
- Production Django settings turn off DEBUG, require secret/host configuration, enable secure cookies, HTTPS redirect, HSTS, content-type protection, and referrer policy.
- Docker health checks verify PostgreSQL, web API/database health, and Nginx. The supplied systemd timer restarts unhealthy web/Nginx services.
- JSON container logs rotate by size/count and go to the container logging driver.
- CI runs tests, coverage reporting, Ruff, Bandit, dependency auditing, Trivy, database restore verification, a load sanity test, and `check --deploy` with warnings treated as failures.
- The deploy workflow runs only after successful CI on `main`, delivers secrets from GitHub Actions secrets to an ignored server `.env`, deploys the tested commit over verified SSH, waits for healthy containers, and calls the HTTPS health endpoint.

Before deploying, put the certificate and private key at `deploy/tls/fullchain.pem` and `deploy/tls/privkey.pem` on the server. Install the systemd timer as described below, and configure GitHub secrets for the server and application secrets:

```sh
sudo cp deploy/hospital-health-restart.service /etc/systemd/system/
sudo cp deploy/hospital-health-restart.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hospital-health-restart.timer
```

The supplied service expects the checkout at `/opt/hospital-management-service`. Update its `WorkingDirectory` and `ExecStart` if you use another path. The deploy workflow assumes the branch is `main`; change the filter and remote fetch if your production branch differs.

## How to change the project safely

For a new field or feature:

1. Read the model, serializer, view, URL, and tests for the closest existing feature.
2. Decide the permission and ownership rule before writing the view.
3. Add or update the model and serializer; keep public output fields explicit.
4. Add a migration:

   ```sh
   docker compose exec web python manage.py makemigrations
   ```

5. Add tests for allowed access, denied access, invalid input, and audit logging.
6. Run validation:

   ```sh
   docker compose exec web pytest -q
   docker compose exec web python manage.py makemigrations --check --dry-run
   docker compose exec web python manage.py spectacular --validate --fail-on-warn
   python3 -m ruff check .
   ```

7. Keep migrations, tests, and docs in the same change.

## Glossary

- **Authentication:** proving who made a request.
- **Authorization/permission:** deciding what that authenticated user may do.
- **Consent:** a patient's current, time-bounded permission for doctor access.
- **Append-only:** new history entries can be added, but existing entries cannot be edited or removed through the application ORM.
- **UUID filename:** a random stored name that does not reveal the source filename or filesystem path.
- **HSTS:** a browser policy that tells clients to use HTTPS for the site.
- **Rate limit:** a maximum request frequency used to reduce abuse and accidental overload.
- **Health check:** a small endpoint/container probe used by Compose and deployment automation to detect a service that is not ready.
