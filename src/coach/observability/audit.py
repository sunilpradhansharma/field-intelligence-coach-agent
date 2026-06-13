"""T014 — audit + privacy-safe logging for the request path (FR-016).

Two jobs:

1. **Field-level data classification.** The constitution treats **rep data as HR-sensitive**
   and **HCP/prescriber data as private** (FR-016). This module is the single source that
   records WHICH fields must never be emitted to a log/audit sink, so callers can't leak them
   by accident.
2. **A privacy-safe audit record builder.** Audit records are built from a fixed **allow-list**
   of safe identifiers/metadata (ids, role, scope level, counts, timing) — never names, raw PII,
   or business metrics. `build_audit_record` REFUSES (raises) any field outside the allow-list,
   so "log only safe metadata" is enforced by construction, not by reviewer discipline.

The API emits one audit record per request that generates a brief (research §8). Production
swaps the logging sink for CloudWatch/structured audit storage behind the same helper.
"""

from __future__ import annotations

import json
import logging

# The dedicated audit logger. The API logs ONLY through this (privacy-safe) path; nothing on
# the request path logs entities, names, or metrics.
AUDIT_LOGGER_NAME = "coach.audit"
_logger = logging.getLogger(AUDIT_LOGGER_NAME)


# --------------------------------------------------------------- field classification (FR-016)
# Rep fields that are HR-sensitive — NEVER logged or serialized into an audit record.
HR_SENSITIVE_REP_FIELDS: frozenset[str] = frozenset({"name", "tenure_months"})

# HCP/account fields that are private (IQVIA-PDRP / prescriber) — NEVER logged.
PRIVATE_HCP_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "market_share",
        "share_trend",
        "volume",
        "spend",
        "performance",
        "opportunity_level",
        "calls",
        "calls_trend",
    }
)

# The ONLY keys that may appear in an audit record: safe identifiers + non-sensitive metadata.
# rep/user ids are opaque identifiers (not names); counts/limits/status are metadata. No name,
# no metric, no free text ever goes here.
SAFE_AUDIT_FIELDS: frozenset[str] = frozenset(
    {
        "event",
        "user_id",
        "role",
        "scope_level",
        "scope",
        "brief_id",
        "selected_rep_id",
        "rep_id",
        "session_id",  # opaque CLOSE-note id (like brief_id/rep_id — not a name or free text)
        "limit",
        "ranked_count",
        "accounts_count",
        "theme_count",  # count of aggregated themes (metadata, no identity)
        "rep_count",  # count of in-scope reps (metadata, no identity)
        "status",
        "synthetic",
    }
)


def build_audit_record(event: str, ctx, **extra: object) -> dict:
    """Build a privacy-safe audit record from an `AccessContext` + safe metadata.

    Only allow-listed keys (`SAFE_AUDIT_FIELDS`) are permitted; any other key RAISES, so a
    caller cannot accidentally log an HR-sensitive rep field or a private HCP field (FR-016).
    """
    bad = [k for k in extra if k not in SAFE_AUDIT_FIELDS]
    if bad:
        raise ValueError(
            f"refusing to audit-log non-allow-listed field(s): {', '.join(sorted(bad))}"
        )
    record: dict[str, object] = {
        "event": event,
        "user_id": ctx.user_id,
        "role": ctx.role.value,
        "scope_level": ctx.scope_level.value,
        "synthetic": True,
    }
    record.update(extra)
    return record


def emit(record: dict) -> None:
    """Emit one audit record (structured JSON) on the audit logger."""
    _logger.info(json.dumps(record, sort_keys=True))


def audit(event: str, ctx, **extra: object) -> dict:
    """Build + emit a privacy-safe audit record in one call. Returns the emitted record."""
    record = build_audit_record(event, ctx, **extra)
    emit(record)
    return record
