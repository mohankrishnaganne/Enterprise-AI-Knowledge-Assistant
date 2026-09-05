# Pricing and Packaging

ACME Data Platform is sold on four plans. Pricing is public and listed in USD; local
currency invoicing is available on annual contracts.

## Plans

**Free** -- 0 USD per month. Includes 1 project, 100,000 ingested rows per day, 60 API
requests per minute, 7 day retention, and community support. Intended for evaluation and
small side projects. No credit card required and no automatic conversion to a paid plan.

**Starter** -- 99 USD per month. Includes 3 projects, 5 million ingested rows per day,
600 requests per minute, 90 day retention, and email support with a next-business-day
response target.

**Growth** -- 499 USD per month. Includes 10 projects, 50 million ingested rows per day,
3,000 requests per minute, 365 day retention, SSO via SAML, audit log export, and support
with a 4 hour response target during business hours.

**Enterprise** -- custom pricing, typically starting at 40,000 USD annually. Unlimited
projects, negotiated throughput, up to 10 year retention, a dedicated support channel, a
named technical account manager, a 99.95% uptime SLA with financial credits, and optional
single-tenant deployment.

## Usage-based components

Ingestion above the plan allowance is billed at 0.35 USD per million rows on Growth and
0.28 USD per million rows on Enterprise. Starter does not support overage; ingestion
stops at the daily quota until the next UTC day. Overage must be explicitly enabled and
is off by default, so no customer is surprised by a bill.

Storage beyond the included retention is billed at 0.023 USD per GB-month.

Query compute is included on all plans up to the concurrency limits; there is no
per-query charge. This is a deliberate difference from competitors who bill per byte
scanned, and it is the most common reason cited in won deals.

## Discounts

Annual prepayment receives a 15% discount. Two-year prepayment receives 22%. Registered
non-profits and accredited academic institutions receive 50% off list on any plan.
Early-stage startups (under 5 million USD raised, under 3 years old) receive 12 months of
Growth at no cost through the ACME for Startups programme.

## Billing mechanics

Plans are billed monthly in advance; usage components are billed monthly in arrears.
Upgrades take effect immediately and are prorated. Downgrades take effect at the next
renewal date, never mid-cycle. Failed payments retry on days 3, 7 and 14; the account
moves to read-only on day 21 and data is retained for a further 60 days before deletion.
