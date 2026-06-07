"""Data-access layer: the single seam every component reads through.

`interface` defines the abstract contracts; `sqlite_store` is the local MVP
implementation. Swapping to real connectors later is a source change, not a rewrite.
"""

from coach.data_access.interface import AccessContext, DataAccess, Retriever, ScopeError

__all__ = ["AccessContext", "DataAccess", "Retriever", "ScopeError"]
