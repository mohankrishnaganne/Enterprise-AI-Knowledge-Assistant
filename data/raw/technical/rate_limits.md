# Rate Limits and Quotas

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
