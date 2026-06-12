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


def get_settings() -> Settings:
    """Return settings resolved from the current environment."""
    return Settings()
