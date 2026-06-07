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
                                  │            └──< CallActivity, BusinessMetrics
                                  └──< CoachingSession (2–3)
RBD (User) ── scoped to ──> Region (read-only, all its districts)
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
| role | enum {`district_manager`, `regional_business_director`} | drives RBAC |
| district_id | string (FK→District), nullable | set for DM; null for RBD |
| region_id | string (FK→Region) | DM's region (via district) or RBD's region |

- **Rule**: A `district_manager` is scoped to `district_id`. A
  `regional_business_director` is scoped to `region_id` (all its districts), **read-only**.
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
| Field | Type | Notes |
|-------|------|-------|
| account_id | string (PK) | |
| rep_id | string (FK→Rep) | |
| name | string | account or HCP display name (synthetic) |
| type | enum {`account`, `hcp`} | |
| market_share | float 0–1 | |
| share_trend | float | signed recent change (e.g., declining share) |
| volume | number | |
| spend | number | promotional/marketing spend |
| performance | enum {`under`, `on`, `over` target} | account performance |
| opportunity_level | enum {`low`, `med`, `high`} | opportunity |
| risk_flag | bool | risk present |

- **Rule**: 15–30 accounts/HCPs per rep.

### CallActivity
| Field | Type | Notes |
|-------|------|-------|
| activity_id | string (PK) | |
| rep_id | string (FK→Rep) | |
| account_id | string (FK→Account) | |
| period | string (e.g., `2026-05`) | |
| calls | int | recent call count |
| calls_trend | float | signed recent change in activity |

- **Used for**: "low call activity in key accounts" signal and the behavior-vs-opportunity
  mismatch flag (low `calls` on `opportunity_level=high`).

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
| context | {market_share, share_trend, volume, spend, performance, calls_trend} | |
| mismatch_flag | bool | behavior vs opportunity mismatch |
| reason | Reason | why this account; why the mismatch |

### CoachingBrief (assembled output)
| Field | Type | Notes |
|-------|------|-------|
| brief_id | string | for audit/trace |
| generated_for | {user_id, role, scope} | DM (or RBD viewing) + territory scope |
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
- Ranking MUST use only the four signals with visible weights; no protected attributes
  (FR-002/012/017).
- `synthetic` MUST be `true` for all MVP data (FR-015).
