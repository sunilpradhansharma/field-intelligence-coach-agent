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
- Q: What is the region-level role's scope in this MVP? → A: Region-scoped, **full access** (it can take actions — NOT read-only) to the same DM briefs (all districts in their region); no aggregation/roll-up. *(Updated — supersedes the earlier "read-only" answer; access is expressed as scope levels in FR-013.)*
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
   shown, labeled and broken down by brand so it is clear which brand each number relates to.
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
- **Region-level role view**: a region-level role (e.g., regional director) oversees
  several DMs/districts — they see their whole region with full access; data is still
  scoped to their region only.
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
  recent call activity trends). This business context MUST be labeled and broken down BY
  BRAND, so the DM can see which brand each number relates to (an account may carry
  metrics across more than one of the modeled brands).
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

- **FR-013**: System MUST restrict each user to their authorized **territory scope level**,
  enforced at the data-access layer. Scope levels are: **self** (a rep — modeled, no MVP
  workflow), **district** (a DM — their own district), **region** (region-level roles —
  their whole region), and **all regions** (the top sales role). All **non-rep** roles have
  **full access within their scope** (NOT read-only); region-level and above also carry
  action rights. **Roles map to a scope level via a single config/enum source** — role
  names are configuration, not hard-coded logic. The MVP (Phases 1–6) does NOT provide
  cross-district aggregation or roll-up views; roll-ups are introduced later as a **scoped,
  aggregate-only** leadership view (Phase 7 — patterns and counts only, never named
  individuals, and only within the viewer's own scope; see *Future Capabilities (Phases 7–10)*).
- **FR-014**: System MUST deny and exclude any rep, account, HCP, or district outside
  the user's territory scope, in data results (not only in the display).
- **FR-015**: System MUST use only synthetic data in this MVP and MUST NOT connect to or
  display any real customer, prescriber, or rep data.
- **FR-016**: System MUST treat rep data as HR-sensitive and HCP/prescriber data as
  private in how it is displayed, scoped, and (if applicable) logged.
- **FR-017**: System MUST exclude protected attributes (and obvious proxies for them)
  from the signals that drive rep or account prioritization.
- **FR-020**: System MUST exclude any HCP flagged as **PRP** (prescriber data
  restriction) from all data returned to a field user. The data-access layer MUST scrub
  PRP-flagged HCPs from results before they are returned (not only hide them in the UI),
  so no PRP HCP appears in any brief section, list, or context. This refines the privacy
  requirement (FR-016) for prescriber data restrictions.

**Quality & states**

- **FR-018**: System MUST clearly indicate missing or insufficient data (no history, no
  recent activity, empty district) instead of fabricating reasons or content.
- **FR-019**: Each recommendation type MUST be checkable against representative example
  cases with expected outcomes (so reliability can be demonstrated).

### Key Entities *(include if feature involves data)*

- **User**: a person using the assistant. Key attributes: role and the **territory scope
  level** it maps to — **self** (rep), **district** (DM), **region** (region-level roles),
  or **all regions** (top sales role). The role-name → scope-level mapping comes from a
  single config/enum source.
- **District / Region (Territory)**: the access and aggregation boundary. A district
  belongs to a region; a region contains districts.
- **Sales Representative (Rep)**: a member of a DM's team. Attributes relevant to the
  brief: performance signals, call activity, assigned accounts, and coaching history.
- **Coaching Session (History)**: a prior ride-along record for a rep. Attributes:
  notes, agreed actions (both sides), and items to observe next.
- **Coaching Focus Area**: a suggested topic to coach a rep on, with its reason and
  supporting signals.
- **Account / HCP**: a customer or prescriber the rep covers. Attributes: market share,
  volume, performance, spend, recent call activity trend, opportunity level, and a `prp`
  boolean (prescriber data restriction). Performance attributes (share, volume, spend,
  call activity) are attributable to a brand in the modeled portfolio. A `prp = true` HCP
  MUST be scrubbed by the data-access layer before any result reaches a field user (FR-020).
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

- The primary user for this MVP is the district manager; region-level (and above) roles
  are supported with region-scoped **full access** to the same briefs (no aggregation), but
  are not the focus of the workflow — they get access rules only, no dedicated screens in
  the MVP.
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
- **Brand portfolio (data realism)**: the POC models a five-brand portfolio — LUPRON
  PEDS, LUPRON URO, LUPRON GYN, Synthroid, and LILETTA (brand spelling finalized).
  Performance data (share, volume, spend, call activity) is attributable to a brand. The
  brand names MUST live in ONE place (an enum or config value) so they are easy to change
  later.
- **Terminology / external systems (confirmed facts)**: **AEBAT** is the tool/website
  that shows strategic spend and speaker-program spend by rep — it is NOT a team. **APEX**
  is the internal analytics support team (a support team / secondary user) — it is NOT a
  data source.

## Out of Scope (MVP)

Out of scope for the **MVP (Phases 1–6)**. Three of these were post-MVP capabilities and are
now **BUILT (Phases 7–10 DONE)** — see *Post-MVP Capabilities (Phases 7–10)* below for their
scope and the rules they keep:

- Summit ranking optimization. *(Built — Phase 8.)*
- Aggregating coaching themes across districts, regions, or nationally for leadership.
  *(Built — Phase 7, as a **scoped, aggregate-only** leadership view: patterns and counts
  only, never named individuals.)*
- Capturing new notes by voice during or after the ride. *(Built — Phase 10.)*
- Connecting to any real or live data source (Veeva, IQVIA, AEBAT — the strategic /
  speaker-program spend reporting tool, Summit, etc.). *(Remains out of scope — synthetic-only.)*
- Workflows for secondary users (reps, marketing/sales leadership, training, APEX — the
  internal analytics support team). *(Remains out of scope.)*

## Post-MVP Capabilities (Phases 7–10) — BUILT

These extend the **same architecture** as the MVP and are **now built** (Phases 7–10 DONE;
status detail: [`docs/project-status.md`](../../docs/project-status.md)). Every one keeps the constitution
rules intact: **deterministic logic is computed in code; the LLM only narrates wording (never
decides ranks, scores, or analysis); all reads AND writes go through the single data-access
door with RBAC scope + PRP scrubbing enforced there; every recommendation carries a visible
`reason`; data is synthetic-only; and the assistant only suggests/records — the human decides.**

- **Phase 7 — theme aggregation (capability #6).** Read *across* reps to surface common
  coaching themes for a leadership view. Two invariants are mandatory: **(a)** the
  aggregated/leadership view shows **patterns and counts only — NEVER named individual reps or
  individually identifiable rep detail** (FR-016); and **(b)** it is **RBAC-scoped** — only the
  **region** and **all** scope levels may see it, each only across **their own region / all
  regions** (it is a scoped, aggregate-only roll-up, not an unscoped one — enforced at the same
  data-access door). This is the scoped roll-up that FR-013 says the MVP does not yet provide.
- **Phase 8 — Summit optimization (capability #5).** Add the **Summit / IC-plan lift** as a
  new **ranking signal**. The lift is **computed in code** from data + per-team config (a
  per-team formula) — **deterministic and explainable, exactly like the four existing signals;
  the LLM never scores or decides it** and may only narrate the wording. Configurable per team.
- **Phase 9 — covariant analysis (capability #4).** Deeper insight in the accounts section —
  which factors move together with results. The analysis is **computed in code and is
  deterministic/explainable, NOT LLM-decided**; the LLM may only narrate the resulting
  structured finding. The **"success" measure** ships as a clearly-labeled config DEFAULT
  ASSUMPTION to confirm with the business (it is not hard-coded), and the insight is surfaced in
  the brief's accounts section with an honest insufficient-data state.
- **Phase 10 — verbal feedback / CLOSE capture (capability #2).** Capture post-ride
  observations using **Amazon Transcribe** (a seam; a deterministic offline fake in tests) + a CLOSE record. The assistant **records
  the human's (the DM's) input — it does not act or auto-generate a plan** (suggestion-only
  holds). This is the **first write path**: writes go through the **same single data-access
  door** under the **writer's own scope (writer-scope RBAC)**, and the transcribed free-text
  CLOSE notes are subject to the **same PRP scrubbing + RBAC on readback** as every other note
  (per **ADR 0002** — the retriever enforces RBAC + PRP at query time), so a captured note that
  references a PRP HCP is never surfaced to a field user.
