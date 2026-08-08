"""Graph state schemas.

Deliberately holds IDs and small metadata only - never full message bodies
or API service objects. Fields that come from toolkit/models.py Pydantic
models are stored as plain dicts (via .model_dump()), not model instances:
the checkpointer msgpack-serializes state, and custom types round-trip
through an unregistered-type pickle fallback that LangGraph is deprecating.
Plain dict/list/str/int/float/bool/None keeps checkpoints on the native,
forward-compatible path. Node functions reconstruct the Pydantic model where
they need typed access. See docs/ARCHITECTURE.md section 4.
"""

from typing import Literal, TypedDict


class SortState(TypedDict, total=False):
    account_id: str
    run_id: str
    messages: list[dict]  # EmailSummary.model_dump()
    classifications: dict[str, dict]  # message_id -> Classification.model_dump()
    labeled_count: int


class SweepState(TypedDict, total=False):
    account_id: str
    run_id: str
    candidates: list[dict]  # EmailSummary.model_dump()
    backup_manifest: dict | None  # BackupManifest.model_dump()
    approval_id: str | None
    approval_status: Literal["pending", "approved", "rejected", "expired"] | None
    trashed_count: int
