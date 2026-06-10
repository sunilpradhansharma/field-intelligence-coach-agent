"""LLM provider seam for narration (T024). Claude on Amazon Bedrock; model id from config.

The LLM is used ONLY to write `reason.summary` prose — it never computes or alters ranks,
scores, signal values, or contributors (Principle I/VI, FR-002/FR-012). Tests inject a fake
LLM; the real Bedrock path is lazy (boto3 is imported on first use) so importing this module
needs no AWS credentials.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from coach.config.settings import get_settings


@runtime_checkable
class LLM(Protocol):
    """Narration-only seam: turn a structured reason input into one short prose summary."""

    def narrate(self, reason_input: dict, instruction: str) -> str: ...


class BedrockLLM:
    """Real Claude-on-Bedrock client. Model id comes from config — never hard-coded
    (Constitution VIII). Not exercised by tests; the real call path lives behind `LLM`."""

    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        s = get_settings()
        self.model_id = model_id or s.bedrock_model_id
        self.region = region or s.aws_region
        if not self.model_id:
            raise ValueError("BEDROCK_MODEL_ID is not configured (model id must come from config).")
        self._client = None

    def _bedrock(self):  # pragma: no cover - real AWS path, not unit-tested
        if self._client is None:
            import boto3  # lazy import so the module loads without boto3/credentials

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def narrate(self, reason_input: dict, instruction: str) -> str:  # pragma: no cover
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 200,
                "messages": [
                    {"role": "user", "content": f"{instruction}\n\n{json.dumps(reason_input)}"}
                ],
            }
        )
        resp = self._bedrock().invoke_model(modelId=self.model_id, body=body)
        payload = json.loads(resp["body"].read())
        return payload["content"][0]["text"].strip()
