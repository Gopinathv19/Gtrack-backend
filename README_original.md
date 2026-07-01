# Gtrack — Multi-Tenant Asset Tracking API

A production-ready **FastAPI** backend for a multi-tenant asset tracking system.
Designed to integrate with **Supabase Postgres** and uses **SQLAlchemy 2.x** ORM
+ **Pydantic v2** schemas, JWT auth with refresh-token rotation, RBAC, invite
workflow, state-machine validated movements, optimistic concurrency, audit
logging, and rate limiting.

## Stack

| Layer        | Tech                                  |
| ------------ | ------------------------------------- |
| Framework    | FastAPI 0.115                         |
| ORM          | SQLAlchemy 2.0 (typed Mapped/PG UUID) |
| Schemas      | Pydantic v2 + pydantic-settings       |
| DB           | Supabase Postgres (psycopg2/asyncpg)  |
| Auth         | python-jose (JWT) + passlib (bcrypt)  |
| Migrations   | Alembic                               |
| Rate Limit   | slowapi                               |
| Integration  | supabase-py (service role client)     |

## Project Layout

```
app/
├── api/
│   ├── deps.py              # auth/RBAC/db deps
│   └── v1/
│       ├── router.py
│       └── endpoints/       # auth, invites, orgs, instances, groups,
│                              users, locations, assets, sacks
├── core/
│   ├── config.py            # pydantic-settings (env)
│   ├── security.py          # JWT + password hashing
│   └── supabase_client.py   # supabase-py wrapper
├── db/
│   ├── base_class.py
│   └── session.py
├── models/
│   ├── enums.py             # status/action enums + transition maps
│   └── models.py            # SQLAlchemy ORM models
├── schemas/                 # Pydantic request/response models
├── services/state_machine.py
└── main.py
alembic/                     # migrations
supabase/rls_policies.sql    # row-level security policies
scripts/seed_roles.py        # seed RBAC roles
```

## Quick Start

```bash
# 1. Install deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# edit .env to point DATABASE_URL at your Supabase Postgres
# (Settings -> Database -> Connection string)

# 3. Run migrations (or let dev mode auto-create)
alembic revision --autogenerate -m "initial"
alembic upgrade head

# 4. Apply RLS policies (optional but recommended in Supabase)
psql "$DATABASE_URL" -f supabase/rls_policies.sql

# 5. Seed roles
python -m scripts.seed_roles

# 6. Run the server
uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs>

## Multi-Tenancy

- Every tenant-scoped table has an `organization_id` FK.
- The JWT carries `org_id` as a custom claim; deps automatically filter
  queries by `current_user.organization_id`.
- `supabase/rls_policies.sql` adds defense-in-depth Postgres RLS policies
  reading the same claim, so even ad-hoc SQL is tenant-isolated.

## Authentication Flow

1. `POST /api/v1/auth/login` → `{access_token, refresh_token}`
2. Send `Authorization: Bearer <access_token>` on every request.
3. When access token expires (15 min default), call
   `POST /api/v1/auth/refresh` with the refresh token (rotated on use).
4. `POST /api/v1/auth/logout` revokes the refresh token.

Refresh tokens are stored hashed (SHA-256) in the `refresh_tokens` table and
rotated on every refresh.

## RBAC

Built-in roles (`scripts/seed_roles.py`):

| Role               | Capabilities                              |
| ------------------ | ----------------------------------------- |
| `ORG_ADMIN`        | Manage org/instances/groups/users/roles   |
| `STORE_MAINTAINER` | Create/pack assets, manage sacks          |
| `SHIFT_PERSON`     | Pickup / deliver sacks                    |
| `SYSADMIN`         | Close sacks (receive assets)              |
| `AUDITOR`          | (future) Read-only                        |

Roles are scoped per **group** through the `user_roles(user_id, role_id, group_id)`
join. Use `require_roles(...)` and `require_roles_in_group(...)` dependencies.

## Invite Workflow

```
POST   /api/v1/invites                  # OrgAdmin creates invite
POST   /api/v1/invites/accept?token=... # Invitee accepts and creates account
POST   /api/v1/invites/{id}/resend
DELETE /api/v1/invites/{id}             # revoke
```

Invites are time-limited (`INVITE_EXPIRE_HOURS`, default 72h), one-time use,
and create the `users` row + `user_roles` assignment atomically.

## Asset Lifecycle

```
CREATED → PACKED → IN_TRANSIT → DELIVERED → RECEIVED
             ↘ DAMAGED / LOST (terminal)
```

```
Sack: CREATED → PICKED_UP → IN_TRANSIT → DELIVERED → CLOSED
```

Transitions are enforced server-side (`app/services/state_machine.py`).
Invalid transitions return **409 Conflict**.

Each transition writes an `asset_movements` / `sack_movements` row for full
audit history.

## Optimistic Concurrency

`assets` and `sacks` use SQLAlchemy's `version_id_col`. Patch requests may
also pass the last-seen `updated_at`; mismatch returns 409.

## Rate Limiting

`slowapi` enforces a default `RATE_LIMIT_PER_MINUTE` (100). 429 responses
include `Retry-After` headers.

## Supabase Connection Strings — which one do I use?

Supabase exposes **three** different connection URLs for the same database.
Pick based on _where_ and _how_ you connect:

| Method                | Host                                              | Port | Use it when…                                                                                  |
| --------------------- | ------------------------------------------------- | ---- | --------------------------------------------------------------------------------------------- |
| **Direct connection** | `db.<project-ref>.supabase.co`                    | 5432 | Long-lived servers (VMs, your own backend) on a static IP. Highest perf, fewest hops. **IPv6** only on the free tier. |
| **Session pooler**    | `aws-1-<region>.pooler.supabase.com`              | 5432 | Long-lived servers that need **IPv4** or are behind a NAT. **Recommended for this FastAPI app.** Behaves like a real Postgres session. |
| **Transaction pooler**| `aws-1-<region>.pooler.supabase.com`              | 6543 | Short-lived/serverless functions (Vercel, Lambda, Cloudflare). Each transaction is on a fresh pooled connection — no session state, no prepared statements. |

For this backend, use the **Session pooler** URI you already copied:

```
postgresql://postgres.vzggfomfrabfpzjlpnvy:[YOUR-PASSWORD]@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres
```

…and convert it to a SQLAlchemy URL by:

1. Changing the scheme from `postgresql://` to `postgresql+psycopg2://`
2. Appending `?sslmode=require` (Supabase enforces SSL)
3. URL-encoding any special chars in the password (e.g. `@` → `%40`)

So your `.env` becomes:

```env
DATABASE_URL=postgresql+psycopg2://postgres.vzggfomfrabfpzjlpnvy:MyP%40ss@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres?sslmode=require
```

### Why are there two URLs (`DATABASE_URL` and `ASYNC_DATABASE_URL`) in the example?

Only because SQLAlchemy uses a **different driver** for sync vs async I/O:

- `postgresql+psycopg2://…` → blocking driver, used by `Session`/`create_engine` (what this app uses today).
- `postgresql+asyncpg://…` → non-blocking driver, used by `AsyncSession`/`create_async_engine`.

This codebase only uses the sync engine, so **you only need `DATABASE_URL`**.
You can leave `ASYNC_DATABASE_URL` blank/commented unless you later add async endpoints.

### Common gotchas

- **`connection refused` on `localhost:5432`** → `.env` not loaded or the variable is still the default. Make sure the file is named `.env` (not `.env.example`) and lives at the repo root.
- **`password authentication failed`** → password not URL-encoded.
- **`could not connect to server: Network is unreachable`** → you're on IPv4-only and tried the direct host. Use the **Session pooler** URL instead.
- **`SSL connection is required`** → add `?sslmode=require`.

## What goes in the `SUPABASE_*` env vars?

These are all **optional** — they only matter if you want this FastAPI
backend to talk to Supabase's **Auth / Storage / Admin** APIs (not just
its Postgres database). If you only use Supabase as a Postgres host
(via `DATABASE_URL`), leave all four blank.

All four values come from:
**Supabase Dashboard → Project Settings → API**

| Variable                    | What it is                                                                 | Sensitivity                                | When you need it                                                                                  |
| --------------------------- | -------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `SUPABASE_URL`              | Your project's REST base URL: `https://<project-ref>.supabase.co`           | Public                                     | Whenever you call any Supabase API from the backend.                                              |
| `SUPABASE_ANON_KEY`         | "anon public" API key. Subject to Row-Level-Security.                       | Public-safe (also shipped to browsers).    | Almost never on the backend — only if you want to act as an anonymous user. Listed for completeness. |
| `SUPABASE_SERVICE_ROLE_KEY` | "service_role" API key. **Bypasses RLS**. God-mode.                         | **Secret** — server-only, never to clients.| If the backend should create Supabase Auth users, send magic links, reset passwords, upload to Storage with admin powers, etc. Used by `app/core/supabase_client.py::get_supabase()`. |
| `SUPABASE_JWT_SECRET`       | HS256 secret used to sign Supabase-issued user JWTs.                        | **Secret**.                                | Only if your **frontend** signs in via Supabase Auth and forwards the Supabase JWT to this API — then we verify it with `verify_supabase_jwt()`. |

### Pick your scenario

- **Scenario A — Postgres only (simplest)**
  You use this app's own `/auth/login` + JWT system; Supabase is just the DB.
  Set `DATABASE_URL`. Leave all four `SUPABASE_*` blank.

- **Scenario B — Backend triggers Supabase Auth admin actions**
  e.g. you want the backend to programmatically create users, send invite
  emails through Supabase, or upload files to Storage.
  Set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`.

- **Scenario C — Single sign-on via Supabase Auth**
  Your frontend logs in with Supabase Auth and sends the resulting JWT
  here. You want the API to trust those tokens.
  Set `SUPABASE_URL` + `SUPABASE_JWT_SECRET`.
  (Scenarios B and C can be combined.)

### Security note

`SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_JWT_SECRET` are **secrets**.
Never commit them, never expose them to the browser. Treat them like a
database root password.

## Supabase Integration Notes


You can integrate this backend with Supabase in two main ways:


1. **Use Supabase only as the Postgres database**
   Point `DATABASE_URL` at your Supabase Postgres. The FastAPI app handles
   auth itself (its own JWT). This is what the included endpoints do.

2. **Use Supabase Auth as the identity provider**
   Have your frontend log in via Supabase Auth, forward the Supabase JWT,
   and verify it with `app.core.supabase_client.verify_supabase_jwt`.
   The `users.supabase_user_id` column is provided to link Supabase Auth
   users to your domain users.

For administrative tasks (creating users in Supabase Auth, sending magic
links, etc.) use `app.core.supabase_client.get_supabase()` which returns a
service-role client.

## Webhook Events (planned)

Hook points are in place for emitting webhooks on:
`asset.created`, `asset.packed`, `asset.delivered`, `asset.received`,
`sack.created`, `sack.picked_up`, `sack.delivered`, `sack.closed`.

## License

MIT (see `LICENSE`).
