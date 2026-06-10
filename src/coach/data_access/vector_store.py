"""Vector store seam for the coaching-notes retriever (T011).

A thin interface over a vector index. The MVP uses a deterministic in-memory cosine store
(offline, repeatable — good for tests); production swaps a Chroma / Bedrock Knowledge Bases /
OpenSearch backend behind the same `VectorStore` interface. The retriever (not the store)
applies RBAC + PRP; the store only does similarity + a simple metadata-equality filter.
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    def add(self, id_: str, vector: list[float], metadata: dict) -> None: ...

    def query(
        self, vector: list[float], where: dict | None = None
    ) -> list[tuple[str, float, dict]]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class InMemoryVectorStore:
    """Deterministic in-memory cosine index. Returns ALL `where`-matching items, ranked by
    similarity desc then id asc (stable). The retriever slices top-k AFTER its RBAC/PRP
    filtering, so nothing is dropped before the guards run."""

    def __init__(self) -> None:
        self._items: list[tuple[str, list[float], dict]] = []

    def add(self, id_: str, vector: list[float], metadata: dict) -> None:
        self._items.append((id_, list(vector), dict(metadata)))

    def query(
        self, vector: list[float], where: dict | None = None
    ) -> list[tuple[str, float, dict]]:
        where = where or {}
        hits = [
            (id_, _cosine(vector, vec), meta)
            for id_, vec, meta in self._items
            if all(meta.get(k) == v for k, v in where.items())
        ]
        # Deterministic ranking: score desc, then id asc.
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits
