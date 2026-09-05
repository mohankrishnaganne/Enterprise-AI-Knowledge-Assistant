# Production Deployment Runbook

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
