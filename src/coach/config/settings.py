"""Runtime settings, read from environment / configuration.

Constitution VIII: the Bedrock Claude model id is NEVER hard-coded — it is read from
configuration (`BEDROCK_MODEL_ID`). The deterministic ranking weights are also config,
and are deliberately fixed + visible (Principle VI).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# The four explainable ranking signals (Principle VI / FR-002). Weights are fixed and
# visible; defaults are equal. Override via env vars `COACH_WEIGHT_<SIGNAL>` if needed.
SIGNALS = ("declining_share", "low_call_activity", "missed_follow_up", "opportunity_risk")


def _default_weights() -> dict[str, float]:
    return {
        "declining_share": float(os.getenv("COACH_WEIGHT_DECLINING_SHARE", "0.25")),
        "low_call_activity": float(os.getenv("COACH_WEIGHT_LOW_CALL_ACTIVITY", "0.25")),
        "missed_follow_up": float(os.getenv("COACH_WEIGHT_MISSED_FOLLOW_UP", "0.25")),
        "opportunity_risk": float(os.getenv("COACH_WEIGHT_OPPORTUNITY_RISK", "0.25")),
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

    # Fixed, visible ranking weights (deterministic scorer in a later phase consumes these).
    ranking_weights: dict[str, float] = field(default_factory=_default_weights)


def get_settings() -> Settings:
    """Return settings resolved from the current environment."""
    return Settings()
