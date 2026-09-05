# SDK Quickstart

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
