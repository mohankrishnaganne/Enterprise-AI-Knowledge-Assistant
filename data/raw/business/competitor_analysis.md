# Competitive Landscape

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
