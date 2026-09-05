# Product Roadmap

Rolling four-quarter view, reviewed monthly by the product council. Items are commitments
for the current quarter and directional beyond it.

## Q4 2025 -- committed

**Salesforce and NetSuite connectors.** The two most requested integrations and the most
cited competitive gap. Salesforce is in private beta with 6 design partners; NetSuite
follows 6 weeks later.

**Query result caching.** Repeat queries against unchanged partitions return from cache.
Expected to cut p50 dashboard latency by roughly 60% for the common case of a dashboard
polling on a fixed interval.

**Audit log export to customer object storage.** Currently Growth and Enterprise
customers can view audit logs but cannot export them to their own SIEM. This blocks a
recurring compliance requirement.

**EU data residency.** Full processing and storage within `eu-west-1` for customers who
require it. This is a prerequisite in most European public sector deals.

## Q1 2026 -- planned

**Self-hosted deployment for Growth.** Addresses the second most cited competitive gap.
Scope is a supported Kubernetes chart with a customer-managed control plane.

**Schema evolution without a new version.** Additive changes (new nullable columns)
should not require creating a new schema version. Backward compatibility rules are being
drafted with the data platform team.

**Materialised views.** Continuously maintained aggregates, targeting the dashboard use
case that query caching only partially addresses.

## Q2 2026 -- directional

Streaming exports to customer-owned sinks. Anomaly detection on ingested series. A
governance layer covering column-level access control and data lineage.

## Explicitly not planned

**Batch historical analytics at warehouse scale.** This is the segment where Northwind is
strong and where our architecture, optimised for recent data, is a poor fit. We will
continue to integrate with warehouses rather than compete with them.

**A visualisation product.** Customers use the BI tool they already have. Building one
would compete with our own integration partners.

**Per-byte-scanned pricing.** Repeatedly requested by procurement teams who are used to
it. Declined, because cost predictability is our primary competitive differentiator.
