<!--
SYNC IMPACT REPORT
==================
Version change: (template / unversioned) → 1.0.0
Bump rationale: Initial ratification of the project constitution. First formal,
versioned governance document for field-intelligence-coach-agent.

Modified principles: N/A (initial adoption)
Added principles:
  I.   Human Decides, AI Assists
  II.  Always Explain Why
  III. Synthetic Data Only in the POC
  IV.  Data Privacy & Compliance From Day One
  V.   Role- and Territory-Based Access Control (RBAC)
  VI.  Fair, Not Biased
  VII. Built to Grow Into Production
  VIII.One Platform (AWS + Bedrock + Claude)
  IX.  Quality Must Be Testable
Added sections:
  - Security, Privacy & Compliance Constraints
  - Development Workflow & Quality Gates
  - Governance

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — reviewed; "Constitution Check" gate is a
     generic placeholder resolved at plan time against this file. No edit required.
  ✅ .specify/templates/spec-template.md — reviewed; no mandatory section added/removed
     by this constitution that the spec template must hard-code. No edit required.
  ✅ .specify/templates/tasks-template.md — reviewed; principle-driven task types
     (RBAC, explainability, fairness, test fixtures) are expressed at task-generation
     time. No structural edit required.

Follow-up TODOs: none. RATIFICATION_DATE set to project start (2026-06-07).
-->

# Field Intelligence Coach Agent Constitution

An AI-powered agent that helps district managers and regional business directors
prepare for coaching conversations and make better business prioritization decisions.
These principles are non-negotiable. Every spec, plan, task, and review MUST comply.

## Core Principles

### I. Human Decides, AI Assists

The agent MUST only suggest, prepare, and inform. The district manager or regional
business director ALWAYS makes the final decision. The agent MUST NOT take any
real-world action on its own — it never books, sends, commits, or executes on behalf
of a user without an explicit human approval step.

Rationale: Coaching and prioritization are judgment calls that carry people,
performance, and compliance consequences. Keeping a human in command is both an
ethical requirement and a trust requirement for field adoption.

### II. Always Explain Why

Every suggestion — which rep to coach, what to coach on, which account to focus on —
MUST surface its reason and the underlying data signals. No black-box output is
permitted. Each recommendation MUST be traceable to the inputs that produced it.

Rationale: Managers will only act on advice they can defend to their reps and their
own leadership. Explainability is also a precondition for the fairness and
auditability principles below.

### III. Synthetic Data Only in the POC

The POC environment MUST use synthetic data that mirrors the *shape* of real data.
No real Veeva, IQVIA, AEBAT, or Summit data may enter the POC. Synthetic datasets
MUST be clearly labeled as synthetic and MUST NOT be presented as real performance.

Rationale: Building against realistic shapes proves the design while removing the
privacy, regulatory, and contractual risk of handling real prescriber and rep data
before production controls exist.

### IV. Data Privacy & Compliance From Day One

The system MUST be designed as if real data rules already apply, even on synthetic
data. HCP data MUST be treated as private. Prescriber data MUST follow IQVIA / PDRP
rules. Rep performance data MUST be treated as HR-sensitive. Privacy and compliance
controls are designed in from the start, not retrofitted.

Rationale: Designing for the strictest rules from day one means swapping in real data
later is a data-source change, not a security or compliance redesign.

### V. Role- and Territory-Based Access Control (RBAC)

Users MUST see only what their role and territory permit. A district manager sees
their own district; a regional business director sees their region. Access decisions
MUST be enforced at the data-access layer, not merely hidden in the UI.

Rationale: Field hierarchies are sensitive. Enforcing scope at the data layer prevents
both accidental leakage and deliberate over-reach, and keeps the model from ever
reasoning over data the user is not entitled to.

### VI. Fair, Not Biased

The agent MUST support the "equal to fair" goal. It MUST NOT rank or profile reps in
a hidden or unfair way. Prioritization MUST be explainable and grounded in legitimate
business signals. Protected or proxy-for-protected attributes MUST NOT drive
recommendations.

Rationale: Coaching prioritization directly affects careers. Fairness is both an
ethical obligation and a legal/HR risk control; it depends on the transparency
required by Principle II.

### VII. Built to Grow Into Production

The system MUST keep a clean, well-defined data-access tool layer so that swapping
synthetic data for real connectors later is a change of source, not a rewrite.
The system is commercial (not GxP) but MUST be governed, secure, and auditable.

Rationale: A stable tool/connector boundary is what makes the POC a credible path to
production rather than a throwaway demo.

### VIII. One Platform (AWS + Bedrock + Claude)

The system MUST be built on AWS, using Amazon Bedrock with Claude for model inference.
Orchestration logic MUST live in code (not hidden in prompt-only flows) so it stays
testable and reviewable.

Rationale: A single, code-orchestrated platform keeps the system testable, portable
across environments, and free of opaque orchestration that cannot be verified.

### IX. Quality Must Be Testable

Every type of recommendation MUST be checkable against example cases. Each
recommendation category requires representative test fixtures with expected outcomes,
so reliability can be demonstrated to leadership.

Rationale: "Show, don't tell." Testable recommendation quality is how trust is earned
and how regressions are caught before they reach a field manager.

## Security, Privacy & Compliance Constraints

- **Data classification**: HCP/prescriber data = private (IQVIA/PDRP); rep performance
  data = HR-sensitive. All storage, logging, and model context MUST respect these
  classifications.
- **No real data in POC**: enforced per Principle III. Synthetic generators MUST
  produce shape-faithful, clearly-labeled data.
- **Access enforcement**: RBAC (Principle V) MUST be enforced server-side at the
  data-access layer; UI filtering alone is insufficient.
- **Auditability**: recommendation inputs, reasoning, and any human approval actions
  MUST be auditable. Audit records MUST not themselves leak out-of-scope data.
- **Platform**: AWS + Amazon Bedrock (Claude) per Principle VIII. Secrets and
  credentials MUST follow standard AWS secret-management practice.

## Development Workflow & Quality Gates

- **Constitution Check (gate)**: Every `plan.md` MUST pass a Constitution Check before
  Phase 0 and again after Phase 1 design. Violations MUST be recorded and justified in
  the plan's Complexity Tracking table, or the design MUST change.
- **Explainability gate**: No recommendation feature ships without surfacing its reason
  and supporting signals (Principle II).
- **Fairness gate**: Prioritization features MUST document which business signals drive
  ranking and confirm no hidden/protected-proxy ranking (Principle VI).
- **RBAC gate**: Any feature reading rep, HCP, or territory data MUST demonstrate
  data-layer scope enforcement (Principle V).
- **Test gate**: Each recommendation category MUST have example-based tests with
  expected outcomes (Principle IX) before it is considered done.
- **Tool-layer gate**: Data access MUST go through the connector/tool abstraction so a
  source swap does not require a rewrite (Principle VII).

## Governance

This constitution supersedes other project practices where they conflict. All specs,
plans, tasks, and code reviews MUST verify compliance with these principles, and any
complexity that deviates MUST be explicitly justified.

**Amendment procedure**: Proposed amendments MUST be documented (what changes and why),
reviewed and approved by the project owner, and accompanied by a migration note when
they affect existing specs, plans, or templates.

**Versioning policy** (semantic versioning of this document):
- **MAJOR**: backward-incompatible governance changes or principle removals/redefinitions.
- **MINOR**: a new principle or section, or materially expanded guidance.
- **PATCH**: clarifications, wording, and non-semantic refinements.

**Compliance review**: Compliance is checked at each speckit gate (specify, plan, tasks,
implement, analyze) and at code review. The dependent templates under
`.specify/templates/` MUST be kept in sync when principles change.

**Version**: 1.0.0 | **Ratified**: 2026-06-07 | **Last Amended**: 2026-06-07
