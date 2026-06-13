"""Runtime settings, read from environment / configuration.

Constitution VIII: the Bedrock Claude model id is NEVER hard-coded — it is read from
configuration (`BEDROCK_MODEL_ID`). The deterministic ranking weights are also config,
and are deliberately fixed + visible (Principle VI).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from coach.schemas import Role, ScopeLevel

# The four explainable ranking signals (Principle VI / FR-002). Weights are fixed and
# visible; defaults are equal. Override via env vars `COACH_WEIGHT_<SIGNAL>` if needed.
SIGNALS = ("declining_share", "low_call_activity", "missed_follow_up", "opportunity_risk")

# SINGLE SOURCE OF TRUTH for the role → territory scope-level mapping (RBAC, Principle V /
# FR-013). RBAC code scopes by `ScopeLevel`; role NAMES are configured only here, never
# hard-coded across the codebase. All non-rep roles get FULL access within their scope.
ROLE_SCOPE_LEVELS: dict[Role, ScopeLevel] = {
    Role.rep: ScopeLevel.self_,
    Role.district_manager: ScopeLevel.district,
    Role.regional_director: ScopeLevel.region,
    Role.regional_business_executive: ScopeLevel.region,
    Role.head_of_sales: ScopeLevel.all_,
}


def scope_level_for(role: Role) -> ScopeLevel:
    """Resolve a role NAME to its territory scope level (the single config source)."""
    return ROLE_SCOPE_LEVELS[role]


def _default_weights() -> dict[str, float]:
    return {
        "declining_share": float(os.getenv("COACH_WEIGHT_DECLINING_SHARE", "0.25")),
        "low_call_activity": float(os.getenv("COACH_WEIGHT_LOW_CALL_ACTIVITY", "0.25")),
        "missed_follow_up": float(os.getenv("COACH_WEIGHT_MISSED_FOLLOW_UP", "0.25")),
        "opportunity_risk": float(os.getenv("COACH_WEIGHT_OPPORTUNITY_RISK", "0.25")),
        # Phase 8 Summit opportunity — OFF by default (0.0): the four core signals are unchanged
        # until a non-zero weight folds Summit into the SAME normalized rollup (ADR 0001).
        "summit_opportunity": float(os.getenv("COACH_WEIGHT_SUMMIT", "0.0")),
    }


def _default_norm_caps() -> dict[str, float]:
    """Per-signal normalization basis: the raw value at (or above) which a signal saturates
    to 1.0. Each signal's raw aggregate is mapped to 0..1 as `min(raw, cap) / cap` BEFORE its
    weight is applied, so the weights alone control relative influence (no count-style signal
    can dominate a fractional one). Visible + env-overridable; never hard-coded in the scorer.

    Rationale + options: see docs/adr/0001-signal-normalization.md. These default caps are a
    product judgment and are TUNABLE — review/tune them with the business once real output is
    seen (ADR 0001 open follow-up).
    """
    return {
        # summed magnitude of negative share_trend across the rep's (account, brand) rows
        "declining_share": float(os.getenv("COACH_NORM_CAP_DECLINING_SHARE", "3.0")),
        # count of high-opportunity rows with low call activity
        "low_call_activity": float(os.getenv("COACH_NORM_CAP_LOW_CALL_ACTIVITY", "10")),
        # count of coaching sessions with a missed follow-up (2–3 sessions/rep)
        "missed_follow_up": float(os.getenv("COACH_NORM_CAP_MISSED_FOLLOW_UP", "3")),
        # count of (risk OR high-opportunity) under-served rows
        "opportunity_risk": float(os.getenv("COACH_NORM_CAP_OPPORTUNITY_RISK", "10")),
        # Phase 8 Summit: district ranking positions a rep's focus could gain (saturates at cap)
        "summit_opportunity": float(os.getenv("COACH_NORM_CAP_SUMMIT", "3")),
    }


def _default_focus_catalog() -> dict[str, str]:
    """FIXED catalog: which coaching focus area each signal maps to (T027). Visible + tunable.
    The deterministic component picks 1-3 of these by signal strength; the LLM only phrases
    the reason text, it never chooses the focus area."""
    return {
        "declining_share": "Defend and regrow share at key accounts",
        "low_call_activity": "Improve account prioritization and call planning",
        "missed_follow_up": "Follow through on prior agreed coaching actions",
        "opportunity_risk": "Pursue new therapy starts / under-served opportunity",
    }


def _default_focus_thresholds() -> dict[str, float]:
    """Minimum RAW signal value for a focus area to TRIGGER (T027). Visible + env-overridable;
    never hard-coded in the component body."""
    return {
        "declining_share": float(os.getenv("COACH_FOCUS_MIN_DECLINING_SHARE", "0.5")),
        "low_call_activity": float(os.getenv("COACH_FOCUS_MIN_LOW_CALL_ACTIVITY", "1")),
        "missed_follow_up": float(os.getenv("COACH_FOCUS_MIN_MISSED_FOLLOW_UP", "1")),
        "opportunity_risk": float(os.getenv("COACH_FOCUS_MIN_OPPORTUNITY_RISK", "1")),
    }


@dataclass(frozen=True)
class SummitFormula:
    """A per-TEAM Summit scoring formula (Phase 8 / capability #5).

    **PLACEHOLDER coefficients — representative only, NOT a real IC plan.** The business will
    supply each team's real Summit / IC-plan logic; this is an ASSUMPTION to be confirmed (see
    spec.md → Future Capabilities and docs/project-status.md). It is **config-swappable per team
    WITHOUT any code change** — the engine (`components/summit.py`) reads coefficients from here
    and never hard-codes a team's numbers. Applied to a district's aggregated (account, brand)
    inputs to produce a Summit score; districts are then ranked by that score.
    """

    share_weight: float = 100.0  # × mean market share across the district's (account, brand) rows
    volume_weight: float = 0.002  # × total volume
    decline_penalty: float = 40.0  # × total share-decline magnitude (penalizes decline)
    calls_weight: float = 0.5  # × total calls
    # TUNABLE MODELING ASSUMPTION (per team): in the what-if lift, how much of a halted decline
    # is assumed to come back. 1.0 = full recovery (a halted decline is fully regained — the
    # optimistic default); 0.5 = half comes back; 0.0 = no recovery. The business may set a more
    # conservative value per team without any code change.
    recovery_fraction: float = 1.0


def _default_summit_formulas() -> dict[str, SummitFormula]:
    """Per-TEAM Summit formulas (team = district id). `"default"` applies to any team without an
    explicit entry. PLACEHOLDER until the business supplies the real per-team formulas; add or
    override a team's coefficients here (config-only, no engine change). The default
    `recovery_fraction` is env-overridable (`COACH_SUMMIT_RECOVERY_FRACTION`)."""
    return {
        "default": SummitFormula(
            recovery_fraction=float(os.getenv("COACH_SUMMIT_RECOVERY_FRACTION", "1.0"))
        )
    }


@dataclass(frozen=True)
class SuccessMeasure:
    """The covariant analysis (Phase 9 / capability #4) "success" measure.

    **DEFAULT ASSUMPTION to confirm with the business (open question).** Default: a "winning"
    (account, brand) is one with **RISING share AND performance on/above target**. It is tunable
    via config WITHOUT any code change — set `min_share_trend` ("rising" = share_trend strictly
    above this) and whether performance must be on/above target. The analysis engine
    (`components/covariant.py`) never hard-codes a hidden definition; it reads this measure.
    """

    min_share_trend: float = 0.0  # "rising" share = share_trend strictly greater than this
    require_on_or_above_target: bool = True  # performance must be 'on' or 'over'


# Shown when no signal clears its trigger threshold (a low-priority, no-gap default focus).
DEFAULT_FOCUS_AREA = "No high-priority coaching gap — reinforce current strengths"

# The positive talking point used when a rep has no high-priority signals (opener fallback).
DEFAULT_OPENER_POINT = "Reinforce current strengths and confirm the day's goals"

# Ranking-narration wording (T024) — visible + tunable, like DEFAULT_FOCUS_AREA / the opener
# default. The narration is WORDING ONLY; it chooses among these phrases by the ALREADY-COMPUTED
# score / triggered signals and never changes ranks, scores, or signal values.
# Used when a rep has NO triggered signal (score 0 / no coaching gap) — never call such a rep
# "the priority" or imply urgency.
RANKING_NO_GAP_SUMMARY = "No major coaching gap — reinforce current strengths."
# Closing phrases for a rep that DOES have triggered signals, chosen by
# `Settings.ranking_high_priority_threshold` on the normalized 0..1 score.
RANKING_HIGH_PRIORITY_CLOSING = "— a clear priority for a ride-along today."
RANKING_LOW_PRIORITY_CLOSING = "— worth attention on an upcoming ride."


@dataclass(frozen=True)
class Settings:
    """Resolved configuration. No secrets are stored here."""

    # LLM / Bedrock — model id MUST come from config, never hard-coded.
    bedrock_model_id: str | None = field(default_factory=lambda: os.getenv("BEDROCK_MODEL_ID"))
    aws_region: str | None = field(default_factory=lambda: os.getenv("AWS_REGION"))
    bedrock_embed_model_id: str | None = field(
        default_factory=lambda: os.getenv("BEDROCK_EMBED_MODEL_ID")
    )
    # Amazon Transcribe (Phase 10 Step 10b voice capture): the S3 bucket for the recording + job
    # output. Used only by the real `AmazonTranscribe` path (never in tests, which use the fake).
    transcribe_s3_bucket: str | None = field(
        default_factory=lambda: os.getenv("TRANSCRIBE_S3_BUCKET")
    )

    # Local stores (MVP). Production maps these to Aurora/Athena and Bedrock KB/OpenSearch.
    db_path: str = field(default_factory=lambda: os.getenv("COACH_DB_PATH", "./data/coach.db"))

    # Seeded synthetic data — fixed seed makes generation repeatable for tests.
    seed: int = field(default_factory=lambda: int(os.getenv("COACH_SEED", "42")))

    # Fixed, visible ranking weights — the deterministic scorer (T023) consumes these.
    ranking_weights: dict[str, float] = field(default_factory=_default_weights)

    # Per-signal normalization caps (single, visible basis for mapping raw values to 0..1).
    ranking_norm_caps: dict[str, float] = field(default_factory=_default_norm_caps)

    # Ranking thresholds (visible + config-sourced; never hard-coded in the scorer body).
    # A high-opportunity (account, brand) row with calls <= this counts as "low call activity".
    low_call_threshold: int = field(
        default_factory=lambda: int(os.getenv("COACH_LOW_CALL_THRESHOLD", "2"))
    )
    # How many top contributing (account, brand) pairs to list in a rep's reason.
    top_contributors: int = field(
        default_factory=lambda: int(os.getenv("COACH_TOP_CONTRIBUTORS", "3"))
    )
    # Ranking NARRATION threshold (wording only): a rep whose normalized 0..1 score is at or
    # above this is described as "a clear priority"; a rep with triggered signals but a score
    # below it is described as "worth attention". Does NOT affect ranks or scores.
    ranking_high_priority_threshold: float = field(
        default_factory=lambda: float(os.getenv("COACH_RANKING_HIGH_PRIORITY_THRESHOLD", "0.5"))
    )

    # Coaching-focus selection (T027): fixed catalog (signal -> focus area), trigger
    # thresholds (min raw signal value), and how many focus areas to return (1..N).
    focus_catalog: dict[str, str] = field(default_factory=_default_focus_catalog)
    focus_thresholds: dict[str, float] = field(default_factory=_default_focus_thresholds)
    max_focus_areas: int = field(
        default_factory=lambda: int(os.getenv("COACH_MAX_FOCUS_AREAS", "3"))
    )

    # Ride-along prep (T030): how many of the most recent coaching sessions to surface.
    ride_along_max_notes: int = field(
        default_factory=lambda: int(os.getenv("COACH_RIDE_ALONG_MAX_NOTES", "2"))
    )

    # Accounts / business context (T033): how many KEY (account, brand) rows to surface
    # (the focused list, not the whole book), and the behaviour-vs-opportunity mismatch rule
    # threshold — a high-opportunity (account, brand) with calls <= this is flagged (FR-008).
    accounts_max: int = field(default_factory=lambda: int(os.getenv("COACH_ACCOUNTS_MAX", "5")))
    mismatch_call_threshold: int = field(
        default_factory=lambda: int(os.getenv("COACH_MISMATCH_CALL_THRESHOLD", "2"))
    )

    # Opener (T036): how many talking points to include in the suggested opener.
    opener_max_points: int = field(
        default_factory=lambda: int(os.getenv("COACH_OPENER_MAX_POINTS", "3"))
    )

    # Brief assembly (T015): how many ranked reps to show in section 1 (the "top 3–5" list).
    ranked_reps_max: int = field(
        default_factory=lambda: int(os.getenv("COACH_RANKED_REPS_MAX", "5"))
    )

    # Theme aggregation (Phase 7) PRIVACY control: the smallest group size that may be reported
    # as a raw count. Any grouping cell — a theme's total, or a per-district count — whose rep
    # count is BELOW this is SUPPRESSED (masked, never shown as a raw small count), so an
    # aggregate can never identify an individual (e.g. a 1-rep district; FR-016). Visible +
    # env-overridable; it is a tunable privacy control, not a display preference.
    aggregation_min_cell: int = field(
        default_factory=lambda: int(os.getenv("COACH_AGGREGATION_MIN_CELL", "3"))
    )

    # Summit optimization (Phase 8 / capability #5). Per-TEAM (district) scoring formulas — a
    # representative PLACEHOLDER until the business supplies the real per-team logic; swap/extend
    # per team via config, no engine change. The Summit signal is OFF by default (weight 0.0 in
    # `ranking_weights`), so the four-signal ranking is unchanged until it is configured on.
    summit_formulas: dict[str, SummitFormula] = field(default_factory=_default_summit_formulas)
    # How many top declining (account, brand) rows a rep's Summit insight targets.
    summit_max_targets: int = field(
        default_factory=lambda: int(os.getenv("COACH_SUMMIT_MAX_TARGETS", "3"))
    )

    # Covariant analysis (Phase 9 / capability #4). The "success" measure is a labeled DEFAULT
    # ASSUMPTION to confirm (see `SuccessMeasure`). The spend threshold binarizes the
    # 'spend_support' behavior variable (a placeholder proxy for "use of approved assets/spend").
    # The min-rows / min-support guards keep thin data HONEST (no association is claimed below
    # them). All config-visible + env-overridable; none hard-coded in the analysis body.
    success_measure: SuccessMeasure = field(default_factory=SuccessMeasure)
    covariant_spend_threshold: float = field(
        default_factory=lambda: float(os.getenv("COACH_COVARIANT_SPEND_THRESHOLD", "4000"))
    )
    covariant_min_rows: int = field(
        default_factory=lambda: int(os.getenv("COACH_COVARIANT_MIN_ROWS", "8"))
    )
    covariant_min_support: int = field(
        default_factory=lambda: int(os.getenv("COACH_COVARIANT_MIN_SUPPORT", "3"))
    )


def get_settings() -> Settings:
    """Return settings resolved from the current environment."""
    return Settings()
