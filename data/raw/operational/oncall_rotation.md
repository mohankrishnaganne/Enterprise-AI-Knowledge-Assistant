# On-Call Rotation

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
