# Platform System Architecture

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
