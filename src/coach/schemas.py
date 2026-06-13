"""Pydantic schemas: entities, the explainability `Reason` object, recommendation
objects, and the synthetic `Dataset` container.

Validation rules enforced here (from the spec):
- Every recommendation object (RepRanking, CoachingFocus, AccountFocus, Opener) MUST
  carry a non-empty `Reason` (FR-010, Principle II).
- A `Reason.summary` must be non-empty.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- enums
class Role(StrEnum):
    """Role NAMES. The authoritative role → scope-level mapping lives in ONE place:
    `coach.config.settings.ROLE_SCOPE_LEVELS`. RBAC code scopes by `ScopeLevel`, never by
    these names directly. ("RD"/"RBE" terminology is still being confirmed — names are
    config; see docs/project-status.md.)"""

    rep = "rep"
    district_manager = "district_manager"
    regional_director = "regional_director"  # RD
    regional_business_executive = "regional_business_executive"  # RBE (working definition)
    head_of_sales = "head_of_sales"


class ScopeLevel(StrEnum):
    """Territory scope a role grants — the RBAC mechanism (Principle V / FR-013).
    All non-rep levels have FULL access (no read-only)."""

    self_ = "self"  # a rep — only their own records
    district = "district"  # a DM — their own district
    region = "region"  # region-level roles (RD, RBE) — their whole region
    all_ = "all"  # top sales role (Head of Sales) — all regions


class AccountType(StrEnum):
    account = "account"
    hcp = "hcp"


class Performance(StrEnum):
    under = "under"
    on = "on"
    over = "over"


class OpportunityLevel(StrEnum):
    low = "low"
    med = "med"
    high = "high"


class Brand(StrEnum):
    """The modeled brand portfolio — SINGLE SOURCE OF TRUTH for brand names.

    Performance data (share, volume, spend, call activity) is attributable to a brand
    via the (account, brand) pair (see data-model.md). No brand name may be hard-coded
    anywhere else; draw from this enum.
    """

    lupron_peds = "LUPRON PEDS"
    lupron_uro = "LUPRON URO"
    lupron_gyn = "LUPRON GYN"
    synthroid = "Synthroid"
    liletta = "LILETTA"


class SignalName(StrEnum):
    declining_share = "declining_share"
    low_call_activity = "low_call_activity"
    missed_follow_up = "missed_follow_up"
    opportunity_risk = "opportunity_risk"
    # Phase 8 / capability #5 — the Summit/IC-plan ranking-lift opportunity. OFF by default
    # (config weight 0.0); the four signals above are the MVP core. Deterministic, code-computed.
    summit_opportunity = "summit_opportunity"


# ---------------------------------------------------------------------- entities
class Region(BaseModel):
    region_id: str
    name: str


class District(BaseModel):
    district_id: str
    region_id: str
    name: str


class User(BaseModel):
    user_id: str
    name: str
    role: Role
    region_id: str
    district_id: str | None = None  # set for a DM; None for an RBD


class Rep(BaseModel):
    rep_id: str
    name: str
    district_id: str
    tenure_months: int  # context only — NOT a ranking signal (Principle VI / FR-017)


class Account(BaseModel):
    account_id: str
    rep_id: str
    name: str
    type: AccountType
    market_share: float
    share_trend: float  # signed; negative = declining share
    volume: float
    spend: float
    performance: Performance
    opportunity_level: OpportunityLevel
    risk_flag: bool
    # PRP (prescriber data restriction). Data is ADDED here in the foundation phase;
    # the data-access SCRUBBING of prp=True HCPs is a later task (T008A, FR-020).
    prp: bool = False


class AccountBrandMetrics(BaseModel):
    """Per-(account, brand) performance metrics (data-model.md I1 decision).

    One account can carry metrics across multiple brands; keyed by (account_id, brand).
    """

    account_id: str
    brand: Brand
    market_share: float
    share_trend: float  # signed; negative = declining share
    volume: float
    spend: float
    performance: Performance
    opportunity_level: OpportunityLevel
    risk_flag: bool


class CallActivity(BaseModel):
    activity_id: str
    rep_id: str
    account_id: str
    brand: Brand  # call activity is per-(account, brand) (data-model.md I1)
    period: str
    calls: int
    calls_trend: float  # signed recent change in activity


class CoachingSession(BaseModel):
    session_id: str
    rep_id: str
    date: str  # ISO date
    notes_text: str
    agreed_actions: list[str] = Field(default_factory=list)
    observe_next: list[str] = Field(default_factory=list)
    follow_up_done: bool = True  # False -> "missed coaching follow-up" signal
    # The account/HCP this note is about, when known (set on a CLOSE record). Drives PRP scrubbing
    # at readback: a note tied to a PRP account is dropped by the retriever (ADR 0002). `None` for
    # synthetic seed notes (the retriever ties those to an account positionally).
    account_id: str | None = None


class BusinessMetric(BaseModel):
    """A per-account view of business context (derived from Account fields)."""

    account_id: str
    market_share: float
    share_trend: float
    volume: float
    spend: float
    performance: Performance


# ----------------------------------------------------- explainability objects
class DataPoint(BaseModel):
    label: str
    value: float | int | str
    source: str


class SignalContribution(BaseModel):
    signal: SignalName
    # The raw aggregated value the scorer measured (e.g. summed share-drop magnitude, or a
    # count of low-call / under-served rows). Shown to the DM so they see real numbers.
    raw_value: float
    # `raw_value` mapped to 0..1 via a config-visible normalization basis
    # (`Settings.ranking_norm_caps`): a count/magnitude at or above its cap = 1.0. This is
    # the value used in scoring, so the fixed weights alone control relative influence.
    normalized_value: float
    weight: float  # fixed, visible weight from config
    contribution: float  # normalized_value * weight


class Reason(BaseModel):
    """Structured explainability object attached to every recommendation."""

    summary: str = Field(min_length=1)  # non-empty plain-language reason
    signals: list[SignalContribution] = Field(default_factory=list)
    data_points: list[DataPoint] = Field(default_factory=list)


# --------------------------------------------------- recommendation objects
# Each REQUIRES a `reason` (no default) — Principle II / FR-010.
class RepRanking(BaseModel):
    rep_id: str
    rank: int
    total_score: float
    reason: Reason


class CoachingFocus(BaseModel):
    focus_area: str
    reason: Reason


class AccountBrandContext(BaseModel):
    """Per-(account, brand) business context shown to the DM (FR-007 / I1)."""

    market_share: float
    share_trend: float
    volume: float
    spend: float
    performance: Performance
    opportunity_level: OpportunityLevel
    calls: int
    calls_trend: float


class AccountFocus(BaseModel):
    account_id: str
    brand: Brand  # labeled to the DM via the enum DISPLAY name (e.g. "LILETTA") — FR-007
    context: AccountBrandContext  # per-(account, brand) (I1)
    mismatch_flag: bool  # behaviour-vs-opportunity mismatch for this (account, brand) — FR-008
    reason: Reason


class OpenerSource(StrEnum):
    """Provenance: which already-computed brief section a talking point was built from."""

    priority = "priority"  # the rep's ranking reason (section 1)
    coaching_focus = "coaching_focus"  # section 2
    account_mismatch = "account_mismatch"  # section 4 (a key/mismatched account)
    default = "default"  # positive no-gap default (no high-priority signals)


class TalkingPoint(BaseModel):
    """One point to raise in the opening conversation, SELECTED in code from an upstream
    section output. `ref` records exactly which input it came from (provenance)."""

    text: str
    source: OpenerSource
    ref: str


class Opener(BaseModel):
    text: str  # the LLM-written opening line (placeholder until narrated)
    talking_points: list[TalkingPoint] = Field(default_factory=list)
    reason: Reason


# ------------------------------------------- ride-along prep (section 3 / FR-006)
class NoteSource(StrEnum):
    """Provenance: which guarded path a ride-along item came from."""

    structured_store = "structured_store"  # the data-access structured store
    retriever = "retriever"  # the RBAC + PRP-scrubbed notes retriever


class PriorNote(BaseModel):
    """A prior coaching note (free-text recall via the retriever), with provenance."""

    session_id: str
    date: str
    text: str
    source: NoteSource


class PriorActionItem(BaseModel):
    """An agreed action or a what-to-observe-next item, with its provenance."""

    session_id: str
    date: str
    text: str
    source: NoteSource


class RideAlongPrep(BaseModel):
    """Section 3: prior notes + agreed actions + what to observe next for the selected rep.

    The facts are assembled in code; the LLM writes only `reason.summary` and `opening`.
    """

    rep_id: str
    has_history: bool = True
    prior_notes: list[PriorNote] = Field(default_factory=list)
    agreed_actions: list[PriorActionItem] = Field(default_factory=list)
    observe_next: list[PriorActionItem] = Field(default_factory=list)
    opening: str = Field(
        min_length=1
    )  # LLM-written opening suggestion (placeholder until narrated)
    reason: Reason


class EmptyState(BaseModel):
    """Returned when a rep has no surfaceable coaching history (FR-018) — never fabricated."""

    rep_id: str
    has_history: bool = False
    message: str = Field(min_length=1)
    reason: Reason


# -------------------------------------------- assembled brief (FR-001 / section roll-up)
class GeneratedFor(BaseModel):
    """Who the brief was generated for + their territory scope (audit / display)."""

    user_id: str
    role: Role
    scope_level: ScopeLevel
    scope: str  # the territory the caller is scoped to (district_id / region_id / "all")


class CoachingBrief(BaseModel):
    """The assembled morning brief: the five sections for a selected rep (FR-001). Pure data —
    suggestion only, no action path (FR-011)."""

    brief_id: str
    generated_for: GeneratedFor
    ranked_reps: list[RepRanking]  # section 1 (top N)
    selected_rep_id: str  # the rep the rest of the brief details
    coaching_focus: list[CoachingFocus]  # section 2
    ride_along_prep: RideAlongPrep | EmptyState  # section 3
    accounts: list[AccountFocus]  # section 4
    opener: Opener  # section 5
    synthetic: bool = True  # data provenance label (Principle III)


# ------------------------------------ theme aggregation (Phase 7 / capability #6)
class Theme(BaseModel):
    """One aggregated coaching theme across a set of reps — PATTERNS / COUNTS ONLY.

    STRUCTURAL privacy invariant (FR-016): this object has **no rep-identity field** (no
    `rep_id` / `name`), so an aggregated theme cannot expose a named individual or
    individually identifiable rep detail — it carries only the theme, its counts, and shares.
    The `reason` holds supporting COUNTS (never a list of named reps).
    """

    theme: (
        str  # the focus-area / theme label (from the config catalog — same as the per-rep section)
    )
    signal: SignalName | None = None  # the signal it maps to (None = the no-gap default theme)
    # how many in-scope reps have this theme — `None` when SUPPRESSED (the group is smaller than
    # `Settings.aggregation_min_cell`, so the raw count is withheld for privacy, FR-016).
    rep_count: int | None
    rep_share: float | None  # rep_count / total in-scope reps (0..1); `None` when suppressed
    suppressed: bool = False  # True when the group is too small to report a raw count
    reason: Reason  # supporting counts (no rep identities); summary narrated by the LLM


class ThemeAggregate(BaseModel):
    """An aggregate-only, RBAC-scoped (region / all) leadership view of coaching themes across
    reps (Phase 7 / capability #6). Pure data, suggestion-only. Shows patterns and counts,
    **never named individuals** (FR-016)."""

    generated_for: GeneratedFor
    rep_count: int  # total in-scope reps (the denominator for the shares)
    themes: list[Theme]  # ranked, most common first
    synthetic: bool = True


# -------------------------------------------- Summit optimization (Phase 8 / capability #5)
class SummitTarget(BaseModel):
    """One (account, brand) movement that drives the Summit ranking lift (raw numbers shown)."""

    account_id: str
    brand: Brand
    share_trend: float  # current signed trend (negative = declining)
    projected_share_trend: float  # after the modeled improvement (decline halted -> 0.0)
    decline_reduced: float  # district share-decline magnitude this movement removes


class SummitInsight(BaseModel):
    """Where a rep can focus to move their district's **Summit ranking** the most (capability #5).

    Computed DETERMINISTICALLY in code from a per-team config formula — the LLM never decides the
    lift or the ranking, it only narrates `reason.summary`. Pure data, suggestion-only (FR-011)."""

    rep_id: str
    district_id: str
    team_formula: str  # which per-team formula key was applied (transparency)
    baseline_position: int  # the district's current Summit ranking position (1 = top)
    projected_position: int  # the position after the modeled improvement on the targets
    lift: int  # positions gained (baseline - projected), >= 0
    targets: list[SummitTarget]  # the highest-lift (account, brand) movements to focus on
    reason: Reason  # summary (LLM) + data points (the movements + the ranking change), raw numbers
    synthetic: bool = True


# -------------------------------------------- covariant analysis (Phase 9 / capability #4)
class CovariantVariableFinding(BaseModel):
    """One behavior variable's TRANSPARENT association with the success measure: the success rate
    when the variable is high vs low, with the supporting counts (a plain rate/lift, no model)."""

    variable: str  # the behaviour variable (e.g. "call_activity", "spend_support")
    n_high: int  # (account, brand) rows where the variable is high
    success_rate_high: float  # success rate among those rows (0..1)
    n_low: int  # rows where the variable is low
    success_rate_low: float
    lift: float  # success_rate_high - success_rate_low (positive = associates with success)


class CovariantBlend(BaseModel):
    """The combination of behavior variables with the highest observed success association."""

    variables: list[str]  # the variables that are all true together
    n: int  # rows where all these variables are true (the support)
    success_rate: float  # success rate among those rows (0..1)


class CovariantAnalysis(BaseModel):
    """A simple, TRANSPARENT covariant insight (capability #4): which rep-behavior variables
    associate with the configured success measure, computed DETERMINISTICALLY in code (counts /
    rates / lift — no black-box model), the LLM only narrates `reason.summary`.

    HONESTY: this is a simple association on SYNTHETIC data; a richer covariant model would need
    real data. When there is too little data, `insufficient_data` is true and no association is
    claimed (FR-018). Pure data, suggestion-only (FR-011)."""

    success_measure: str  # human description of the configured success measure (transparency)
    rows_analyzed: int  # total in-scope (account, brand) rows analyzed
    success_rate_overall: float  # overall success rate (0..1)
    variable_findings: list[CovariantVariableFinding]
    optimal_blend: CovariantBlend | None  # the best-associating combination (None if unsupported)
    insufficient_data: bool  # true -> too little data; no association claimed
    reason: Reason  # summary (LLM) + data points (variables, success measure, supporting numbers)
    synthetic: bool = True


# ------------------------------------------- CLOSE capture (Phase 10 / capability #2)
class CloseRecord(BaseModel):
    """A post-ride CLOSE note — the DM's OWN observations recorded after a coaching ride
    (capability #2). The assistant only **records** the human's input; it does not act (FR-011).

    Written through the single data-access door under the **writer's own scope** (writer-scope
    RBAC), and persisted as a coaching note so the EXISTING scoped + PRP-scrubbed readback
    (ride-along prep / retriever) surfaces it next time (ADR 0002) — a note tied to a PRP HCP is
    never surfaced. `author_user_id` / `author_scope_level` are stamped from the authenticated
    `AccessContext` on save (the writer cannot spoof identity)."""

    rep_id: str = Field(min_length=1)  # the rep the ride was with (must be in the writer's scope)
    # The note's unique id (also the persisted note's primary key). Defaults to a fresh unique id
    # so two CLOSE records can NEVER collide / cross-contaminate; tests may inject a fixed id for
    # determinism. Never a derived/reused value.
    session_id: str = Field(default_factory=lambda: f"close_{uuid4().hex}", min_length=1)
    date: str = Field(min_length=1)  # when it was recorded (ISO timestamp)
    observations: str = Field(min_length=1)  # the DM's free-text observations (the note body)
    agreed_actions: list[str] = Field(default_factory=list)
    observe_next: list[str] = Field(default_factory=list)
    account_id: str | None = None  # the account/HCP discussed, if any (PRP scrubbing on readback)
    author_user_id: str = ""  # stamped from the writer's AccessContext on save
    author_scope_level: ScopeLevel | None = None  # stamped from the writer's AccessContext on save
    synthetic: bool = True


# ------------------------------------------------------- synthetic dataset
class GenerationMeta(BaseModel):
    seed: int
    synthetic: bool = True
    source: str = "synthetic"
    counts: dict[str, int] = Field(default_factory=dict)


class Dataset(BaseModel):
    """In-memory synthetic dataset produced by the generator."""

    meta: GenerationMeta
    regions: list[Region] = Field(default_factory=list)
    districts: list[District] = Field(default_factory=list)
    users: list[User] = Field(default_factory=list)
    reps: list[Rep] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    account_brand_metrics: list[AccountBrandMetrics] = Field(default_factory=list)
    call_activity: list[CallActivity] = Field(default_factory=list)
    coaching_sessions: list[CoachingSession] = Field(default_factory=list)
