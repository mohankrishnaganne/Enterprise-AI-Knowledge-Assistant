"""Operational corpus: HR policy, incident process, on-call and compliance.

Fictional internal documentation for ACME Corp. Several documents deliberately share
vocabulary with the technical set (for example "escalation", "severity", "rotation") so
that metadata filtering has genuine work to do at retrieval time.
"""

DOCUMENTS: dict[str, str] = {
    "employee_onboarding.md": """# New Employee Onboarding

Onboarding at ACME runs for 30 days and is owned jointly by the hiring manager and the
People Operations team. The new joiner's buddy is assigned before the start date, never
after.

## Before day one

People Ops raises the equipment ticket at least 10 business days before the start date.
The standard engineering allocation is a 16-inch laptop with 32 GB of memory, an external
monitor, and a hardware security key. Non-engineering roles receive a 14-inch laptop with
16 GB. Requests outside the standard allocation need director approval.

IT provisions accounts the business day before the start date, never earlier, so that
credentials are not sitting unused. Accounts created include email, Slack, the identity
provider, and the HR system. Access to production systems is not granted at this stage.

## Week one

Day one is orientation: company overview, security training, benefits enrolment, and
hardware setup. Security training must be completed within the first 5 business days;
system access is suspended automatically if it is not.

Days two to five are team-local. Every engineer is expected to ship a small change to
production in their first week. This is a deliberate test of the onboarding path, not of
the individual: if a new joiner cannot ship in week one, the team's setup documentation
is treated as the defect.

## Weeks two to four

The new joiner shadows an on-call shift as an observer during week three. They do not
carry the pager. Observing is mandatory before joining a rotation.

Production access is granted at the end of week two, after security training is complete
and the manager has confirmed readiness in the access ticket. Access follows least
privilege: read-only first, write access only when the role demonstrably requires it.

## The 30-day review

At day 30 the manager and the new joiner hold a structured review covering role clarity,
team integration, and any blockers. People Ops collects anonymised feedback on the
onboarding process itself at the same point. The two conversations are kept separate on
purpose so that process criticism does not have to be delivered to one's own manager.

## Offboarding note

The reverse process is documented separately. Access revocation is triggered by the HR
system and completes within 4 hours of the termination record being created; it does not
wait for the manager to file a ticket.
""",
    "incident_response.md": """# Incident Response Process

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
""",
    "pto_policy.md": """# Paid Time Off Policy

ACME offers a defined PTO allowance rather than an unlimited policy, on the evidence that
unlimited policies reduce time actually taken.

## Allowance

Full-time employees accrue 25 working days of PTO per calendar year, accruing monthly at
2.083 days per month from the start date. Employees with more than 5 years of service
accrue 30 days. Part-time employees accrue pro rata.

Public holidays are additional and follow the employee's country of employment. ACME
observes a company-wide shutdown between 24 December and 1 January inclusive; this does
not consume PTO allowance.

## Carryover

Up to 5 unused days may be carried into the following year and must be used by 31 March.
Days beyond 5 are forfeited at year end. Carryover is not paid out except where local law
requires it, which currently applies to employees in California and in Germany.

## Requesting time off

Submit requests in the HR system. Requests of 5 days or fewer require manager approval
and should be submitted at least 2 weeks in advance. Requests longer than 5 days should
be submitted at least 4 weeks in advance and require both manager and director approval.

Managers are expected to approve or decline within 3 business days. An unanswered request
is not an approval.

## Minimum time off

Employees are required to take a minimum of 15 days per year. Managers are accountable
for their team meeting this floor; it appears in the manager's own performance review.
Anyone below 10 days used by 30 September is flagged to their manager and to People Ops
automatically.

## Sick leave

Sick leave is separate from PTO and is not capped. Absences of more than 3 consecutive
working days require a medical note. Sick leave is never deducted from PTO allowance,
including where an employee falls ill during booked PTO -- in that case the affected days
are returned to the PTO balance on production of a note.

## On-call interaction

PTO and on-call must not overlap. If a booked PTO period conflicts with a published
rotation, the rotation is changed, not the PTO. Swapping is the responsibility of the
team's on-call coordinator, not the individual going on leave.

## Parental leave

Parental leave is covered by a separate policy and is not drawn from PTO. In summary,
ACME provides 20 weeks fully paid for the primary caregiver and 12 weeks fully paid for
the secondary caregiver, available to all parents regardless of gender or route to
parenthood.
""",
    "oncall_rotation.md": """# On-Call Rotation

Every engineering team that owns a production service runs an on-call rotation. On-call
is a team responsibility, never an individual heroic one.

## Structure

Rotations are weekly, running Wednesday 10:00 UTC to the following Wednesday 10:00 UTC.
The handover happens at the start of the working day rather than at a weekend boundary,
so that a handover is never conducted by a tired person.

Each rotation has a primary and a secondary. The secondary is paged only if the primary
does not acknowledge within 5 minutes. A rotation requires a minimum of 6 engineers; a
team below that threshold cannot run its own rotation and must federate with an adjacent
team. This floor exists so that no engineer is on call more than one week in six.

## Expectations while on call

The primary must be reachable and able to reach a working internet connection within 15
minutes, at any hour. On-call engineers are not expected to be at a desk continuously.

On-call engineers are explicitly not expected to make progress on planned project work
during their rotation. Managers must not plan sprint capacity for an on-call engineer
beyond 40%. Where an on-call week is quiet, the surplus time goes to reliability work,
not to feature backlog.

## Compensation and time in lieu

On-call carries a stipend of 400 USD per week, or local equivalent, paid regardless of
whether any page occurred. Any page received between 22:00 and 07:00 local time grants
half a day of time in lieu; two or more such pages in one night grant a full day. Time in
lieu must be taken within 30 days and does not consume PTO allowance.

## Handover

The outgoing primary writes a handover note in the team channel covering open incidents,
degraded systems, deferred alerts, and anything expected to fire. A handover with no note
is not a handover. The incoming primary confirms receipt explicitly.

## Alert hygiene

Any alert that pages a human and turns out not to require human action is a defect. The
on-call engineer files it as such, and the owning team must either fix or delete the
alert within two weeks. Teams whose page volume exceeds 5 pages per rotation for three
consecutive rotations enter a mandatory reliability freeze: no feature work ships until
page volume is back under the threshold.

## Shadowing

New joiners observe one rotation before carrying the pager, as described in the
onboarding documentation. Shadowing is passive: the observer does not receive pages and
does not act.
""",
    "expense_policy.md": """# Expense and Travel Policy

ACME reimburses reasonable expenses incurred in the course of work. The policy is
deliberately short and relies on judgement rather than exhaustive rules.

## The principle

Spend company money as if it were your own, and as if the amount would be published
internally. If a purchase would be awkward to explain to a colleague, do not make it.

## Approval thresholds

Purchases up to 200 USD require no pre-approval; submit the receipt afterwards. Between
200 and 2,000 USD requires manager pre-approval in the expense system. Above 2,000 USD
requires director pre-approval. Above 25,000 USD requires the CFO and enters the
procurement process, which includes a security review for any vendor handling customer
data.

## Travel

Book through the corporate travel tool wherever possible; direct bookings are reimbursed
but generate reconciliation work. Economy class is standard. Premium economy is permitted
for flights with a scheduled duration over 6 hours, and business class for flights over
10 hours or where the traveller has a documented accessibility need.

Hotels should be booked at or below the city cap published in the travel tool. Where no
cap is published, 250 USD per night is the default ceiling.

Ground transport: use the cheapest reasonable option, but personal safety always
overrides cost. A taxi late at night is never questioned.

## Meals

Meals while travelling are reimbursed at actuals up to 75 USD per day, alcohol excluded.
Team meals require the host to be a manager and are capped at 60 USD per head.

## Home office

Every employee receives a one-time 750 USD home office allowance and a 45 USD monthly
internet stipend. The allowance refreshes every 3 years. Furniture purchased under the
allowance remains ACME property above 300 USD in value and is either returned or bought
out at depreciated value on departure.

## Learning and development

Each employee has an annual 1,500 USD learning budget covering courses, books, and
conference tickets. Conference travel is charged to the travel budget, not the learning
budget. The learning budget does not carry over between years.

## Submission

Submit expenses within 30 days of the spend. Claims older than 90 days require a written
exception from Finance. Reimbursement is paid in the next payroll cycle after approval.
""",
    "security_compliance.md": """# Security and Compliance Handbook

ACME holds SOC 2 Type II certification and is ISO 27001 certified. This handbook covers
the internal controls every employee is accountable for.

## Access control

Access follows least privilege and is granted through the identity provider only. Direct
credential sharing is prohibited without exception, including between members of the same
team and including read-only credentials.

Multi-factor authentication is mandatory on every system. Hardware security keys are
required for anyone with production access; TOTP applications are acceptable for
everyone else. SMS-based second factors are not permitted anywhere at ACME.

Production access is time-bound. Standing production write access does not exist;
engineers request elevation for a maximum of 8 hours through the access tool, stating a
reason, and the request is logged and reviewed weekly.

## Access reviews

Quarterly access reviews are run by the security team. Managers must confirm or revoke
every access grant for their reports within 10 business days of the review opening.
Unconfirmed grants are revoked automatically -- silence is treated as revocation, not as
approval.

## Data classification

Four levels apply:

- **Public** -- published material, marketing content.
- **Internal** -- default for everything not otherwise classified.
- **Confidential** -- customer lists, contracts, unreleased financials, source code.
- **Restricted** -- customer records, credentials, personal data, security findings.

Restricted data must never leave ACME-managed systems. It may not be pasted into
external tools, including AI assistants that are not on the approved vendor list.

## Device requirements

Company laptops have full-disk encryption, an endpoint agent, and automatic screen lock
at 5 minutes. Personal devices may access email and Slack through the managed profile
only, and never access production systems or Restricted data.

## Incident reporting

Report any suspected security incident immediately to `security@acme.example` or via
`/security-report` in Slack. Report on suspicion; do not investigate first and do not
wait for certainty. There is no penalty for a report that turns out to be benign, and
this is enforced deliberately.

Phishing simulations run monthly. Clicking a simulation results in a short training
module, not disciplinary action.

## Vendor management

Any vendor processing ACME or customer data requires a security review and a signed DPA
before use. This applies to free tiers and trials exactly as it applies to paid
contracts, which is the most commonly missed part of this policy.

## Retention

Customer records follow the retention period configured per dataset. Audit logs are
retained for 400 days. Backups are retained for 35 days and restore tests are performed
quarterly; a backup that has not been restore-tested is not considered a backup.
""",
    "remote_work_policy.md": """# Remote and Hybrid Work Policy

ACME is remote-first. Roles are advertised as remote unless there is a specific reason
they cannot be, and that reason is stated in the job description.

## Working location

Employees may work from anywhere within their country of employment without approval.
Working from another country requires People Ops approval in advance, because it creates
tax and employment law obligations for ACME. Approval is normally granted for stays up to
30 days per year; longer stays require a review by Legal and may require an employer of
record arrangement.

Employees must not work from a country subject to sanctions or where ACME has no legal
basis to employ. The current permitted list is maintained by People Ops.

## Core hours

Teams define their own core hours, being a window of at least 4 hours where the whole
team overlaps. Core hours are published in the team handbook page. Outside core hours,
availability is not expected and messages should not assume it.

Meetings are scheduled inside core hours. A meeting scheduled outside a participant's
core hours requires their explicit agreement, and recurring meetings outside core hours
are not permitted at all.

## Asynchronous default

Written communication is the default. Decisions made in a synchronous meeting must be
written up in the relevant channel or document within one business day, or they are not
considered decided. This is what makes it possible for someone in a different time zone
to disagree with a decision before it becomes load-bearing.

Documents are preferred over slide decks for anything requiring a decision.

## Office use

ACME maintains offices in London, Berlin and Austin. Office attendance is optional. Desks
are unassigned and booked through the office tool. Employees within 50 km of an office
may claim a commuting allowance on the days they attend, capped at 8 days per month.

## Team gatherings

Every team meets in person at least twice per year for a 3-day gathering. Attendance is
expected and travel is charged to the team's gathering budget rather than to the
individual's travel budget. Gatherings are for relationship building and planning, not
for routine work that could have been done remotely.

## Equipment and safety

The home office allowance in the expense policy applies to all remote employees. Where
local law requires a home workstation assessment, People Ops arranges it. Employees are
responsible for a working internet connection; the monthly stipend contributes to this.
""",
}
