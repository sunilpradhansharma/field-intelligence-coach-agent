"""T010 — embeddings provider seam for the coaching-notes retriever.

Mirrors `llm/client.py`: an interface, a lazy real provider (Amazon Bedrock Titan, model id
from config — never hard-coded; boto3 imported on first use), and a deterministic fake for
tests (no live Bedrock calls). Production swaps the provider behind `EmbeddingProvider`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Protocol, runtime_checkable

from coach.config.settings import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turn texts into fixed-length vectors. Same shape for MVP and production."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class FakeEmbeddings:
    """Deterministic, offline embeddings for tests — a normalized hashed bag-of-words.

    Same text always yields the same vector (uses hashlib, not Python's randomized `hash`),
    so retrieval order is stable across runs. Cosine similarity ~ shared-token overlap.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _tokens(text):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim
            v[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class BedrockEmbeddings:
    """Real Amazon Titan embeddings on Bedrock. Model id comes from config — never
    hard-coded (Constitution VIII). Not exercised by tests; the real path is behind
    `EmbeddingProvider` and imports boto3 lazily so importing this module needs no creds."""

    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        s = get_settings()
        self.model_id = model_id or s.bedrock_embed_model_id
        self.region = region or s.aws_region
        if not self.model_id:
            raise ValueError(
                "BEDROCK_EMBED_MODEL_ID is not configured (model id must come from config)."
            )
        self._client = None

    def _bedrock(self):  # pragma: no cover - real AWS path, not unit-tested
        if self._client is None:
            import boto3  # lazy import

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        out: list[list[float]] = []
        for text in texts:
            resp = self._bedrock().invoke_model(
                modelId=self.model_id, body=json.dumps({"inputText": text})
            )
            out.append(json.loads(resp["body"].read())["embedding"])
        return out
