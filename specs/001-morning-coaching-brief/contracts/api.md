# Contract: HTTP API (FastAPI)

Minimal API the web page calls. The reads are **read-only**, and there is exactly **one
write** — the CLOSE capture (`POST /api/brief/{rep_id}/close`), which **records the DM's own
observations** through the single data-access door; it is not an autonomous action (Principle I —
the assistant suggests/records; the human decides). Every response is RBAC-scoped to the caller's
`AccessContext` (Principle V). The brief endpoint returns recommendations that each include a
structured `reason` (Principle II). The server runs **offline by default** (a deterministic
narrator/structurer); Bedrock is used only when a model id is configured.

## Identity (MVP-simulated → Cognito in prod)

- Caller identity is supplied via header `X-User-Id: <user_id>` (MVP stub). The server
  resolves it to an `AccessContext` `{user_id, role, scope_level, district_id?, region_id}`
  (`scope_level` ∈ `self`/`district`/`region`/`all`; the role-name → scope_level mapping
  comes from config).
- Missing/unknown user → `401`. Out-of-scope target → `403` (nothing out-of-scope is
  returned).

## Endpoints

### `GET /api/whoami`
Returns the resolved access context (for the UI to show role/territory).
```json
{ "user_id": "dm_d1", "role": "district_manager", "scope_level": "district", "district_id": "D1", "region_id": "R1" }
```

### `GET /api/reps`
Ranked list of reps needing attention (brief section 1), scoped to the caller.
- Query: `?limit=5` (default 3–5).
- `200` response:
```json
{
  "synthetic": true,
  "scope": { "role": "district_manager", "scope_level": "district", "district_id": "D1" },
  "ranked_reps": [
    {
      "rep_id": "rep_007",
      "rank": 1,
      "total_score": 0.78,
      "reason": {
        "summary": "Declining share in 3 high-opportunity accounts and a missed coaching follow-up.",
        "signals": [
          { "signal": "declining_share",  "raw_value": 0.9, "weight": 0.25, "contribution": 0.225 },
          { "signal": "low_call_activity","raw_value": 0.6, "weight": 0.25, "contribution": 0.150 },
          { "signal": "missed_follow_up", "raw_value": 1.0, "weight": 0.25, "contribution": 0.250 },
          { "signal": "opportunity_risk", "raw_value": 0.62,"weight": 0.25, "contribution": 0.155 }
        ],
        "data_points": [
          { "label": "share_trend (acct A12)", "value": -0.08, "source": "BusinessMetrics" },
          { "label": "calls last period (acct A12)", "value": 1, "source": "CallActivity" }
        ]
      }
    }
  ]
}
```

### `GET /api/brief/{rep_id}`
Full coaching brief for one rep (sections 2–5 plus the rep's ranking from section 1).
- `403` if `rep_id` is outside the caller's scope.
- `200` response (shape mirrors `CoachingBrief` in data-model.md):
```json
{
  "brief_id": "brief_2026-06-07_rep_007",
  "synthetic": true,
  "generated_for": { "user_id": "dm_d1", "role": "district_manager", "scope_level": "district", "scope": "D1" },
  "selected_rep_id": "rep_007",
  "ranked_reps": [ "...section 1 (as above)..." ],
  "coaching_focus": [
    { "focus_area": "Closing new therapy starts",
      "reason": { "summary": "...", "signals": [], "data_points": [] } }
  ],
  "ride_along_prep": {
    "last_session": { "date": "2026-05-20", "notes_text": "..." },
    "agreed_actions": ["Pre-call plan for top-5 accounts"],
    "observe_next": ["Opening value statement with Dr. X"]
  },
  "accounts": [
    { "account_id": "A12",
      "context": { "market_share": 0.21, "share_trend": -0.08, "volume": 1300,
                   "spend": 4200, "performance": "under", "calls_trend": -0.4 },
      "mismatch_flag": true,
      "reason": { "summary": "High opportunity but call activity is dropping.",
                  "signals": [], "data_points": [] } }
  ],
  "opener": {
    "text": "Let's start with A12 — share is slipping where the opportunity is biggest. How are you thinking about it?",
    "reason": { "summary": "Built from the top-ranked account mismatch.", "signals": [], "data_points": [] }
  }
}
```

- **Empty states**: `ride_along_prep` returns `{ "empty": true, "message": "No prior coaching history yet." }` when the rep has no sessions (FR-018). Sparse data is reported, not fabricated.
- **Now also in the brief (Phases 8–9):** `ranked_reps[].reason.signals` carries a 5th
  `summit_opportunity` contributor (capability #5; deterministic, computed in code), and the brief
  has a `covariant` section (capability #4) — a transparent association with the configured
  "success" measure noted and an honest insufficient-data state.

### `GET /api/themes`  *(Phase 7 — capability #6)*
Aggregated coaching themes for a leadership reader — **patterns and counts ONLY, never named
individuals** (FR-016). **Leadership-scoped:** only `region`/`all` callers; a `district` (DM)
caller gets the same `403` as out-of-scope (indistinguishable from not-found). `200` returns
`{ generated_for, rep_count, themes: [ { theme, signal, rep_count, rep_share, suppressed, reason } ], synthetic }`
(small cells suppressed; each theme carries a narrated `reason`).

### `POST /api/brief/{rep_id}/close`  *(Phase 10 — capability #2; the one write)*
Records a CLOSE note for an in-scope rep through the **single data-access door** under
**writer-scope RBAC** (out-of-scope or unknown rep → `403`). Body is either a `transcript` (the
typed/spoken path — structured offline; `observations` stay the DM's **verbatim** words) or the
already-structured fields. `200` returns `{ "synthetic": true, "saved": { ...CloseRecord... } }`.
The saved note flows back through the same scoped + PRP-scrubbed readback (ADR 0002), so it
appears in the rep's next ride-along prep — and a note tied to a PRP HCP is never surfaced.

## Cross-cutting contract rules
- Every `reason` field MUST be present and non-empty on recommendation objects (FR-010).
- No response contains rows/reps/accounts outside the caller's scope (FR-013/014).
- `synthetic: true` MUST appear on data responses (FR-015).
- Each request that generates a brief MUST emit one audit record (research §8).
