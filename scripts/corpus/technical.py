"""Technical corpus: API docs, runbooks, architecture and schema references.

Content is fictional and describes "ACME Data Platform", a synthetic B2B SaaS product.
Facts here are deliberately specific (numbers, endpoint names, table names) so the
evaluation golden set can assert on them.
"""

DOCUMENTS: dict[str, str] = {
    "api_reference.md": """# ACME Data Platform REST API Reference

The ACME Data Platform exposes a versioned REST API at `https://api.acmedata.io/v2`.
All endpoints accept and return `application/json` encoded as UTF-8.

## Conventions

Every request must include an `X-ACME-Project` header naming the target project slug.
Requests without this header are rejected with `400 MISSING_PROJECT`. Timestamps are
returned as RFC 3339 strings in UTC. Pagination uses opaque cursors, never numeric
offsets, because the underlying tables are append-only and offsets drift under writes.

## Datasets

### POST /v2/datasets

Creates a dataset. The request body requires `name` (3-64 characters, lowercase
alphanumeric plus hyphens) and `schema_id`. Optional fields are `description`,
`retention_days` (default 90, maximum 3650) and `tags`. Returns `201` with the created
dataset object. Attempting to reuse a name within the same project returns
`409 DATASET_EXISTS`.

### GET /v2/datasets

Lists datasets. Supports `limit` (default 50, maximum 200), `cursor`, and `tag` filters.
The response envelope contains `items` and `next_cursor`; `next_cursor` is `null` on the
final page.

### DELETE /v2/datasets/{dataset_id}

Soft-deletes a dataset. The dataset remains queryable for 30 days in a `deleted` state
and is then purged permanently. Pass `?hard=true` to purge immediately; this requires the
`datasets:purge` scope and is irreversible.

## Ingestion

### POST /v2/datasets/{dataset_id}/records

Appends records. The body is a JSON array of up to 1000 objects, and the total payload
must not exceed 5 MB. Partial success is possible: the response returns `accepted` and
`rejected` arrays, where each rejected entry carries the zero-based `index` and a
`reason`. A `202` status means the batch was queued; records become queryable within
approximately 30 seconds.

### POST /v2/datasets/{dataset_id}/records:stream

Opens a chunked upload for large loads. Each line must be a single JSON object
(newline-delimited JSON). The stream may run for at most 15 minutes before the server
closes it with `504 STREAM_TIMEOUT`.

## Queries

### POST /v2/query

Executes a read-only SQL statement against one or more datasets in the project. The body
requires `sql` and optionally `parameters` for bound values. Statements are limited to a
60 second execution budget and 100,000 returned rows. Write statements (`INSERT`,
`UPDATE`, `DELETE`, `MERGE`) are rejected with `403 READ_ONLY_ENDPOINT`.

## Errors

Errors return a consistent body: `{"error": {"code": "...", "message": "...",
"request_id": "..."}}`. Always log `request_id` -- ACME Support cannot investigate an
incident without it. Codes in the `4xx` range are client errors and should not be
retried unchanged; `429` and `5xx` are retryable with exponential backoff.
""",
    "authentication.md": """# API Authentication and Authorization

ACME Data Platform supports two credential types: **API keys** for server-to-server
integrations and **OAuth 2.0** for applications acting on behalf of a user.

## API keys

API keys are issued per project from the console under Settings > API Keys. A key is
shown exactly once at creation and cannot be recovered afterwards; if it is lost, revoke
it and issue a new one. Keys are presented as a bearer token:

    Authorization: Bearer acme_live_XXXXXXXXXXXXXXXX

Keys are prefixed by environment: `acme_live_` for production and `acme_test_` for the
sandbox. Sandbox keys never touch production data and are rate limited independently.

### Rotation

Keys do not expire automatically. Policy requires rotation every 90 days. Two active
keys may exist per project simultaneously, which allows zero-downtime rotation: issue the
new key, deploy it, verify traffic has moved using the Key Usage panel, then revoke the
old key. Revocation takes effect within 60 seconds globally.

## OAuth 2.0

ACME implements the authorization code flow with PKCE. Public clients must use PKCE;
the `client_secret` flow is available only to confidential clients registered as such.

- Authorization endpoint: `https://auth.acmedata.io/oauth/authorize`
- Token endpoint: `https://auth.acmedata.io/oauth/token`

Access tokens are JWTs valid for 60 minutes. Refresh tokens are valid for 30 days and
are single-use: each refresh returns a new refresh token and invalidates the previous
one. Reusing a consumed refresh token is treated as a compromise indicator and revokes
the entire token family.

## Scopes

Scopes are granular and additive. The commonly used set is:

- `datasets:read` -- list and describe datasets
- `datasets:write` -- create and update datasets
- `datasets:purge` -- permanently delete datasets and records
- `records:write` -- append records
- `query:execute` -- run SQL queries
- `admin:members` -- manage project membership

`datasets:purge` and `admin:members` are considered privileged and cannot be granted to
sandbox keys.

## Failure modes

A missing or malformed `Authorization` header returns `401 UNAUTHENTICATED`. A valid
credential lacking the required scope returns `403 INSUFFICIENT_SCOPE`, and the error
message names the specific scope required. A revoked key returns `401 KEY_REVOKED`.
""",
    "rate_limits.md": """# Rate Limits and Quotas

Rate limits protect shared infrastructure and are enforced per project, not per API key.
Issuing additional keys does not increase your throughput.

## Limits by plan

| Plan | Requests/minute | Ingestion rows/day | Concurrent queries |
| --- | --- | --- | --- |
| Free | 60 | 100,000 | 2 |
| Starter | 600 | 5,000,000 | 8 |
| Growth | 3,000 | 50,000,000 | 25 |
| Enterprise | Negotiated | Negotiated | 100 |

Sandbox environments are fixed at 120 requests per minute on every plan.

## Headers

Every response carries the current limit state:

- `X-RateLimit-Limit` -- the ceiling for the current window
- `X-RateLimit-Remaining` -- requests left in the window
- `X-RateLimit-Reset` -- Unix epoch seconds when the window resets

When exhausted the API returns `429 RATE_LIMITED` along with a `Retry-After` header in
seconds. Clients must honour `Retry-After` rather than retrying immediately.

## Recommended client behaviour

Use exponential backoff with full jitter, starting at 1 second and capping at 60 seconds,
with a maximum of 5 attempts. Do not retry `4xx` responses other than `429`. The official
SDKs implement this policy by default; if you are writing a client by hand, replicate it.

Batch aggressively. A single `POST /v2/datasets/{id}/records` call carrying 1000 records
consumes one request against the rate limit, whereas 1000 single-record calls consume
1000. The most common cause of a customer hitting their limit is per-record ingestion in
a loop.

## Quota exhaustion

Exceeding the daily ingestion row quota returns `429 QUOTA_EXCEEDED` and, unlike a
transient rate limit, does not reset until 00:00 UTC. Quota consumption is visible in the
console under Usage, updated every 5 minutes. Growth and Enterprise plans can enable
overage billing, which allows ingestion to continue at 1.4x the per-row list price rather
than failing.
""",
    "deployment_runbook.md": """# Production Deployment Runbook

This runbook covers deploying the ACME Data Platform services to the production cluster.
It is the authoritative procedure; do not deploy by any other route.

## Preconditions

A deployment may proceed only when all of the following hold:

1. The change is merged to `main` and CI is green on that commit.
2. A staging soak of at least 2 hours has completed with no new error-rate alerts.
3. The deploy window is open. Windows are Monday to Thursday, 09:00-16:00 UTC.
   Friday deploys require VP Engineering approval recorded in the change ticket.
4. No Sev-1 or Sev-2 incident is currently open.

## Procedure

### 1. Announce

Post the intent in `#deploys` with the commit SHA, the services affected and a link to
the change ticket.

### 2. Canary

Roll out to the canary pool, which is 5% of production traffic:

    acmectl deploy --service ingest-api --sha <SHA> --stage canary

Hold the canary for a minimum of 15 minutes. Watch the Canary Health dashboard. The
canary is considered failed if the p99 latency rises above 400 ms, the 5xx rate exceeds
0.5%, or any new error signature appears in the log aggregator.

### 3. Full rollout

If the canary is healthy, proceed:

    acmectl deploy --service ingest-api --sha <SHA> --stage production

Rollout is progressive across three availability zones with a 10 minute soak between
zones. Total expected duration is 45 minutes.

### 4. Verify

Confirm the deployed SHA in every zone with `acmectl status --service ingest-api`. Run
the post-deploy smoke suite: `acmectl verify --suite post-deploy`. All 34 checks must
pass.

## Rollback

Rollback is always safe and is the default response to any doubt. Do not debug forward
during a rollout.

    acmectl rollback --service ingest-api

Rollback targets the previous known-good SHA and completes in approximately 4 minutes.
Note that rollback does **not** revert database migrations. Migrations are required to be
backward compatible for one release, which is what makes rollback safe; a migration that
breaks this rule must not be merged.

## Database migrations

Migrations run separately from service deploys, via `acmectl migrate --plan` then
`acmectl migrate --apply`. Always inspect the plan output first. Migrations that add a
non-nullable column without a default, drop a column still read by the running release,
or rewrite a table larger than 50 GB require a written plan reviewed by the data platform
team before they may be applied.
""",
    "system_architecture.md": """# Platform System Architecture

The ACME Data Platform is a multi-tenant system running on Kubernetes across three
availability zones in `us-east-1`, with an asynchronous replica in `eu-west-1` for
disaster recovery.

## Service topology

Four services make up the request path:

**edge-gateway** terminates TLS, authenticates the caller, applies rate limiting, and
routes to the appropriate backend. It is stateless and holds no customer data. It
consults an in-memory credential cache with a 30 second TTL, which is why key revocation
propagates within 60 seconds rather than instantly.

**ingest-api** accepts record batches, validates them against the dataset schema, and
writes them to the durable log. It acknowledges a batch only after the log write is
replicated to two zones.

**query-engine** plans and executes SQL. It reads from the columnar store and never from
the durable log directly. Query plans are cached for 10 minutes keyed by the normalised
statement text plus schema version.

**control-plane** owns projects, datasets, schemas, membership and billing state. It is
the only service that writes to the metadata database.

## Storage layers

The **durable log** is a partitioned append-only log retaining 7 days of raw records. It
is the system of record for recovery.

The **columnar store** holds query-optimised data in object storage, compacted from the
log. Compaction runs continuously with a target lag of 30 seconds, which is the source of
the documented "records queryable within approximately 30 seconds" behaviour.

The **metadata database** is a PostgreSQL cluster with one primary and two synchronous
replicas. It holds no customer records, only descriptions of them.

## Multi-tenancy and isolation

Tenants share compute but never share storage paths. Every object key is prefixed with
the project UUID, and the query engine injects a mandatory project predicate at plan time
that cannot be overridden by user SQL. Noisy-neighbour protection is handled by per-
project concurrency slots in the query engine rather than by hard resource partitioning.

## Failure and recovery

Loss of a single availability zone is transparent: the gateway sheds that zone and
capacity is restored by autoscaling within about 3 minutes. Loss of the entire `us-east-1`
region requires a manual failover decision by the incident commander; the documented
recovery point objective is 5 minutes and the recovery time objective is 4 hours.
""",
    "database_schema.md": """# Metadata Database Schema

The metadata database is PostgreSQL 16. It stores platform state only; customer records
live in the columnar store. All tables use UUID primary keys generated by the
application, never database sequences, so that identifiers are stable across restores.

## projects

Columns: `project_id` (UUID, PK), `slug` (text, unique), `display_name` (text),
`plan` (enum: free, starter, growth, enterprise), `region` (text),
`created_at` (timestamptz), `deleted_at` (timestamptz, nullable).

Soft deletion is used throughout. Any query touching this table must filter
`deleted_at IS NULL` unless it is an administrative recovery query.

## datasets

Columns: `dataset_id` (UUID, PK), `project_id` (UUID, FK to projects),
`name` (text), `schema_id` (UUID, FK to schemas), `retention_days` (integer, default 90),
`state` (enum: active, deleted, purging), `created_at`, `deleted_at`.

There is a unique constraint on `(project_id, name)` filtered to `deleted_at IS NULL`,
which is what produces the `409 DATASET_EXISTS` API error. An index on
`(project_id, state)` supports the list endpoint.

## schemas

Columns: `schema_id` (UUID, PK), `project_id` (UUID, FK), `version` (integer),
`definition` (JSONB), `created_at`.

Schemas are immutable. Editing a schema creates a new row with an incremented `version`;
existing datasets continue to reference the version they were created against. This is
why a schema change never breaks an in-flight ingestion.

## api_keys

Columns: `key_id` (UUID, PK), `project_id` (UUID, FK), `key_hash` (bytea),
`prefix` (text), `scopes` (text array), `last_used_at` (timestamptz),
`created_at`, `revoked_at` (timestamptz, nullable).

Only the Argon2id hash of the key is stored, never the key itself. `prefix` holds the
first 12 characters so the console can display a recognisable stub. `last_used_at` is
updated at most once per minute per key to avoid write amplification.

## memberships

Columns: `membership_id` (UUID, PK), `project_id` (UUID, FK), `user_id` (UUID),
`role` (enum: owner, admin, engineer, analyst, viewer), `created_at`.

A project must retain at least one `owner`; the application enforces this, as it cannot
be expressed as a database constraint. Removing the last owner returns
`409 LAST_OWNER`.

## Retention of the audit trail

`audit_events` is partitioned monthly and retained for 400 days, which satisfies the
SOC 2 requirement of one year plus a margin. Partitions older than the retention window
are detached and archived to object storage rather than dropped.
""",
    "sdk_quickstart.md": """# SDK Quickstart

Official SDKs are available for Python, TypeScript, Go and Java. They wrap the REST API,
implement the recommended retry policy, and handle cursor pagination transparently.

## Install

    pip install acme-data
    npm install @acme/data
    go get github.com/acmedata/acme-go

## Authenticate

The SDKs read `ACME_API_KEY` and `ACME_PROJECT` from the environment by default. Passing
them explicitly is supported but discouraged, as it invites hardcoded credentials.

    from acme_data import Client

    client = Client()  # reads ACME_API_KEY and ACME_PROJECT

## Create a dataset and append records

    dataset = client.datasets.create(
        name="web-events",
        schema_id=schema.id,
        retention_days=365,
    )

    result = client.records.append(dataset.id, rows)
    print(result.accepted_count, result.rejected)

`records.append` automatically splits an iterable of any size into batches of 1000 rows
and stays under the 5 MB payload ceiling. It returns an aggregate result across all
batches. Rejected rows are returned with their original index relative to the input
iterable, not the internal batch.

## Query

    rows = client.query.execute(
        "SELECT path, count(*) AS hits FROM web_events "
        "WHERE ts >= :since GROUP BY path ORDER BY hits DESC",
        parameters={"since": "2025-09-01T00:00:00Z"},
    )

Always use bound parameters. String-interpolating values into SQL is the single most
common source of injection reports we receive through the bug bounty programme.

## Pagination

Iterating a list endpoint follows cursors for you:

    for dataset in client.datasets.list(tag="production"):
        print(dataset.name)

Call `.page()` instead of iterating if you need explicit control over cursors.

## Timeouts and retries

The default request timeout is 30 seconds, except for `query.execute`, which uses 65
seconds to sit just above the server's 60 second execution budget. Retries follow
exponential backoff with full jitter, 5 attempts maximum. Override with
`Client(max_retries=..., timeout=...)`. Setting `max_retries=0` is appropriate inside a
job that has its own outer retry loop, to avoid multiplicative retry storms.
""",
}
