"""Shared data shapes used across toolkit + graphs.

Kept intentionally small: graph state should hold IDs and metadata, never
full message bodies (see docs/ARCHITECTURE.md section 4 on checkpointer bloat).
"""

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "important",
    "promotions",
    "social",
    "newsletters",
    "receipts",
    "statements",
    "e_mandate",
    "personal",
    "other",
]


class EmailSummary(BaseModel):
    id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    date: str  # ISO 8601
    label_ids: list[str] = Field(default_factory=list)


class Classification(BaseModel):
    message_id: str
    category: Category
    confidence: float
    reason: str = ""


class BatchClassification(BaseModel):
    results: list[Classification]


class BackupManifest(BaseModel):
    drive_file_id: str
    drive_file_link: str
    message_count: int
    message_ids: list[str]
