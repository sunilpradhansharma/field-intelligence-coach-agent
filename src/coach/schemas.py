"""Pydantic schemas: entities, the explainability `Reason` object, recommendation
objects, and the synthetic `Dataset` container.

Validation rules enforced here (from the spec):
- Every recommendation object (RepRanking, CoachingFocus, AccountFocus, Opener) MUST
  carry a non-empty `Reason` (FR-010, Principle II).
- A `Reason.summary` must be non-empty.
"""

from __future__ import annotations

from enum import StrEnum

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

    NOTE: the spelling of "Litella" is UNCONFIRMED and must be finalized before the
    `Brand` enum value and the T021 golden fixture are frozen (see spec Assumptions).
    """

    lupron_peds = "LUPRON PEDS"
    lupron_uro = "LUPRON URO"
    lupron_gyn = "LUPRON GYN"
    synthroid = "Synthroid"
    litella = "Litella"  # spelling unconfirmed — see class docstring


class SignalName(StrEnum):
    declining_share = "declining_share"
    low_call_activity = "low_call_activity"
    missed_follow_up = "missed_follow_up"
    opportunity_risk = "opportunity_risk"


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


class AccountFocus(BaseModel):
    account_id: str
    context: BusinessMetric
    mismatch_flag: bool
    reason: Reason


class Opener(BaseModel):
    text: str
    reason: Reason


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
