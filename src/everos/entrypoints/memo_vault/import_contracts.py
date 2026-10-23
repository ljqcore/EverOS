"""Shared Vault import contracts, independent of parser and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PARSER_VERSION = "generic-1"
DEEPSEEK_HARNESS_PARSER_VERSION = "deepseek-harness-v4-2"

class ImportWorkflowError(ValueError):
    """Expected user-facing failure in the import workflow."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    conversation_id: str
    ordinal: int
    role: str
    content: str
    timestamp_ms: int | None
    source_message_id: str | None
    content_hash: str
    duplicate: bool = False
    memory_input: bool = True


@dataclass(frozen=True, slots=True)
class ParsedToolEvent:
    conversation_id: str
    ordinal: int
    source_event_id: str
    source_event_seq: int
    event_type: str
    timestamp_ms: int
    turn: int | None
    step: int | None
    call_id: str | None
    tool_name: str | None
    arguments: dict[str, Any] | None
    result_content: list[dict[str, Any]] | None
    result_text: str | None
    is_error: bool | None
    source_event_seqs: tuple[int, ...]
    content_hash: str
    duplicate: bool = False
    source_content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedImport:
    messages: tuple[ParsedMessage, ...]
    conversation_count: int
    duplicate_message_count: int
    tool_call_count: int = 0
    tool_events: tuple[ParsedToolEvent, ...] = ()
    tool_result_count: int = 0
    skipped_event_counts: dict[str, int] | None = None
    warnings: tuple[str, ...] = ()
    parser_version: str = PARSER_VERSION
    duplicate_tool_event_count: int = 0
    source_event_conflict_count: int = 0

    @property
    def message_count(self) -> int:
        return len(self.messages)


