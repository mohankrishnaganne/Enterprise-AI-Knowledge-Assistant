# Incident Response Process

This process applies to all production incidents affecting customer-facing systems. It is
owned by the Reliability team and reviewed quarterly.

## Severity definitions

**Sev-1** -- Complete outage of a customer-facing service, confirmed data loss, or an
active security breach. Any customer data exposure is automatically Sev-1 regardless of
scale.

**Sev-2** -- Major functional degradation affecting many customers, or a full outage of a
single non-critical subsystem. Ingestion delayed beyond 15 minutes is Sev-2.

**Sev-3** -- Minor degradation, elevated error rates within SLO, or an issue affecting a
single customer with a workaround available.

**Sev-4** -- Cosmetic or internal-only issues with no customer impact.

When in doubt, declare the higher severity. Downgrading later is cheap and routine;
discovering late that an incident was under-classified is expensive.

## Declaring an incident

Anyone at ACME may declare an incident. No approval is required and none should ever be
sought. Declare by running `/incident declare` in Slack, which creates a dedicated
channel, a timeline document, and pages the on-call engineer.

## Roles

The **Incident Commander** owns coordination and decisions. The IC does not debug. If the
person who declared the incident starts debugging, they must hand off the IC role first.

The **Communications Lead** owns customer-facing updates and the status page. This role is
mandatory for Sev-1 and Sev-2.

The **Operations Lead** performs the technical work.

For a Sev-3 one person may hold all three roles. For Sev-1 they must be three different
people.

## Escalation timelines

The on-call engineer acknowledges a page within 5 minutes. If unacknowledged, the alert
escalates to the secondary on-call, then after a further 5 minutes to the engineering
manager on the escalation rota.

Sev-1 requires an executive notification within 15 minutes of declaration, sent by the
Communications Lead to the VP Engineering and the VP Customer Success.

Status page updates are posted within 30 minutes of a Sev-1 or Sev-2 declaration and
then at least every 60 minutes until resolution.

## Resolution and review

An incident is resolved when customer impact has ended, not when the root cause is
understood. The IC declares resolution.

Every Sev-1 and Sev-2 requires a written postmortem published within 5 business days.
Postmortems are blameless: they describe systems and conditions, never individual fault.
Each postmortem produces action items with named owners and due dates, tracked to
completion by the Reliability team. Action items overdue by more than 30 days are
escalated to the VP Engineering in the monthly review.
