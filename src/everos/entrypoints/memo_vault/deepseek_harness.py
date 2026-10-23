"""Parser for DeepSeek Harness v4 session event streams."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .imports import ImportWorkflowError


@dataclass(frozen=True, slots=True)
class HarnessMessage:
    role: str
    content: str
    timestamp_ms: int
    source_message_id: str
    memory_input: bool = True


@dataclass(frozen=True, slots=True)
class HarnessToolEvent:
    source_event_id: str
    seq: int
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


@dataclass(frozen=True, slots=True)
class DeepSeekHarnessImport:
    session_id: str
    messages: tuple[HarnessMessage, ...]
    tool_events: tuple[HarnessToolEvent, ...]
    skipped_event_counts: dict[str, int]
    warnings: tuple[str, ...]


def _required_int(value: object, *, field: str, line_number: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportWorkflowError(
            "IMPORT_PARSE_FAILED",
            f"Line {line_number}: {field} must be an integer.",
        )
    return value


def _text_from_blocks(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "".join(
        block["text"]
        for block in value
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ).strip()


def _runtime_context(content: str) -> bool:
    stripped = content.lstrip()
    return stripped.startswith(
        ("Current runtime context.", "<system-reminder>")
    )


def _assistant_final_sequences(events: list[dict[str, Any]]) -> set[int]:
    """Select the last visible, non-tool-call assistant event in each Harness turn.

    Harness turn numbers are the primary grouping key. When absent, assistant
    messages are grouped after the most recent user event. A turn is eligible
    only when its last assistant/message itself contains visible text and no
    tool-call block.
    """
    last_assistant_by_turn: dict[tuple[str, int], tuple[int, bool]] = {}
    fallback_user_seq = -1
    for event in events:
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        seq = event.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            continue
        if event_type == "user/message":
            fallback_user_seq = seq
            continue
        if event_type != "assistant/message":
            continue
        message = data.get("message") if isinstance(data.get("message"), dict) else data
        blocks = message.get("content")
        text = _text_from_blocks(blocks)
        has_tool_call = isinstance(blocks, list) and any(
            isinstance(block, dict) and block.get("type") == "tool-call"
            for block in blocks
        )
        turn = data.get("turn", message.get("turn"))
        key = ("turn", turn) if isinstance(turn, int) and not isinstance(turn, bool) else ("fallback", fallback_user_seq)
        last_assistant_by_turn[key] = (seq, bool(text) and not has_tool_call)
    return {
        seq for seq, eligible in last_assistant_by_turn.values() if eligible
    }


def _json_object(value: object, *, field: str, line_number: int) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ImportWorkflowError(
                "IMPORT_PARSE_FAILED",
                f"Line {line_number}: tool call arguments are not valid JSON.",
            ) from exc
    if not isinstance(value, dict):
        raise ImportWorkflowError(
            "IMPORT_PARSE_FAILED",
            f"Line {line_number}: {field} must be a JSON object.",
        )
    return value


def _optional_int(value: object, *, field: str, line_number: int) -> int | None:
    if value is None:
        return None
    return _required_int(value, field=field, line_number=line_number)


def parse_deepseek_harness(payload: bytes) -> DeepSeekHarnessImport:
    """Validate and normalize a UTF-8 DeepSeek Harness v4 JSONL session."""
    if not payload:
        raise ImportWorkflowError("IMPORT_PARSE_FAILED", "The file is empty.")
    if b"\x00" in payload:
        raise ImportWorkflowError(
            "IMPORT_SECURITY_REJECTED", "Binary content is not allowed in JSONL imports."
        )
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportWorkflowError(
            "IMPORT_SECURITY_REJECTED", "The file must contain valid UTF-8 text."
        ) from exc

    records: list[tuple[int, dict[str, Any]]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ImportWorkflowError(
                "IMPORT_PARSE_FAILED",
                f"Invalid JSON on line {line_number}, column {exc.colno}.",
            ) from exc
        if not isinstance(record, dict):
            raise ImportWorkflowError(
                "IMPORT_PARSE_FAILED", f"Line {line_number} must contain a JSON object."
            )
        records.append((line_number, record))

    if not records:
        raise ImportWorkflowError("IMPORT_PARSE_FAILED", "The JSONL file is empty.")
    header_line, header = records[0]
    if header.get("type") != "session":
        raise ImportWorkflowError(
            "IMPORT_PARSE_FAILED",
            f"Line {header_line}: first record must be a session header.",
        )
    if header.get("version") != 4:
        raise ImportWorkflowError(
            "IMPORT_PARSE_FAILED",
            f"Line {header_line}: unsupported DeepSeek Harness session version; expected 4.",
        )
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ImportWorkflowError(
            "IMPORT_PARSE_FAILED", f"Line {header_line}: session id is required."
        )

    events: list[tuple[int, int, dict[str, Any]]] = []
    seen_sequences: set[int] = set()
    for line_number, record in records[1:]:
        seq = _required_int(record.get("seq"), field="seq", line_number=line_number)
        if seq in seen_sequences:
            raise ImportWorkflowError(
                "IMPORT_PARSE_FAILED",
                f"Line {line_number}: duplicate event seq {seq}.",
            )
        seen_sequences.add(seq)
        timestamp = _required_int(
            record.get("time"), field="time", line_number=line_number
        )
        events.append((seq, line_number, record))
    events.sort(key=lambda item: item[0])
    final_assistant_seqs = _assistant_final_sequences(
        [record for _, _, record in events]
    )

    messages: list[HarnessMessage] = []
    tool_events: list[HarnessToolEvent] = []
    skipped: Counter[str] = Counter()
    warnings: list[str] = []
    for seq, line_number, event in events:
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(event_type, str) or not isinstance(data, dict):
            raise ImportWorkflowError(
                "IMPORT_PARSE_FAILED",
                f"Line {line_number}: event type and data object are required.",
            )
        timestamp = event["time"]
        timestamp_ms = int(timestamp)
        source_event_id = f"{session_id}:{event_type}:{seq}"

        if event_type in {"user/message", "assistant/message"}:
            role = "user" if event_type == "user/message" else "assistant"
            message = data.get("message") if isinstance(data.get("message"), dict) else data
            content = _text_from_blocks(message.get("content"))
            if not content:
                skipped["empty_visible_message"] += 1
                continue
            if role == "user" and _runtime_context(content):
                skipped["harness_runtime_context"] += 1
                continue
            messages.append(
                HarnessMessage(
                    role=role,
                    content=content,
                    timestamp_ms=timestamp_ms,
                    source_message_id=source_event_id,
                    memory_input=role == "user" or seq in final_assistant_seqs,
                )
            )
            continue

        if event_type == "agent/inbox/spliced":
            skipped[event_type] += 1
            continue

        if event_type == "tool/call":
            call_id = data.get("callId")
            tool_name = data.get("name")
            if not isinstance(call_id, str) or not call_id:
                raise ImportWorkflowError(
                    "IMPORT_PARSE_FAILED", f"Line {line_number}: tool call id is required."
                )
            if not isinstance(tool_name, str) or not tool_name:
                raise ImportWorkflowError(
                    "IMPORT_PARSE_FAILED", f"Line {line_number}: tool name is required."
                )
            arguments = _json_object(
                data.get("arguments"), field="arguments", line_number=line_number
            )
            tool_events.append(
                HarnessToolEvent(
                    source_event_id=source_event_id,
                    seq=seq,
                    event_type=event_type,
                    timestamp_ms=timestamp_ms,
                    turn=_optional_int(data.get("turn"), field="turn", line_number=line_number),
                    step=_optional_int(data.get("step"), field="step", line_number=line_number),
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    result_content=None,
                    result_text=None,
                    is_error=None,
                    source_event_seqs=(),
                )
            )
            continue

        if event_type == "tool/result":
            message = data.get("message")
            if not isinstance(message, dict):
                raise ImportWorkflowError(
                    "IMPORT_PARSE_FAILED", f"Line {line_number}: tool result message is required."
                )
            call_id = message.get("toolCallId")
            content = message.get("content")
            if not isinstance(content, list) or not all(
                isinstance(block, dict) for block in content
            ):
                raise ImportWorkflowError(
                    "IMPORT_PARSE_FAILED", f"Line {line_number}: tool result content must be an array."
                )
            source_event_seqs = event.get("sourceEventSeqs", [])
            if not isinstance(source_event_seqs, list):
                raise ImportWorkflowError(
                    "IMPORT_PARSE_FAILED", f"Line {line_number}: sourceEventSeqs must be an array."
                )
            normalized_source_seqs = tuple(
                _required_int(value, field="sourceEventSeqs item", line_number=line_number)
                for value in source_event_seqs
            )
            is_error = message.get("isError")
            if is_error is not None and not isinstance(is_error, bool):
                raise ImportWorkflowError(
                    "IMPORT_PARSE_FAILED", f"Line {line_number}: isError must be boolean."
                )
            tool_events.append(
                HarnessToolEvent(
                    source_event_id=source_event_id,
                    seq=seq,
                    event_type=event_type,
                    timestamp_ms=timestamp_ms,
                    turn=None,
                    step=None,
                    call_id=call_id if isinstance(call_id, str) else None,
                    tool_name=None,
                    arguments=None,
                    result_content=content,
                    result_text=_text_from_blocks(content),
                    is_error=is_error,
                    source_event_seqs=normalized_source_seqs,
                )
            )
            continue

        skipped[event_type] += 1

    calls_by_id = {
        event.call_id: event
        for event in tool_events
        if event.event_type == "tool/call" and event.call_id is not None
    }
    results_by_id: Counter[str] = Counter(
        event.call_id
        for event in tool_events
        if event.event_type == "tool/result" and event.call_id is not None
    )
    for event in tool_events:
        if event.event_type == "tool/result" and event.call_id not in calls_by_id:
            warnings.append(f"Tool result at seq {event.seq} has no matching call.")
        if event.event_type == "tool/call" and not results_by_id[event.call_id or ""]:
            warnings.append(f"Tool call at seq {event.seq} has no matching result.")

    return DeepSeekHarnessImport(
        session_id=session_id,
        messages=tuple(messages),
        tool_events=tuple(tool_events),
        skipped_event_counts=dict(skipped),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True, slots=True)
class DetectionResult:
    supported: bool
    source_type: str | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExportSummary:
    session_id: str
    version: int
    event_counts: dict[str, int]


def detect_export(payload: bytes, filename: str) -> DetectionResult:
    """Classify a raw Harness v4 JSONL stream, after ZIP member selection."""
    if not filename.lower().endswith(".jsonl"):
        return DetectionResult(False, None, "Unsupported file extension")
    try:
        header = json.loads(payload.splitlines()[0])
    except (IndexError, ValueError):
        return DetectionResult(False, None, "Invalid JSONL header")
    if not isinstance(header, dict) or header.get("type") != "session":
        return DetectionResult(False, None, "Missing session header")
    if header.get("version") != 4:
        return DetectionResult(False, None, "Unsupported Harness session version")
    return DetectionResult(True, "deepseek_harness")


def _decoded_events(payload: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from .imports import ImportWorkflowError
    if not payload or b"\x00" in payload:
        raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Empty or binary Harness session.")
    try:
        lines = payload.decode("utf-8-sig").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness session is not valid UTF-8 JSONL.") from exc
    if not records or not isinstance(records[0], dict) or records[0].get("type") != "session":
        raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness session header is missing.")
    if records[0].get("version") != 4:
        raise ImportWorkflowError("IMPORT_VERSION_UNSUPPORTED", "Unsupported Harness session version.")
    if not isinstance(records[0].get("id"), str) or not records[0]["id"]:
        raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness session ID is missing.")
    seen: set[int] = set()
    events = []
    for record in records[1:]:
        if not isinstance(record, dict) or not isinstance(record.get("seq"), int) or isinstance(record.get("seq"), bool):
            raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness event sequence is invalid.")
        if record["seq"] in seen:
            raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Duplicate Harness event sequence.")
        seen.add(record["seq"])
        if not isinstance(record.get("type"), str) or not isinstance(record.get("data"), dict):
            raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness event type or data is invalid.")
        if record.get("time") is not None and (
            not isinstance(record["time"], int)
            or isinstance(record["time"], bool)
            or not 0 <= record["time"] <= 253402300799999
        ):
            raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness timestamp is invalid.")
        if "sourceEventSeqs" in record and (
            not isinstance(record["sourceEventSeqs"], list)
            or any(not isinstance(value, int) or isinstance(value, bool)
                   for value in record["sourceEventSeqs"])
        ):
            raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness sourceEventSeqs is invalid.")
        events.append(record)
    return records[0], sorted(events, key=lambda event: event["seq"])


def inspect_export(payload: bytes) -> ExportSummary:
    header, events = _decoded_events(payload)
    return ExportSummary(header["id"], 4, dict(Counter(event["type"] for event in events)))


def convert_harness_v4(payload: bytes, project_id: str):
    """Convert source events to UMIF; never emit EverOS or Vault rows here."""
    import hashlib
    from datetime import UTC, datetime
    from everos.umif.canonical import content_hash, record_id
    from everos.umif.models import Manifest, Message, Principal, Session, ToolCall, ToolResult, UmifPackage
    from everos.umif.package import seal_package
    header, source_events = _decoded_events(payload)
    final_assistant_seqs = _assistant_final_sequences(source_events)
    session_native_id = header["id"]
    source_base = {"provider": "deepseek_harness", "product": "deepseek-harness", "export_version": "4"}
    scope = {"workspace_id": "personal", "project_id": project_id, "session_id": None, "branch_id": "main"}
    def make(cls, native_type, native_id, seq, timestamp, body, *, actor_scope=None, routing=None, extensions=None):
        source = {**source_base, "native_type": native_type, "native_id": native_id}
        ts = timestamp if isinstance(timestamp, int) and not isinstance(timestamp, bool) else None
        return cls(record_id=record_id("deepseek_harness", native_type, native_id), source=source,
                   scope=actor_scope or scope, sequence=seq, timestamp_ms=ts,
                   occurred_at=datetime.fromtimestamp(ts / 1000, UTC).isoformat().replace("+00:00", "Z") if ts is not None else None,
                   provenance={"adapter": "deepseek-harness-adapter", "adapter_version": "1.1.0", "content_sha256": content_hash(body), "time_quality": "source" if ts is not None else "unknown"},
                   routing_hints=routing or {}, payload=body, extensions=extensions or {})
    user_id = record_id("deepseek_harness", "principal", "user")
    agent_id = record_id("deepseek_harness", "principal", "agent")
    principals = [make(Principal, "principal", "user", 0, None, {"principal_id": user_id, "kind": "person"}),
                  make(Principal, "principal", "agent", 1, None, {"principal_id": agent_id, "kind": "agent"})]
    session_id = record_id("deepseek_harness", "session", session_native_id)
    session = make(Session, "session", session_native_id, 0, None, {"session_id": session_id, "session_kind": "agent_run", "native_session_id": session_native_id})
    event_scope = {**scope, "session_id": session_id}
    events = []
    skipped: Counter[str] = Counter()
    warnings = []
    tool_names = sorted({e["data"].get("name") for e in source_events if e["type"] == "tool/call" and isinstance(e["data"].get("name"), str)})
    tools = {name: record_id("deepseek_harness", "principal", "tool:" + name) for name in tool_names}
    principals.extend(make(Principal, "principal", "tool:" + name, i + 2, None, {"principal_id": pid, "kind": "tool", "name": name}) for i, (name, pid) in enumerate(tools.items()))
    additional_roles = sorted({e["type"].split("/", 1)[0] for e in source_events
                               if e["type"] in {"system/message", "developer/message", "observer/message"}})
    role_principals = {role: record_id("deepseek_harness", "principal", role) for role in additional_roles}
    first_role_sequence = len(principals)
    principals.extend(make(Principal, "principal", role, i + first_role_sequence, None,
                           {"principal_id": pid, "kind": role})
                      for i, (role, pid) in enumerate(role_principals.items()))
    calls: dict[str, str] = {}
    for event in source_events:
        typ, data, seq = event["type"], event["data"], event["seq"]
        stamp = event.get("time")
        native_id = f"{session_native_id}:{typ}:{seq}"
        if typ in {"user/message", "assistant/message", "system/message", "developer/message", "observer/message"}:
            role = typ.split("/", 1)[0]
            message = data.get("message") if isinstance(data.get("message"), dict) else data
            body_text = _text_from_blocks(message.get("content"))
            if not body_text:
                skipped["empty_visible_message"] += 1
                continue
            if role == "user" and _runtime_context(body_text):
                skipped["harness_runtime_context"] += 1
                continue
            body = {"message_id": native_id, "author_principal_id": user_id if role == "user" else agent_id if role == "assistant" else role_principals[role],
                    "role": role, "content_parts": [{"type": "text", "text": body_text}]}
            memory_allowed = role == "user" or (
                role == "assistant" and seq in final_assistant_seqs
            )
            events.append(make(Message, "message", native_id, seq, stamp, body, actor_scope=event_scope,
                               routing={"user_memory": "allow" if memory_allowed else "deny"},
                               extensions={"deepseek_harness": {"event_type": typ}}))
            continue
        if typ == "tool/call":
            call_id, name = data.get("callId"), data.get("name")
            if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                from .imports import ImportWorkflowError
                raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness tool call ID or name is missing.")
            raw = data.get("arguments")
            raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            try: decoded = json.loads(raw_text)
            except (ValueError, TypeError): decoded = None
            arguments = decoded if isinstance(decoded, dict) else None
            body = {"call_id": call_id, "agent_principal_id": agent_id, "tool_principal_id": tools[name],
                    "tool_name": name, "arguments_text": raw_text, "arguments": arguments,
                    "turn": data.get("turn"), "step": data.get("step"), "status": "requested"}
            calls[call_id] = native_id
            events.append(make(ToolCall, "tool_call", native_id, seq, stamp, body, actor_scope=event_scope,
                               routing={"user_memory": "deny", "agent_memory": "allow"}))
            continue
        if typ == "tool/result":
            message = data.get("message")
            if not isinstance(message, dict):
                from .imports import ImportWorkflowError
                raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness tool result message is missing.")
            blocks = message.get("content")
            if not isinstance(blocks, list) or not all(isinstance(block, dict) for block in blocks):
                from .imports import ImportWorkflowError
                raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness tool result content is invalid.")
            call_id = message.get("toolCallId")
            if call_id is not None and (not isinstance(call_id, str) or not call_id):
                from .imports import ImportWorkflowError
                raise ImportWorkflowError("IMPORT_PARSE_FAILED", "Harness tool result call ID is invalid.")
            body = {"call_id": call_id, "tool_principal_id": None, "status": "error" if message.get("isError") else "completed",
                    "is_error": message.get("isError"), "content_parts": blocks, "result_text": _text_from_blocks(blocks),
                    "source_event_seqs": event.get("sourceEventSeqs", [])}
            events.append(make(ToolResult, "tool_result", native_id, seq, stamp, body, actor_scope=event_scope,
                               routing={"user_memory": "deny", "agent_memory": "allow"}))
            if call_id not in calls: warnings.append(f"Tool result at seq {seq} has no matching call.")
            continue
        skipped[typ] += 1
    for call_id, native_id in calls.items():
        if not any(isinstance(e, ToolResult) and e.payload.get("call_id") == call_id for e in events):
            warnings.append(f"Tool call {native_id} has no matching result.")
    manifest = Manifest(package_id=record_id("deepseek_harness", "package", session_native_id + ":" + project_id),
                        generator={"name": "everos-umif", "version": "0.1.0"},
                        source_exports=[{**source_base, "session_id": session_native_id, "content_sha256": "sha256:" + hashlib.sha256(payload).hexdigest()}],
                        default_scope={"workspace_id": "personal", "project_id": project_id}, files=[],
                        privacy={"classification": "private", "contains_personal_data": True})
    return seal_package(UmifPackage(manifest=manifest, principals=tuple(principals), sessions=(session,), events=tuple(events),
                                    import_report={"skipped_event_counts": dict(skipped),
                                                   "skipped_event_reasons": {kind: "runtime_context" if kind == "harness_runtime_context" else "empty_visible_text" if kind == "empty_visible_message" else "not_in_first_slice" for kind in skipped},
                                                   "warnings": warnings}))
