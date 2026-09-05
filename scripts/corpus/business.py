"""Business corpus: pricing, financials, roadmap, competition and support SLAs.

Two of these documents are rendered to PDF by ``scripts/generate_corpus.py`` so the PDF
ingestion path is genuinely exercised rather than merely claimed. They are marked in
``PDF_DOCUMENTS``.
"""

DOCUMENTS: dict[str, str] = {
    "pricing.md": """# Pricing and Packaging

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
""",
    "competitor_analysis.md": """# Competitive Landscape

Internal analysis, refreshed quarterly by Product Marketing. Confidential -- do not share
externally.

## Market position

ACME competes in the operational analytics segment: teams that need fast queries over
recent event data without operating a warehouse. We are not competing with general
purpose data warehouses on batch analytics over historical data, and positioning us there
loses deals.

## Northwind Analytics

Northwind is the incumbent and the most frequent competitor in Growth and Enterprise
deals. Strengths: mature ecosystem, broad connector library, established brand with data
teams. Weaknesses: per-byte-scanned pricing that makes costs unpredictable, and a
documented median ingestion-to-query lag of 4 to 6 minutes against our approximately 30
seconds.

Our winning argument is cost predictability. In competitive bake-offs the customer's own
query pattern is the strongest evidence; ask for it early rather than arguing on
theoretical pricing.

We lose to Northwind when the buyer already runs Northwind elsewhere in the organisation
and consolidation outweighs unit economics.

## Bluepeak

Bluepeak is the low-cost challenger, roughly 40% below our list price. Strengths: price,
simple onboarding. Weaknesses: no SSO below their top tier, no audit log export, 99.5%
SLA against our 99.95%, and a single-region architecture with no documented disaster
recovery.

We win Bluepeak deals on compliance requirements. We lose them in price-led evaluations
where the buyer has no regulatory driver. Discounting to match Bluepeak is not
authorised; the correct response is to disqualify or to move the conversation to
requirements.

## Build-it-yourself

The most common alternative overall is an in-house stack, typically Kafka plus a
columnar store. This is a credible choice for large engineering organisations. Our
argument is total cost of ownership: the median customer migrating from an in-house
stack reported 1.8 full-time engineers freed.

Do not disparage in-house builds in sales conversations. Buyers who built one are
usually proud of it, and the argument that lands is opportunity cost, not quality.

## Where we are weak

Connector coverage is our most cited gap, particularly the absence of native Salesforce
and NetSuite connectors. Both are on the roadmap. The second most cited gap is the lack
of a self-hosted option below the Enterprise tier.
""",
    "product_roadmap.md": """# Product Roadmap

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
""",
    "partner_program.md": """# Partner Programme

The ACME Partner Programme covers technology partners who build integrations and
solution partners who implement ACME for their clients.

## Tiers

**Registered** -- no revenue commitment. Access to partner documentation, a sandbox
project, and the partner Slack community. Self-service enrolment.

**Certified** -- requires two certified engineers and one published reference customer.
Adds co-marketing eligibility, a listing in the partner directory, and a 15% referral
commission on first-year contract value.

**Strategic** -- by invitation. Requires 250,000 USD in influenced annual revenue. Adds a
named partner manager, joint account planning, early roadmap access under NDA, and a 20%
referral commission.

## Certification

Engineer certification is a 4 hour online assessment covering ingestion design, schema
modelling, query optimisation and security configuration. It is free, and valid for 24
months. Recertification is a shorter delta assessment.

## Referral and resale

Referrals are registered in the partner portal and are protected for 90 days from
registration. A deal registered by two partners is awarded to whichever registered first,
with no exceptions, because arbitrating these disputes destroys trust in the programme
faster than any individual deal is worth.

Resale is available to Strategic partners only. Resellers receive a 25% margin on list
and own the billing relationship with the end customer. ACME retains the right to contact
the end customer directly on security and incident matters.

## Technology partners

Technology partners publishing a connector must meet the integration standards: OAuth 2.0
where the target system supports it, incremental sync rather than full reload, documented
rate limit handling, and a published support contact with a 2 business day response
commitment.

Connectors are reviewed by the ACME integrations team before listing. Review takes up to
15 business days. Listed connectors are re-reviewed annually and delisted if unmaintained.

## Support expectations

Partners receive support through the partner channel, with a 1 business day response
target for Certified and 4 business hours for Strategic. Partners must not route end
customer support requests through the partner channel; end customers use their own
support entitlement under the customer SLA.
""",
    "q3_2025_report.md": """# Q3 2025 Business Review

Prepared by Finance and Revenue Operations. Confidential -- internal distribution only.

## Headline results

Annual recurring revenue closed the quarter at 24.6 million USD, up 8.4% quarter over
quarter and 41% year over year. This is 2% ahead of the plan of 24.1 million USD.

Net revenue retention was 118%, down from 121% in Q2. The decline is attributable to
lower expansion in the Starter segment rather than to increased churn; gross logo churn
was 1.1% for the quarter, the lowest on record.

## Segment performance

Enterprise contributed 14.2 million USD of ARR, 58% of the total, from 61 customers. The
average Enterprise contract value rose to 233,000 USD from 214,000 USD, driven by
retention upsell rather than by new logo pricing.

Growth contributed 7.9 million USD from 1,320 customers. Starter contributed 2.5 million
USD from 2,110 customers. The Free tier ended the quarter with 18,400 active projects, of
which 3.1% converted to a paid plan within 90 days of signup.

## Costs and efficiency

Gross margin was 79%, up from 77%, largely from the storage compaction work that reduced
object storage spend by 14% on flat volume growth.

Sales and marketing spend was 9.1 million USD. Customer acquisition cost payback stood at
16 months, against a target of 18. Net magic number was 0.9.

Headcount ended at 214, up 19 in the quarter, with engineering at 96.

## Cash

Cash and equivalents closed at 61.3 million USD. Quarterly net burn was 3.4 million USD,
giving 18 quarters of runway at the current rate. The board's stated target is to reach
default alive by Q4 2026 without additional financing.

## Risks

The largest single-customer concentration is 4.1% of ARR, within the 5% board threshold.

Two Enterprise renewals totalling 1.6 million USD are at risk in Q4, both citing the
absence of a self-hosted option. This is the commercial driver behind prioritising
self-hosted deployment in Q1 2026.

Hiring in the EU is behind plan by 7 roles, which puts the Q4 EU data residency
commitment at moderate delivery risk.
""",
    "customer_support_sla.md": """# Customer Support Service Level Agreement

This SLA governs support entitlements by plan. It is contractual for Enterprise customers
and a published target for all other plans.

## Support channels

Free customers use the community forum only. Starter and Growth customers use email and
the in-console support widget. Enterprise customers additionally receive a dedicated
Slack Connect channel and a named technical account manager.

Telephone support is not offered on any plan. This is deliberate: written support
produces a searchable record and better handoffs across time zones.

## Priority definitions

**P1 -- Critical.** Production system unusable, or confirmed data loss. Requires the
customer to confirm business impact.

**P2 -- High.** Major feature unavailable or severely degraded, with no workaround.

**P3 -- Normal.** Functionality impaired with a workaround available, or a significant
question blocking implementation.

**P4 -- Low.** General questions, feature requests, documentation issues.

## Response targets

| Priority | Enterprise | Growth | Starter |
| --- | --- | --- | --- |
| P1 | 30 minutes, 24x7 | 4 business hours | 1 business day |
| P2 | 2 hours, 24x7 | 8 business hours | 2 business days |
| P3 | 1 business day | 2 business days | 3 business days |
| P4 | 3 business days | 5 business days | Best effort |

Response target means time to a substantive human reply, not an automated acknowledgement.
Business hours are 09:00 to 18:00 in the customer's registered primary time zone, Monday
to Friday, excluding local public holidays.

## Uptime commitment

Enterprise customers receive a 99.95% monthly uptime commitment on the query and
ingestion APIs. Growth receives a 99.9% published target without financial remedy.

Service credits for Enterprise are 10% of the monthly fee for uptime below 99.95%, 25%
below 99.5%, and 50% below 99.0%. Credits must be requested within 30 days of the
affected month and are applied against future invoices. Credits are the sole remedy for
availability failures.

Excluded from the uptime calculation: scheduled maintenance announced at least 5 business
days in advance and capped at 4 hours per quarter, customer-caused outages, and force
majeure events.

## Escalation

Any customer may request escalation by replying to their ticket with the word ESCALATE.
This routes the ticket to the support duty manager within one response cycle. Enterprise
customers may additionally escalate through their technical account manager, and to the
VP Customer Success for unresolved P1 issues older than 4 hours.
""",
}

# These two are additionally rendered to PDF so the PDF loader path is exercised.
PDF_DOCUMENTS: tuple[str, ...] = ("q3_2025_report.md", "customer_support_sla.md")
