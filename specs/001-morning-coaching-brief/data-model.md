# Phase 1 Data Model: Morning Coaching Brief (MVP)

Derived from the spec's Key Entities and the plan. Field types are logical (not
storage-specific); the MVP persists these in SQLite/DuckDB behind the data-access
interface (see [contracts/data-access.md](./contracts/data-access.md)). All reads are
RBAC-scoped (Principle V). HCP fields are treated as private (IQVIA/PDRP); rep fields as
HR-sensitive (Principle IV).

## Entity overview & relationships

```text
Region (1) ──< District (2) ──< User (DM, 1 per district)
                     │
                     └──< Rep (8–12) ──< Account/HCP (15–30)
                                  │            └──< AccountBrandMetrics (per brand), CallActivity (per brand)
                                  └──< CoachingSession (2–3)
Region-level role (User) ── scoped to ──> Region (full access, all its districts)
```

## Entities

### Region
| Field | Type | Notes |
|-------|------|-------|
| region_id | string (PK) | e.g., `R1` |
| name | string | |

### District
| Field | Type | Notes |
|-------|------|-------|
| district_id | string (PK) | e.g., `D1`, `D2` |
| region_id | string (FK→Region) | exactly 2 districts in the seed |
| name | string | |

- **Rule**: A District belongs to exactly one Region. The seed has 1 region, 2 districts.

### User
| Field | Type | Notes |
|-------|------|-------|
| user_id | string (PK) | |
| name | string | |
| role | enum (config-sourced) | maps to a **scope level**; drives RBAC |
| scope_level | enum {`self`, `district`, `region`, `all`} | the territory level the role grants |
| district_id | string (FK→District), nullable | set for a `district`-level user; null otherwise |
| region_id | string (FK→Region) | the user's region (via district for a DM, or directly) |

- **Rule**: access is scoped by **level**, not job title: `self` (rep — modeled, no MVP
  workflow), `district` (DM — own district), `region` (region-level roles — whole region),
  `all` (top sales role — all regions). All **non-rep** levels have **full access** (NOT
  read-only); `region` and above also carry action rights. The role-name → `scope_level`
  mapping comes from a **single config/enum source** (role names are configuration).
- **Identity/uniqueness**: `user_id` unique. One DM per district in the seed.

### Rep (Sales Representative) — *HR-sensitive*
| Field | Type | Notes |
|-------|------|-------|
| rep_id | string (PK) | |
| name | string | |
| district_id | string (FK→District) | RBAC scope key |
| tenure_months | int | context only — **not** a ranking signal |

- **Rule**: A Rep belongs to exactly one District. 8–12 reps per district.
- **Fairness (VI)**: No protected attributes are stored or used in ranking; `tenure_months`
  is display context only, excluded from the scorer.

### Account / HCP — *private (IQVIA/PDRP)*
Identity + privacy attributes. Brand-attributable performance lives in **AccountBrandMetrics** (below).

| Field | Type | Notes |
|-------|------|-------|
| account_id | string (PK) | |
| rep_id | string (FK→Rep) | |
| name | string | account or HCP display name (synthetic) |
| type | enum {`account`, `hcp`} | |
| prp | bool | prescriber data restriction; `true` → scrubbed at the data-access layer before any result reaches a field user (FR-020) |

- **Rule**: 15–30 accounts/HCPs per rep.
- **Privacy (IV)**: An HCP with `prp = true` MUST NOT appear in any data returned to a
  field user. The data-access layer scrubs PRP HCPs from all reads (FR-020), refining the
  HCP-private treatment (FR-016).

### AccountBrandMetrics — *private (IQVIA/PDRP)*
**Decision (I1): performance metrics are PER-BRAND.** Share, volume, spend, performance,
opportunity, and risk are attributable to an `(account, brand)` pair, so one account can
carry metrics across multiple of the five brands.

| Field | Type | Notes |
|-------|------|-------|
| account_id | string (FK→Account) | part of composite key |
| brand | enum Brand | part of composite key (see **Brand**) |
| market_share | float 0–1 | for this account+brand |
| share_trend | float | signed recent change (e.g., declining share) |
| volume | number | |
| spend | number | promotional/marketing spend |
| performance | enum {`under`, `on`, `over` target} | account performance for this brand |
| opportunity_level | enum {`low`, `med`, `high`} | opportunity for this brand |
| risk_flag | bool | risk present for this brand |

- **Key**: composite PK `(account_id, brand)`. An account has one row per brand it carries.
- **Inherits PRP**: rows belonging to a `prp = true` account are scrubbed with the account (FR-020).

### Brand (enum / config — single source of truth)
The modeled brand portfolio. Names live in ONE place (an enum or config value) so they
are easy to change later.

| Value | Notes |
|-------|-------|
| `LUPRON_PEDS` | LUPRON PEDS |
| `LUPRON_URO` | LUPRON URO |
| `LUPRON_GYN` | LUPRON GYN |
| `SYNTHROID` | Synthroid |
| `LITELLA` | Litella (spelling TBC — see spec Assumptions open item) |

- **Rule**: Performance data (share, volume, spend, call activity) is attributable to a
  brand in this portfolio via the `(account, brand)` pair. No brand name is hard-coded
  outside this enum/config.

### CallActivity
| Field | Type | Notes |
|-------|------|-------|
| activity_id | string (PK) | |
| rep_id | string (FK→Rep) | |
| account_id | string (FK→Account) | |
| brand | enum Brand | call activity is per-(account, brand) (I1 decision) |
| period | string (e.g., `2026-05`) | |
| calls | int | recent call count |
| calls_trend | float | signed recent change in activity |

- **Used for**: "low call activity in key accounts" signal and the behavior-vs-opportunity
  mismatch flag (low `calls` on a brand whose `opportunity_level=high` for that account).

### CoachingSession (History)
| Field | Type | Notes |
|-------|------|-------|
| session_id | string (PK) | |
| rep_id | string (FK→Rep) | |
| date | date | most recent used for ride-along prep |
| notes_text | text | free text — embedded for RAG |
| agreed_actions | list<string> | actions both sides agreed |
| observe_next | list<string> | what the DM committed to observe next |
| follow_up_done | bool | drives "missed coaching follow-up" signal |

- **Rule**: 2–3 sessions for most reps; some reps have **0** (empty-state edge case).
- **RAG**: `notes_text` (+ key fields) chunked & embedded (Titan) into the vector store.

## Derived / computed objects (not persisted)

### Reason (structured explainability object) — core to Principle II
Every recommendation carries one of these.
| Field | Type | Notes |
|-------|------|-------|
| summary | string | LLM-narrated plain-language reason (rendered to DM) |
| signals | list<SignalContribution> | the machine-truth behind `summary` |
| data_points | list<{label, value, source}> | exact values used |

**SignalContribution** (used by the deterministic scorer):
| Field | Type | Notes |
|-------|------|-------|
| signal | enum {`declining_share`, `low_call_activity`, `missed_follow_up`, `opportunity_risk`} | |
| raw_value | number | normalized 0–1 sub-score |
| weight | float | fixed, visible weight from config |
| contribution | float | `raw_value * weight` |

### RepRanking (output of prioritization component)
| Field | Type | Notes |
|-------|------|-------|
| rep_id | string | |
| rank | int | 1 = highest need |
| total_score | float | sum of contributions |
| reason | Reason | signals + weights + data points |

- **Determinism**: identical seeded input → identical ranking & scores (tested). Tie-break
  rule is stable and documented (opportunity/risk desc, then rep_id asc).

### CoachingFocus (output of coaching-focus component)
| Field | Type | Notes |
|-------|------|-------|
| focus_area | string | 1–3 per rep |
| reason | Reason | tied to the rep's data |

### AccountFocus (output of accounts/context component)
| Field | Type | Notes |
|-------|------|-------|
| account_id | string | |
| brand | enum Brand | the brand this context row relates to (labeled to the DM) |
| context | {market_share, share_trend, volume, spend, performance, calls_trend} | per-(account, brand) (I1) |
| mismatch_flag | bool | behavior vs opportunity mismatch, for this account+brand |
| reason | Reason | why this account; why the mismatch |

- **Per-brand (FR-007)**: business context is labeled and broken down by brand, so the DM
  sees which brand each number relates to. An account may contribute multiple AccountFocus
  rows (one per brand it carries).

### CoachingBrief (assembled output)
| Field | Type | Notes |
|-------|------|-------|
| brief_id | string | for audit/trace |
| generated_for | {user_id, role, scope_level, scope} | DM (or a region-level role viewing) + territory scope |
| ranked_reps | list<RepRanking> | section 1 (top 3–5) |
| selected_rep_id | string | the rep the rest of the brief details |
| coaching_focus | list<CoachingFocus> | section 2 (1–3) |
| ride_along_prep | {last_session, agreed_actions, observe_next} \| empty-state | section 3 |
| accounts | list<AccountFocus> | section 4 |
| opener | {text, reason} | section 5 |
| synthetic | bool = true | data provenance label (Principle III) |

## State / lifecycle notes

- The brief is **read-only, generated on demand** ("today"). No persisted brief state
  machine in the MVP beyond the audit record. No entity is mutated by the assistant
  (Principle I — the assistant never acts).
- Empty states: rep with 0 `CoachingSession` → `ride_along_prep = empty-state`; sparse
  `CallActivity` → component reports missing data rather than fabricating (FR-018).

## Validation rules (from requirements)

- Every output object that represents a recommendation MUST include a non-empty `reason`
  (FR-010). Tests reject any recommendation missing a reason.
- All reads MUST be RBAC-scoped; results MUST contain only in-scope rows (FR-013/014).
- HCPs with `prp = true` MUST be scrubbed by the data-access layer before any result is
  returned to a field user; no PRP HCP appears in any output (FR-020).
- Ranking MUST use only the four signals with visible weights; no protected attributes
  (FR-002/012/017).
- `synthetic` MUST be `true` for all MVP data (FR-015).
