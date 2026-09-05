# Security and Compliance Handbook

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
