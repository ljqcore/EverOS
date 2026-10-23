# DeepSeek Harness Session Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import DeepSeek Harness v4 session JSONL into MEMO Vault as normalized user/assistant messages and separately persisted tool-call/result events.

**Architecture:** Add a dedicated v4 JSONL parser that validates the event stream and converts visible chat text plus tool trace records into import models. Extend the existing preview/commit flow and project scoped SQLite store for trace events, while sending only normalized user/assistant messages through the existing EverOS extraction adapter.

**Tech Stack:** Python, FastAPI, SQLite, Pydantic/API envelopes, React, TypeScript, Vite, pytest.

**Spec:** Approved in conversation on 2026-10-21; no separate spec file requested.

## Global Constraints

- Accept direct `.jsonl` session files with DeepSeek Harness `version: 4`; ZIP-contained JSONL is out of scope.
- Set the single-file upload limit to 100 MiB and preserve the preview/commit/cancel lifecycle.
- Never send reasoning blocks, tool-call payloads, or normalized tool events to current memory extraction.
- Keep tool event data project scoped and separate from `normalized_messages`.
- Do not change parsing behavior for existing `.json`, `.md`, `.txt`, or `.zip` imports.

## Review Focus

- Malformed JSONL, unsupported versions, missing/duplicate event sequence numbers must fail before preview data is written; pin with parser and route tests.
- Mixed assistant blocks must import visible text only and exclude reasoning/tool-call blocks; pin with a mixed-block fixture.
- Harness inserted/spliced context must not become duplicate dialogue or extracted profile input; pin with an input fixture containing `agent/inbox/spliced` and marked runtime context.
- Orphan tool results and calls without results must remain inspectable and appear as preview warnings; pin with trace-linking tests.
- Identical message text at distinct source event IDs must remain distinct, while repeated imports of the same source events are recognized; pin with parser, preview, and commit tests.

---

### Task 1: Parse and normalize Harness v4 JSONL

**Files:**
- Create: `src/everos/entrypoints/memo_vault/deepseek_harness.py`
- Modify: `src/everos/entrypoints/memo_vault/imports.py`
- Test: `tests/unit/test_entrypoints/test_deepseek_harness.py`
- Test fixture: `tests/fixtures/memo_vault/deepseek_harness_v4.jsonl` (synthetic and sanitized; do not copy the user's full exported session)

**Interfaces:**
- Produces `parse_deepseek_harness(payload: bytes) -> DeepSeekHarnessImport`.
- `DeepSeekHarnessImport` contains `session_id`, normalized `messages`, normalized `tool_events`, skipped event counts, and parse warnings.
- `ImportService.preview()` accepts `generic` or `deepseek_harness`; the latter requires a `.jsonl` filename and maps to the shared `ParsedImport` representation. Generic imports keep their existing extension rules.

- [ ] **Step 1: Add failing parser tests** for valid v4 headers, user messages, assistant visible text blocks, mixed reasoning/text/tool-call blocks, tool calls/results, timestamp and event order, and repeated identical text with distinct event IDs.
- [ ] **Step 2: Add failing rejection tests** for malformed lines, unsupported versions, missing/duplicate sequence numbers, invalid tool arguments JSON, and files exceeding the 100 MiB upload limit.
- [ ] **Step 3: Implement the dedicated parser**. Read UTF-8 JSONL records; require a v4 session header; order events by `seq`; map `user/message` and `assistant/message` text blocks to messages; map `tool/call` and `tool/result` to trace events; ignore infrastructure events and count them by type. Exclude `agent/inbox/spliced` from dialogue. Exclude narrowly recognized Harness runtime-context/system-reminder user injections from extraction and report their counts.
- [ ] **Step 4: Dispatch only `source_type=deepseek_harness` `.jsonl` uploads to the parser**, add the `.jsonl` media type and extension validation, and keep all existing generic formats on their current code path. Use a stable message source ID derived from session ID, event type, and sequence number; reject a Harness source type with a non-JSONL file.
- [ ] **Step 5: Run focused parser tests**.

Run: `PYTHONPATH=src pytest -c /dev/null --confcutdir=tests/unit/test_entrypoints tests/unit/test_entrypoints/test_deepseek_harness.py -q`

Expected: existing generic import tests pass; Harness parser tests pass; malformed and unsupported JSONL fail with `IMPORT_PARSE_FAILED` or `IMPORT_SECURITY_REJECTED` and include the source line where applicable.

- [ ] **Step 6: Commit** with message `feat: parse DeepSeek Harness v4 sessions`.

### Task 2: Persist tool traces and apply source event deduplication

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/imports.py`
- Modify: `src/everos/entrypoints/memo_vault/storage.py`
- Test: `tests/unit/test_entrypoints/test_deepseek_harness.py`

**Interfaces:**
- Add a normalized tool-event model with `conversation_id`, source sequence, timestamp, turn/step, event type, `call_id`, tool name, arguments/result JSON, error flag, linked source sequences, stable source event ID, content hash, and duplicate flag.
- Persist events in `normalized_tool_events`, keyed by `(batch_id, conversation_id, source_event_id)`; keep these rows separate from `normalized_messages`.

- [ ] **Step 1: Add failing storage and commit tests** for schema initialization on both new and existing vault databases, atomic persistence of messages plus tool events, linked call/result rows, and rollback on a persistence error.
- [ ] **Step 2: Add failing deduplication tests** proving that a repeated source event is duplicate, a source ID with changed content blocks commit with a conflict, and identical text at distinct source IDs is preserved.
- [ ] **Step 3: Add the `normalized_tool_events` schema and migration** with batch foreign key, source event identity, canonical JSON payload fields, content hash, and indexes for conversation order and call ID lookup.
- [ ] **Step 4: Extend preview serialization and commit persistence** to round-trip tool events. For Harness imports, determine repeated events by stable source event ID instead of message-content hash; retain existing generic importer deduplication unchanged. If an event ID already exists with different content, show a conflict and disable commit. Persist messages and trace rows in the same SQLite transaction as the import batch.
- [ ] **Step 5: Run focused persistence and migration tests**.

Run: `PYTHONPATH=src pytest -c /dev/null --confcutdir=tests/unit/test_entrypoints tests/unit/test_entrypoints/test_deepseek_harness.py -q`

Expected: importing into a new or pre-existing vault succeeds; committed trace events are queryable and linked; interrupted commit leaves no partial trace or message rows.

- [ ] **Step 6: Commit** with message `feat: persist DeepSeek Harness tool traces`.

### Task 3: Extend API and UI preview for Harness traces

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/imports.py`
- Modify: `src/everos/entrypoints/memo_vault/routes/imports.py`
- Modify: `apps/memo-vault-ui/src/api.ts`
- Modify: `apps/memo-vault-ui/src/App.tsx`
- Modify: `apps/memo-vault-ui/src/styles.css`
- Test: `tests/unit/test_entrypoints/test_deepseek_harness.py`

**Interfaces:**
- Accept `source_type=deepseek_harness` at `/api/v1/imports/preview`; keep `generic` as the default.
- Extend `ImportPreview` with `tool_result_count`, preview trace events, skipped-event counts, warning summaries, and duplicate trace count.
- Add a DeepSeek Harness source card and pass the selected `source_type` to `previewImport`.

- [ ] **Step 1: Add failing preview API tests** for Harness source selection, message and trace counts, filtered event counts, duplicate source events, orphan call/result warnings, preview cancellation, duplicate whole-file detection, and the 100 MiB upload boundary.
- [ ] **Step 2: Implement preview response fields** using bounded samples (up to 20 messages and 20 trace events), and redact/truncate sensitive-looking values in displayed tool arguments/results without modifying archived trace data.
- [ ] **Step 3: Add the source selection and preview UI**. Display message/tool-call/tool-result/duplicate counts; show trace calls with linked results and errors; show ignored/filtered counts and warnings; retain target project selection and existing commit/cancel controls.
- [ ] **Step 4: Run backend preview tests and frontend build**.

Run: `PYTHONPATH=src pytest -c /dev/null --confcutdir=tests/unit/test_entrypoints tests/unit/test_entrypoints/test_deepseek_harness.py -q`

Expected: preview API fields match the TypeScript contract; existing generic preview UI behavior remains unchanged.

Run: `npm --prefix apps/memo-vault-ui run build`

Expected: TypeScript compilation and Vite production build succeed.

- [ ] **Step 5: Commit** with message `feat: preview DeepSeek Harness traces`.

### Task 4: Verify extraction isolation and document the format

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/routes/imports.py`
- Modify: `apps/memo-vault-ui/src/App.tsx`
- Test: `tests/unit/test_entrypoints/test_deepseek_harness.py`
- Test: `tests/unit/test_entrypoints/test_api/test_routes/test_memo_vault_candidates.py`

**Interfaces:**
- Commit returns the existing import batch contract plus source type and message/duplicate counts; tool events remain available from the imported batch’s trace records.
- Candidate extraction continues to receive only normalized user/assistant messages. No tool event is serialized into the EverOS candidate extraction request in this task.

- [ ] **Step 1: Add a failing integration test** in `test_memo_vault_imports.py` that previews and commits a Harness fixture, invokes candidate extraction, and asserts the request contains only normalized user/assistant messages while trace rows remain persisted.
- [ ] **Step 2: Add edge-case route tests** for all-filtered events, unsupported event types, orphaned tool results, and duplicate commits. Ensure each outcome is visible in preview and does not silently lose trace records.
- [ ] **Step 3: Update the import format guide** in the source-selection UI: describe `.jsonl` v4 support, message/tool trace handling, excluded reasoning/context events, and the 100 MiB limit.
- [ ] **Step 4: Run focused backend tests and frontend build**.

Run: `pytest tests/unit/test_entrypoints/test_memo_vault_imports.py tests/unit/test_entrypoints/test_api/test_routes/test_memo_vault_candidates.py -q`

Expected: chat messages follow the existing extraction path; tool events are not sent to extraction; all focused tests pass.

Run: `npm --prefix apps/memo-vault-ui run build`

Expected: production build succeeds.

- [ ] **Step 5: Commit** with message `test: verify Harness import extraction isolation`.
