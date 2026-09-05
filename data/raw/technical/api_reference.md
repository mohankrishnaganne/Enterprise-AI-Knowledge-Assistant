# ACME Data Platform REST API Reference

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
