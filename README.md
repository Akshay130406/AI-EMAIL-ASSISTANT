# AI Email Assistant

The repository preserves the original Streamlit/Python prototype and contains
an independently runnable React frontend and FastAPI backend. Users can
optionally connect Gmail for bounded, read-only inbox synchronization. Draft
management and sending require a separate, explicitly granted Gmail permission
and user confirmation. Google Calendar access uses a separate authorization
flow and requires confirmation before event changes.

## Project structure

```text
backend/
  alembic/                # Versioned database migrations
  app/
    api/                  # Authentication and modular API routes
    core/                 # Runtime and production configuration checks
    database/             # SQLAlchemy engine and sessions
    models/               # Users, Google identities, sessions, and app data
    schemas/              # Validated API schemas
    services/             # Authentication and business logic
    main.py               # FastAPI application
    worker.py             # Durable background-job worker entry point
    seed.py               # Optional development-only sample seed
  tests/
  requirements.txt
  alembic.ini
frontend/
  src/
    components/
    contexts/             # Authentication and theme state
    layouts/
    pages/
    services/             # Central API client
    types/
  .env.example
  package.json
  vite.config.ts
app.py                     # Original Streamlit prototype; preserved
main.py                    # Original Python/Gmail prototype; preserved
```

## Requirements

- Node.js 22+ and npm
- Python 3.10+
- SQLite for local development/tests or PostgreSQL for deployment

## Google OAuth configuration

Create a **Web application** OAuth client in Google Cloud Console. Add the
frontend origin to **Authorized JavaScript origins** and the exact backend
callback URIs to **Authorized redirect URIs**:

```text
Local origin:   http://127.0.0.1:5174
Login callback: http://127.0.0.1:8002/api/auth/google/callback
Gmail callback: http://127.0.0.1:8002/api/integrations/gmail/callback
Calendar callback: http://127.0.0.1:8002/api/integrations/calendar/callback
```

Normal sign-in requests only `openid email profile`. Gmail connection is a
separate, authenticated flow and requests those identity scopes plus
`https://www.googleapis.com/auth/gmail.readonly`. Calendar is authorized in a
separate authenticated flow and requests identity scopes plus
`https://www.googleapis.com/auth/calendar.events` and
`https://www.googleapis.com/auth/calendar.calendarlist.readonly`. Neither
integration scope is requested during normal sign-in. Gmail linking is
deliberately restricted to the same stable Google
subject used for the signed-in application account; selecting another Google
identity is rejected rather than silently linking it.

Calendar is authorized separately and requests
`https://www.googleapis.com/auth/calendar.events` and
`https://www.googleapis.com/auth/calendar.calendarlist.readonly` together with
identity scopes to verify the selected Google account. Calendar permissions
are not requested during sign-in or Gmail authorization.

Gmail draft management is opt-in and separate from the initial read-only
connection. It requests
`https://www.googleapis.com/auth/gmail.compose` through an authenticated
authorization flow using the same callback URI. This permission supports draft
management and sending, but the application does not modify inbox messages.
Create, edit, and delete operations affect drafts only. Sending requires a
separate in-app confirmation. Send calls are never automatically retried; if
Gmail's response is ambiguous, the draft is marked `unknown` and cannot be sent
again automatically. Users should verify the message in Gmail before taking
further action.

Create `backend/.env` from the example only when it does not already exist;
update local settings without overwriting an existing environment file. Set
`frontend/.env` to `VITE_API_URL=http://127.0.0.1:8002` for this local setup.
Generate `SESSION_SECRET` with a secure random generator (at least 32
characters); use a different value in every environment. The configured
`GOOGLE_REDIRECT_URI`, `GMAIL_REDIRECT_URI`, and `CALENDAR_REDIRECT_URI` must
exactly match the Google Console callback URIs. Gmail and Calendar tokens are
encrypted at rest using AES-256-GCM.
Set `TOKEN_ENCRYPTION_KEY` to base64 encoding of exactly 32 random bytes and
set a unique `TOKEN_ENCRYPTION_KEY_ID`. Production startup fails closed if this
key is absent or invalid.

## Run locally

In the backend terminal:

```powershell
cd backend
if (!(Test-Path .venv)) { python -m venv .venv }
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8002
```

You can also start the backend from the repository root with:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8002
```

The root-level legacy `app.py` and `main.py` remain unchanged; the backend
entry point gives `backend/` import precedence so it cannot resolve the legacy
`app.py` in place of the FastAPI package.

In another terminal:

```powershell
cd frontend
if (!(Test-Path .env)) { Copy-Item .env.example .env }
npm install
npm run dev
```

Open `http://127.0.0.1:5174` and use this exact host consistently for local
OAuth and session cookies. Stop and restart Vite with Ctrl+C and the same
command. Vite is configured to fail if port 5174 is already occupied. Check
backend health, readiness, and docs on port 8002.

## Production settings

Configure these values through the hosting provider's secret/environment
settings; do not commit `.env` files:

- `APP_ENV=production`
- `DATABASE_URL`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- `GMAIL_REDIRECT_URI`, `CALENDAR_REDIRECT_URI`, `TOKEN_ENCRYPTION_KEY`,
  `TOKEN_ENCRYPTION_KEY_ID`
- Optional `TOKEN_ENCRYPTION_KEY_PREVIOUS` during key rotation and
  `GMAIL_SYNC_MAX_MESSAGES` (1–100; default 50)
- `SESSION_SECRET`
- `FRONTEND_URL`, `BACKEND_URL`, `ALLOWED_ORIGINS`
- `COOKIE_SECURE=true`, `COOKIE_SAMESITE=none` for a cross-site frontend/API
  deployment such as the default Vercel and Render hostnames

Production startup fails closed if required configuration is incomplete,
insecure, or inconsistent. Credentialed CORS accepts only the configured
origins. For browsers that block third-party cookies, use frontend and API
custom domains under the same site or a same-site reverse proxy. Configure
`GOOGLE_REDIRECT_URI` to the exact HTTPS backend callback registered in Google
Cloud Console.

Sessions use random opaque IDs in `Secure`/`HttpOnly` cookies, while only
keyed hashes are stored in the database. Session records expire after seven
days and are deleted on logout or rotated after sign-in. State and PKCE
transactions are one-use and expire after ten minutes. Mutating API requests
require both an allow-listed `Origin` and a synchronizer CSRF token returned by
`GET /api/auth/me`; the frontend keeps this token in memory only.
OAuth callback query strings are redacted before ASGI access logging so
authorization codes and state values are not written to application access logs.

Google identity is verified using Google's signed ID-token validation. User
identity is keyed by Google's stable `sub`; an existing email is linked only
when Google confirms it as verified and it has no conflicting Google identity.
Sign-in tokens are used transiently and discarded. Gmail and Calendar tokens
are persisted only in encrypted form. The default Gmail permission is
read-only; compose
access is only added after a separate user authorization.
Integration tokens use AES-256-GCM with unique random nonces and account/token-type
associated data. Back up the current encryption key separately from the
database in an access-controlled secret manager; losing both the active and
backup keys makes stored Gmail and Calendar tokens unrecoverable and requires
users to reconnect.
For rotation, deploy the new key as `TOKEN_ENCRYPTION_KEY` with a new key ID
and retain old keys in `TOKEN_ENCRYPTION_KEY_PREVIOUS` as
`key-id:base64-key` entries. Do not remove an old key until all credentials
encrypted under it have been re-encrypted or the corresponding users have
reconnected. Credentials are re-encrypted lazily when used; keep previous keys
until all accounts have been accessed or reconnected. Key rotation and backups
are operational responsibilities; there is no bulk re-encryption command.
`SESSION_SECRET` is a server-side HMAC key: use a distinct high-entropy value
per environment, and rotate it knowing that active sessions and OAuth flows
will be invalidated.

## Vercel and Render deployment

The frontend includes a Vercel SPA rewrite at `frontend/vercel.json`. Create a
Vercel project with `frontend` as its root directory, use `npm run build` as
the build command and `dist` as the output directory. Set `VITE_API_URL` to
the HTTPS base URL of the deployed FastAPI service.

`render.yaml` describes separate FastAPI web and durable-job worker services.
Applying the blueprint creates two Render Starter services and may incur
hosting charges. Configure the `mailmind-production` environment group with
the actual managed PostgreSQL URL, OAuth client credentials, random
session/encryption keys, deployed frontend/backend URLs and exact allowed
frontend origin. The blueprint does not create a database; create one
separately only after approving its cost, then use its internal connection URL
for services in the same Render region. Production startup rejects SQLite.
`BACKEND_URL` must match the host used by all three Google OAuth callback URLs.
The web service applies Alembic migrations in its release command; the worker
uses the same environment group and runs `python -m app.worker`.

Set the Vercel `VITE_API_URL` after the Render web service is created. Add the
deployed frontend origin and HTTPS callback URLs to Google Cloud Console.
Although `COOKIE_SECURE=true` and `COOKIE_SAMESITE=none` are configured for
cross-origin hosting, browsers may block third-party cookies across default
`vercel.app` and `onrender.com` domains. A frontend/API custom-domain pair under
the same site or a same-site reverse proxy is recommended. No live deployment
or production database was created as part of this change.

### Production setup checklist

1. In Google Cloud, create or select a project, enable the Gmail API and Google
   Calendar API, and configure an OAuth consent screen as an External app if
   users outside your Workspace will sign in. Add the app name, support and
   developer contact addresses, homepage, privacy policy, terms of service,
   and verified authorized domain(s). Use a Web application OAuth client.
   Register these exact HTTPS redirect URIs, replacing the host with the
   deployed `BACKEND_URL`:
   - `{BACKEND_URL}/api/auth/google/callback`
   - `{BACKEND_URL}/api/integrations/gmail/callback`
   - `{BACKEND_URL}/api/integrations/calendar/callback`
   The backend performs the OAuth redirects, so do not put client secrets in
   Vercel or the browser. The implementation requests identity scopes
   `openid email profile`, Gmail read scope
   `https://www.googleapis.com/auth/gmail.readonly`, separate Gmail compose
   scope `https://www.googleapis.com/auth/gmail.compose`, and Calendar scopes
   `https://www.googleapis.com/auth/calendar.events` and
   `https://www.googleapis.com/auth/calendar.calendarlist.readonly`.
   Keep the app in Testing with explicitly added test users while validating.
   Before general availability, follow Google's current OAuth verification
   and data-use requirements for the requested sensitive scopes; Testing-mode
   refresh-token restrictions can interrupt long-running tests.
2. Create a managed PostgreSQL database only after reviewing the provider's
   current plan, region, storage, backup, and retention charges. Put its
   internal connection URL in Render's `DATABASE_URL`; do not use SQLite or
   expose a database URL to Vercel. The Render web service runs
   `alembic upgrade head` as its release command before starting. For an
   existing database, take and verify a restorable backup first, then inspect
   the migration history and run the release command once; do not run the
   migration concurrently from the web and worker services.
3. Configure the Render environment group with the required production values:
   `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REDIRECT_URI`, `GMAIL_REDIRECT_URI`, `CALENDAR_REDIRECT_URI`,
   `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY_ID`,
   `FRONTEND_URL`, `BACKEND_URL`, and `ALLOWED_ORIGINS`. Also configure
   `TOKEN_ENCRYPTION_KEY_PREVIOUS` when rotating keys and `GEMINI_API_KEY` to
   enable Gemini. Generate independent high-entropy session and 32-byte
   base64 encryption keys; keep backups of the encryption key outside the
   database. Use exact HTTPS origins/URLs with no trailing slash for the
   origin variables. `render.yaml` includes a web service, a worker service,
   and `/api/ready` as the health check; the worker itself enqueues due
   automations and processes jobs, so there is no separate scheduler service.
4. Configure Vercel with root `frontend`, build command `npm run build`, output
   `dist`, and `VITE_API_URL` set to the Render API base URL. Set the value for
   each Vercel environment deliberately; use a separate staging backend and
   database for Preview deployments rather than pointing previews at
   production. Keep `ALLOWED_ORIGINS` restricted to the exact production
   frontend origin. Prefer custom frontend and API domains under the same
   site to reduce cross-site cookie restrictions.
5. Before enabling real users, verify login, Gmail read-only sync, AI responses,
   and Calendar reads using a dedicated Google test account. Test draft sending
   and Calendar writes only after a separate explicit confirmation for each
   real external action. Confirm logs contain no tokens, message bodies, or
   secrets; verify database restore procedures and worker/job monitoring.

The Render blueprint currently defines two Starter compute services but no
database, and no services have been deployed by this audit. Actual charges
depend on current Render plans, managed database size/backups/region, Vercel
usage and plan, Gemini usage, and any domain or monitoring services. Check
provider pricing before creating resources; no live integration or billing
verification has been performed.

## Gemini AI features

Set `GEMINI_API_KEY` on the backend only. Optional controls are
`GEMINI_MODEL` (default `gemini-2.5-flash`), `GEMINI_TIMEOUT_SECONDS` (25),
`GEMINI_MAX_OUTPUT_TOKENS` (1200), `GEMINI_MAX_INPUT_CHARS` (16000), and
`AI_USER_REQUESTS_PER_MINUTE` (12). A missing or invalid key disables AI
operations with an explicit service-unavailable response; the app does not
silently substitute demo output.

Authenticated AI endpoints provide email classification, email/thread
summaries, editable writing/rewrite/reply suggestions, a Gmail-grounded
copilot, and dashboard insights. Email intelligence only accepts synchronized
Gmail records owned by the signed-in user and requires an active Gmail
connection. Copilot retrieves a bounded subset of that user's synchronized
mail; it does not search Gmail directly. AI operations never write or send to
Gmail, and generated text is never applied automatically.

Gemini receives the submitted writing text, bounded email excerpts, or selected
Calendar event context when an AI operation is explicitly requested. Do not send sensitive messages unless
you accept Google's applicable API data-handling terms. Email content is
passed as untrusted data separately from system instructions, outputs are
schema-validated, and source evidence/references are checked where supported.
Classification and summary responses are cached in process for five minutes
using content-derived keys; per-user request limits are also process-local.
For multi-worker deployments, add a shared rate-limit/cache backend before
relying on those limits as a billing control. A single model request is made
without automatic retries to avoid duplicate charges.

## API and database

- Public health check: `GET /api/health`
- Authentication: `GET /api/auth/google`, `GET /api/auth/google/callback`,
  `GET /api/auth/me`, `POST /api/auth/logout`
- Gmail: `GET /api/integrations/gmail/status`,
  `POST /api/integrations/gmail/connect` (CSRF-protected),
  `POST /api/integrations/gmail/compose/connect` (separate compose authorization),
  `GET /api/integrations/gmail/callback`,
  `POST /api/integrations/gmail/sync`,
  `DELETE /api/integrations/gmail/disconnect`
- Gmail drafts: `GET/POST /api/integrations/gmail/drafts`,
  `GET/PUT/DELETE /api/integrations/gmail/drafts/{draft_id}`,
  `POST /api/integrations/gmail/drafts/{draft_id}/send` (requires an explicit
  confirmation payload), and `GET /api/integrations/gmail/drafts/{draft_id}/send-status`
- Calendar: `GET /api/integrations/calendar/status`,
  `POST /api/integrations/calendar/connect`,
  `GET /api/integrations/calendar/callback`,
  `GET /api/integrations/calendar/calendars`,
  `GET /api/integrations/calendar/events/upcoming`,
  `GET /api/integrations/calendar/events/{event_id}`,
  `POST /api/integrations/calendar/events`,
  `PUT/DELETE /api/integrations/calendar/events/{event_id}`,
  `POST /api/integrations/calendar/events/conflicts`,
  `POST /api/integrations/calendar/availability`,
  `POST /api/integrations/calendar/assistant`,
  `DELETE /api/integrations/calendar/disconnect`
- AI: `POST /api/ai/classify/{email_id}`,
  `POST /api/ai/summarize/{email_id}`,
  `POST /api/ai/summarize-thread/{thread_id}`,
  `POST /api/ai/write`, `POST /api/ai/rewrite`,
  `POST /api/ai/reply-suggestion/{email_id}`,
  `POST /api/ai/copilot`, `GET /api/ai/insights`
- Automation/jobs: `GET/POST /api/automations`,
  `PATCH/DELETE /api/automations/{automation_id}`,
  `POST /api/automations/{automation_id}/run`,
  `GET /api/jobs`, `POST /api/jobs/{job_id}/cancel`,
  `GET /api/notifications`, `PATCH /api/notifications/{notification_id}`
- Analytics: `GET /api/analytics/overview?period_days=7` (7–90 days)
- Email list/detail routes return Gmail-backed data after a Gmail identity is
  connected; otherwise they return only sample data. Inbox messages are
  read-only; draft actions are separately scoped and synchronized. Inbox
  synchronization is bounded (default 50, maximum 100 messages per
  request), deduplicated, and uses Gmail history IDs for incremental updates.
  Expired history IDs trigger bounded recovery; synchronization never removes
  local rows based on incomplete Gmail results. Email body text is displayed
  as text; stored HTML is sanitized and never rendered as raw markup.
- The Sent view contains Gmail messages confirmed by a successful send or
  later synchronization. The sending draft is removed from the active draft
  list and its final status remains available to its owner.
- Data routes require a valid session and remain scoped to that user.
- Durable automation jobs are processed by a separate worker; scheduled
  automations are disabled until enabled. Job attempts, queue size and manual
  runs are bounded, and Gmail synchronization remains read-only. Analytics use
  persisted user-scoped messages and identify whether the displayed data is
  Gmail-backed or sample data; unsupported response-rate/productivity metrics
  are intentionally omitted.
- OpenAPI documentation: `http://127.0.0.1:8002/docs`
- Apply schema changes explicitly with `alembic upgrade head`; application
  startup does not run migrations.

Optional fictional sample data can be loaded in development only:

```powershell
$env:APP_ENV = "development"
$env:DEV_USER_EMAIL = "developer@example.test"
python -m app.seed
```

The seed is repeatable and contains only fictional `.test` addresses. To use
seeded data after authentication, configure `DEV_USER_EMAIL` to the same
verified Google email used for local sign-in.

## Validation

```powershell
cd backend
python -m pytest
alembic check
```

```powershell
cd frontend
npm test
npm run build
```

## Credentials and prototype preservation

Never commit `.env` secrets, Google OAuth credentials, service-account files,
tokens, database files, virtual environments, or dependency directories.
`credentials.json` and `libraries.env` are ignored. If either contained real
credentials in a previous commit, remove it from Git history as appropriate
and rotate the credential. The original `app.py` and `main.py` are untouched.
