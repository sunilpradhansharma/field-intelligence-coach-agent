# Feature Specification: Morning Coaching Brief (MVP)

**Feature Branch**: `001-morning-coaching-brief`

**Created**: 2026-06-07

**Status**: Draft

**Input**: User description: "Build the first version (MVP) of an assistant that helps district managers prepare for coaching their sales representatives and make better, fairer decisions about where to spend their limited field time."

## Overview

A district manager (DM) opens the assistant on the morning of a field ride and, in a
few minutes, gets one clear **morning coaching brief** that prepares them for the
pre-ride business conversation with a rep. The brief answers: who to ride with and
why, what to coach, what happened last time, which accounts/HCPs matter and how the
business is doing, and how to open the conversation. Every suggestion shows its reason
and the data behind it. The assistant only suggests — the DM always decides.

This MVP uses synthetic data only and scopes every view to the user's own territory.

## Clarifications

### Session 2026-06-07

- Q: Which business signals should drive the MVP rep "needs attention" ranking? → A: The four named signals — declining share, low call activity in key accounts, missed coaching follow-up, and business opportunity/risk — combined with transparent, explainable weighting shown to the user.
- Q: How should SC-004/SC-005 ("more consistent/complete preparation") be made measurable? → A: Define a fixed checklist rubric covering the 5 brief sections and score preparation for completeness/consistency against it.
- Q: What is the regional business director's (RBD) scope in this MVP? → A: Read-only, region-scoped access to the same DM briefs (all districts in their region); no aggregation/roll-up.
- Q: What size/shape should the synthetic dataset target? → A: Small realistic district — ~8–12 reps per district, ~15–30 accounts/HCPs per rep, 2–3 prior coaching sessions for most reps.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See who to ride with and why (Priority: P1)

On the morning of a field ride, the DM opens the assistant and sees a short, ranked
list of reps on their team who most need attention today. Each rep in the list shows a
clear, plain-language reason (e.g., declining share, low call activity in key accounts,
a missed coaching follow-up, or a notable business opportunity or risk). The DM uses
this to choose which rep to ride with.

**Why this priority**: This is the entry point and the core "equal to fair" decision.
Without a reasoned ranking, the DM has no starting point and the assistant delivers no
value. It is independently useful even if no other section exists.

**Independent Test**: Load a synthetic district, open the brief, and confirm a ranked
list of reps appears where every rep has at least one visible, data-backed reason for
their position. Verify a DM sees only reps in their own district.

**Acceptance Scenarios**:

1. **Given** a DM with a district of synthetic reps, **When** they open the morning
   brief, **Then** they see a ranked list of reps who need attention, ordered by need.
2. **Given** the ranked list, **When** the DM views any rep, **Then** at least one
   clear reason and the supporting data signal(s) are shown for that rep's ranking.
3. **Given** a DM signed in, **When** the list is generated, **Then** it contains only
   reps within that DM's district and no reps from other districts.
4. **Given** two reps with identical business signals, **When** the list is ranked,
   **Then** the ranking is explainable and based only on stated business signals (no
   hidden ordering).

---

### User Story 2 - Know what to coach this rep on (Priority: P2)

Having chosen a rep, the DM sees 1-3 suggested coaching focus areas for that rep
(e.g., closing new therapy starts, using approved assets, better account
prioritization). Each focus area shows the reason behind it and the data that supports
it.

**Why this priority**: Turns "who" into actionable "what," directly raising coaching
quality and consistency. Valuable on its own once a rep is selected, but depends on
having a rep in focus (P1).

**Independent Test**: Select a synthetic rep and confirm 1-3 coaching focus areas
appear, each with a visible reason tied to that rep's data.

**Acceptance Scenarios**:

1. **Given** a selected rep, **When** the DM views coaching suggestions, **Then**
   between 1 and 3 focus areas are shown.
2. **Given** a coaching focus area, **When** the DM views it, **Then** its reason and
   supporting data are shown.
3. **Given** a rep with no notable gaps in the synthetic data, **When** suggestions are
   generated, **Then** the assistant clearly states there are no high-priority focus
   areas rather than inventing one.

---

### User Story 3 - Recall what happened last time (ride-along prep) (Priority: P2)

For the selected rep, the DM sees prior coaching notes, the actions both sides agreed
last time, and a reminder of what the DM said they would observe next.

**Why this priority**: Continuity is what separates strong coaching from one-off
advice; it makes follow-through visible and ties to fairness/accountability. Depends on
a selected rep (P1) and is independently demonstrable.

**Independent Test**: Select a synthetic rep that has prior coaching history and confirm
the last session's notes, agreed actions, and "to observe next" reminders display.

**Acceptance Scenarios**:

1. **Given** a selected rep with prior coaching history, **When** the DM opens
   ride-along prep, **Then** the most recent coaching notes are shown.
2. **Given** prior history exists, **When** the DM views it, **Then** the actions both
   sides agreed and the items the DM committed to observe next are shown.
3. **Given** a rep with no prior coaching history, **When** the DM opens ride-along
   prep, **Then** the assistant clearly indicates there is no prior history yet.

---

### User Story 4 - See which accounts/HCPs matter and how the business is doing (Priority: P2)

For the selected rep, the DM sees the key accounts/HCPs to focus on, plus simple
business context (market share, volume, account performance, spend, and recent call
activity trends), and is shown where the rep's behavior may not match the opportunity.

**Why this priority**: Grounds coaching in business reality and surfaces
behavior-vs-opportunity mismatches, the heart of "fair" prioritization. Depends on a
selected rep (P1).

**Independent Test**: Select a synthetic rep and confirm a short list of key
accounts/HCPs appears with business context and at least one flagged
behavior-vs-opportunity mismatch where the data warrants it.

**Acceptance Scenarios**:

1. **Given** a selected rep, **When** the DM views accounts, **Then** a focused list of
   key accounts/HCPs is shown (not the rep's entire book).
2. **Given** an account/HCP in the list, **When** the DM views it, **Then** simple
   business context (share, volume, performance, spend, recent call activity trend) is
   shown.
3. **Given** an account where call activity does not match opportunity, **When** the DM
   views it, **Then** the mismatch is explicitly pointed out with its reason.
4. **Given** the accounts shown, **When** the DM views them, **Then** all are within the
   DM's district scope.

---

### User Story 5 - Get a suggested way to open the conversation (Priority: P3)

Based on the points above, the assistant suggests a short, clear opener the DM can use
to start the morning business talk with the rep.

**Why this priority**: A helpful finishing touch that lowers the effort to act on the
brief, but the brief is already valuable without it. Depends on the other sections for
substance.

**Independent Test**: For a selected rep with a populated brief, confirm a short
suggested opener appears that references the rep's specific situation.

**Acceptance Scenarios**:

1. **Given** a populated brief for a rep, **When** the DM views the opener, **Then** a
   short suggested opening statement/question is shown.
2. **Given** the opener, **When** the DM reads it, **Then** it references the specific
   points from this rep's brief (not generic boilerplate).
3. **Given** the opener is shown, **When** the DM reviews it, **Then** it is presented
   as a suggestion the DM may edit or ignore, never as a required script.

---

### Edge Cases

- **New rep, no history**: rep has no prior coaching notes — ride-along prep clearly
  says "no prior history" instead of showing empty fields.
- **Sparse data**: a rep or account has little/no recent activity data — the brief
  states what is missing rather than fabricating signals or reasons.
- **No standout rep**: all reps look similar — the ranking still explains its order and
  does not imply a false "problem rep."
- **Empty district**: a DM with no reps assigned sees a clear empty-state message.
- **Out-of-scope request**: a DM tries to view a rep, account, or district outside
  their territory — access is denied and nothing out of scope is shown.
- **Regional business director (RBD) view**: an RBD oversees several DMs/districts —
  they see their region; data is still scoped to their region only.
- **Tie / equal signals**: two reps or accounts have equal signals — ordering remains
  explainable and reason-based, not arbitrary or hidden.

## Requirements *(mandatory)*

### Functional Requirements

**Coaching brief content**

- **FR-001**: System MUST produce a single morning coaching brief for a DM that
  combines: a ranked list of reps needing attention, coaching focus areas, prior
  coaching history, key accounts/HCPs with business context, and a suggested opener.
- **FR-002**: System MUST present a ranked list of reps in the DM's team ordered by
  need for attention, derived from these four business signals: declining share, low
  call activity in key accounts, missed coaching follow-up, and business
  opportunity/risk. The relative weighting of these signals MUST be transparent and
  shown to the user (no hidden weighting).
- **FR-003**: System MUST show, for every ranked rep, at least one plain-language reason
  and the underlying business signal(s) that justify the ranking.
- **FR-004**: System MUST allow the DM to select a rep and view that rep's detailed
  brief sections.
- **FR-005**: System MUST suggest 1-3 coaching focus areas for the selected rep, each
  with a visible reason and supporting data.
- **FR-006**: System MUST show the selected rep's prior coaching notes, the actions both
  sides agreed last time, and the items the DM committed to observe next.
- **FR-007**: System MUST show a focused list of key accounts/HCPs for the selected rep
  with simple business context (market share, volume, account performance, spend, and
  recent call activity trends).
- **FR-008**: System MUST point out where a rep's behavior (e.g., call activity) may not
  match the account opportunity, with the reason for the flag.
- **FR-009**: System MUST suggest a short opener for the morning business conversation
  that references the specific points in the selected rep's brief.

**Explainability & human control (constitution: Explain Why; Human Decides)**

- **FR-010**: System MUST show a reason and the supporting data for every
  recommendation (rep ranking, coaching focus, account focus, opener). No
  recommendation may appear without its rationale.
- **FR-011**: System MUST present all outputs as suggestions only. The system MUST NOT
  take, send, schedule, or commit any action on the DM's behalf.
- **FR-012**: System MUST make ranking/prioritization explainable and based solely on
  stated business signals; it MUST NOT order reps or accounts using hidden criteria.

**Access & data (constitution: RBAC; Synthetic-only; Privacy; Fairness)**

- **FR-013**: System MUST restrict each user to their own territory: a DM sees only
  their own district; a regional business director (RBD) has read-only, region-scoped
  access to the same per-DM briefs across all districts in their region. The MVP does
  NOT provide cross-district aggregation or roll-up views for the RBD.
- **FR-014**: System MUST deny and exclude any rep, account, HCP, or district outside
  the user's territory scope, in data results (not only in the display).
- **FR-015**: System MUST use only synthetic data in this MVP and MUST NOT connect to or
  display any real customer, prescriber, or rep data.
- **FR-016**: System MUST treat rep data as HR-sensitive and HCP/prescriber data as
  private in how it is displayed, scoped, and (if applicable) logged.
- **FR-017**: System MUST exclude protected attributes (and obvious proxies for them)
  from the signals that drive rep or account prioritization.

**Quality & states**

- **FR-018**: System MUST clearly indicate missing or insufficient data (no history, no
  recent activity, empty district) instead of fabricating reasons or content.
- **FR-019**: Each recommendation type MUST be checkable against representative example
  cases with expected outcomes (so reliability can be demonstrated).

### Key Entities *(include if feature involves data)*

- **User**: a person using the assistant. Key attributes: role (district manager or
  regional business director) and the territory (district or region) they are scoped to.
- **District / Region (Territory)**: the access and aggregation boundary. A district
  belongs to a region; a region contains districts.
- **Sales Representative (Rep)**: a member of a DM's team. Attributes relevant to the
  brief: performance signals, call activity, assigned accounts, and coaching history.
- **Coaching Session (History)**: a prior ride-along record for a rep. Attributes:
  notes, agreed actions (both sides), and items to observe next.
- **Coaching Focus Area**: a suggested topic to coach a rep on, with its reason and
  supporting signals.
- **Account / HCP**: a customer or prescriber the rep covers. Attributes: market share,
  volume, performance, spend, recent call activity trend, and opportunity level.
- **Business Signal**: a measurable input (e.g., declining share, low call activity,
  missed follow-up, opportunity/risk) used to rank reps and accounts and to justify
  recommendations.
- **Coaching Brief**: the assembled morning output for a DM, composed of the ranked
  reps and, for a selected rep, the focus areas, history, accounts, and opener.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A DM can review the full brief (who to ride with, what to coach, what
  happened last time, which accounts matter, and a suggested opener) in under 5 minutes.
- **SC-002**: 100% of recommendations shown (rep rankings, coaching focus areas, account
  focus, openers) display a visible reason and the supporting data.
- **SC-003**: 100% of data shown to a user falls within that user's territory scope;
  zero out-of-scope reps, accounts, or HCPs appear in any test scenario.
- **SC-004**: In evaluation, two different DMs preparing for the same synthetic rep
  produce coaching preparation that is materially more consistent and complete than the
  same DMs preparing without the assistant, scored against a fixed preparedness
  checklist rubric that covers the five brief sections (rep + reason, coaching focus,
  last-time prep, accounts/business context, and opener).
- **SC-005**: A DM following the brief covers a higher share of the fixed rubric's
  preparation items than a DM who does not use it.
- **SC-006**: Every recommendation type passes its example-based checks (expected
  outcomes match) before release.
- **SC-007**: 100% of data used and displayed in the MVP is synthetic; no real customer,
  prescriber, or rep data is present in the environment.

## Assumptions

- The primary user for this MVP is the district manager; the regional business director
  is supported with read-only, region-scoped access to the same briefs (no aggregation),
  but is not the focus of the workflow.
- All data is synthetic and pre-loaded for the MVP; the brief reflects the current
  synthetic dataset rather than live or real-time sources.
- The synthetic dataset targets a small but realistic district: ~8–12 reps per district,
  ~15–30 accounts/HCPs per rep, and 2–3 prior coaching sessions for most reps (some reps
  intentionally have none, to exercise empty-state behavior).
- The ranked rep list shows a short set (assumed top 3-5) rather than the full team, to
  fit the "few minutes" goal; the exact count can be tuned during design.
- The brief is generated for "today" (the morning of a field ride); scheduling, calendar
  integration, and selecting a future date are out of scope for the MVP.
- Coaching history exists in the synthetic data for at least some reps so ride-along prep
  can be demonstrated; reps without history are handled via the empty-state behavior.
- "Behavior may not match opportunity" is derived from comparing the rep's recent call
  activity against the account's opportunity signals in the synthetic data.
- A fixed preparedness checklist rubric (covering the five brief sections) will be
  authored to evaluate the SC-004/SC-005 consistency and completeness outcomes.

## Out of Scope (MVP)

- Summit ranking optimization.
- Aggregating coaching themes across districts, regions, or nationally for leadership.
- Capturing new notes by voice during or after the ride.
- Connecting to any real or live data source (Veeva, IQVIA, AEBAT, Summit, etc.).
- Workflows for secondary users (reps, marketing/sales leadership, training, APEX).
