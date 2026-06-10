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


def get_settings() -> Settings:
    """Return settings resolved from the current environment."""
    return Settings()
