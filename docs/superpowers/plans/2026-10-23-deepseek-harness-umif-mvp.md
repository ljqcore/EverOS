# DeepSeek Harness v4 → UMIF → MEMO Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status:** Draft for user review. No implementation is authorized by this document alone.

**Goal:** Import the provided DeepSeek Harness ZIP through a validated UMIF package, then complete the existing Vault candidate-review and Memory Pack flow without bypassing human confirmation.

**Architecture:** The ZIP is an input container. A versioned Harness adapter converts its JSONL events into source-independent UMIF records. A validator checks the package before a Vault projector creates the existing normalized-message/tool-event rows. The existing candidate extraction and approval services consume that projection; a separate future compiler can target EverOS `/memory/add` and `/flush` when its review semantics are agreed.

**Tech Stack:** Python 3.12+, Pydantic 2, FastAPI, SQLite, React/TypeScript. No new package dependency is planned.

**Spec:** `docs/superpowers/UMIF统一中间数据格式与EverOS接入规范.md` (draft 0.1.0), especially §§6–14, 19–21, 23–26, 29–31.

## Global Constraints

- The current source ZIP contains exactly one `session.v4.jsonl` (Harness v4); the Vault currently accepts only a directly uploaded `.jsonl` for this source.
- The Claude manifest lists four ZIPs, and all four are now present under `docs/`. Its manifest alone contains download metadata; the ZIP members contain the actual records. Claude conversion remains a later, separately reviewed adapter task so this first slice can establish the shared UMIF contract with DeepSeek Harness v4.
- The adapter must not write EverOS Markdown, SQLite, or LanceDB directly. Its output is UMIF only.
- System/developer/observer content and tool events must not be recast as user chat; unhandled records need a count and reason.
- Stable IDs, hashes, ordering, and chunk boundaries must be reproducible. Historical timestamps must not silently become import-time timestamps.
- Candidate review remains mandatory before formal EverOS publication. A direct `/memory/add`/`/flush` path must not replace it in this MVP.
- The immutable UMIF package is stored under the Vault data root; import attempts and target IDs are recorded in Vault SQLite. This resolves the spec's open ledger-location question for this MVP, subject to review.

## Review Focus

- A malicious or oversized ZIP must fail before parsing or persisting member content.
- A future Harness version must produce an explicit unsupported-version result rather than losing records.
- Invalid tool arguments must preserve their original text, even when they cannot be decoded as JSON.
- Repeated conversion and repeated import of the same archive must not create different IDs or duplicate approved memory.
- A model/health error during candidate extraction must retain raw evidence and valid UMIF, with a precise failing stage.

## Scope and Data Contract

This first slice covers Harness v4 text messages and structured tool calls/results. The UMIF package contains `manifest.json`, `principals.jsonl`, `sessions.jsonl`, `events.jsonl`, and an import report. `assets.jsonl`, `documents.jsonl`, `memories.jsonl`, feedback, and Agent Case materialization remain later slices. The core package reader/writer and record envelope must permit these optional UMIF record files and discriminators without treating them as chat messages or changing the schema version when the Claude adapter is added. The generic Markdown import must use the same UMIF validator/projector as a regression control.

For each event, retain `schema_version`, `record_type`, `record_id`, `source`, `scope`, `sequence`, `timestamp_ms`, `state`, `provenance`, `payload`, and namespaced `extensions`. Use source IDs where present; otherwise derive IDs from source identity, sequence, and canonical payload. Put volatile import timestamps in the ledger so the same input produces byte-stable core records. Preserve skipped-event counts and safe reasons in the import report.

### Local Claude export findings and effect on this plan

Static inspection of the locally downloaded ZIPs (member names, JSON fields, types, and counts only; no content copied into this plan) found:

| Archive | Export member | Observed records | Future UMIF mapping |
|---|---|---:|---|
| `light_metadata-000.zip` | `users.json`, `login_history.json` | 1 account, 3 login events | Account → Principal alias; login history requires an explicit privacy/routing decision |
| `projects-000.zip` | `projects/<uuid>.json` | 1 project, 1 embedded doc, nonempty `prompt_template` | Project scope; instructions → Document `project_instruction`; embedded doc → Document |
| `memories-000.zip` | `memories/<uuid>.json` | 1 `memory_files` entry | Saved memory → `memory.assertion`, with its own provenance and confirmation; conversion granularity requires review |
| `conversations-000.zip` | `conversations.json` | 1 conversation, 4 messages | Session + Messages; preserve content blocks and parent links |

The conversation's content blocks include text, injected prompts, thinking, 2 tool uses, 2 tool results, and a document reference; one message has a file reference. Three parent links point to a message in this export and one does not. The Claude adapter must handle these observed structures explicitly, including missing parent references and any file payload absent from these four archives. It must not infer tool traces from final text or merge injected prompts/thinking into user chat. These observations correct the former assumption that Claude source records were unavailable; they do not expand this DeepSeek-first delivery into a second importer.

## Planned Files and Tasks

### Task 1: Define and validate the first UMIF slice

**Files:** Create `src/everos/umif/{__init__,models,canonical,package,validator}.py`; create `tests/unit/test_umif/test_models.py`, `test_package.py`, `test_validator.py`.

**Interfaces:** `UmifPackage` contains typed Manifest, Principal, Session, Message, ToolCall and ToolResult records. `write_package(package: UmifPackage, directory: Path) -> None`; `read_package(directory: Path) -> UmifPackage`; `validate_package(package: UmifPackage, directory: Path | None = None) -> ValidationReport`.

- [ ] Define the fixed schema version and typed fields, including `source`, `scope`, `provenance`, `payload`, and extension namespaces.
- [ ] Specify canonical UTF-8 JSON/JSONL serialization and deterministic ID/content-hash rules; tests compare two independent conversions byte for byte.
- [ ] Validate manifest hash/count, duplicate ID/sequence, missing principal/session references, tool-call/result links, and safe blob paths; each failing fixture asserts a stable error code.
- [ ] Keep the package module independent of platform-specific JSON and EverOS persistence imports. Define a versioned extension path for optional `assets.jsonl`, `documents.jsonl`, and `memories.jsonl` so later Claude Document and `memory.assertion` records remain distinct from `event.message`.

### Task 2: Accept the real Harness export container

**Files:** Modify `src/everos/entrypoints/memo_vault/imports.py`, `apps/memo-vault-ui/src/App.tsx`; extend `tests/unit/test_entrypoints/test_deepseek_harness.py`.

**Interfaces:** Define `ImportLimits` in `imports.py` with the existing upload, uncompressed-size, entry-count, and compression-ratio limits. `read_harness_export(payload: bytes, filename: str, limits: ImportLimits) -> bytes` returns the single validated JSONL member; direct `.jsonl` remains supported.

- [ ] Reuse the existing ZIP path, entry-count, decompression-size, compression-ratio, encryption, and special-file checks; require exactly one Harness session JSONL member.
- [ ] Keep the uploaded ZIP bytes as the original evidence, not only the extracted JSONL.
- [ ] Update the UI accepted extensions and user-facing errors for `.zip` and `.jsonl`.
- [ ] Verify the provided ZIP's structure and a malicious/multiple-member fixture without invoking an LLM.

### Task 3: Build the Harness v4 adapter and generic Markdown control

**Files:** Modify `src/everos/entrypoints/memo_vault/{deepseek_harness,imports}.py`; extend `tests/unit/test_entrypoints/test_deepseek_harness.py` and import fixtures.

**Interfaces:** `deepseek_harness.py` exports `detect_export(payload: bytes, filename: str) -> DetectionResult`, `inspect_export(payload: bytes) -> ExportSummary`, and `convert_harness_v4(payload: bytes, project_id: str) -> UmifPackage`. `imports.py` exports `convert_parsed_markdown(parsed: ParsedImport, project_id: str) -> UmifPackage`.

- [ ] Factor the v4 event decoder so conversion can preserve source sequence, IDs, raw tool arguments, and events omitted from today's chat projection.
- [ ] Map session, principals, user/assistant/system messages, calls, results, state, time quality, and source provenance; unknown event types receive explicit report entries.
- [ ] Keep user/assistant text and tool traces distinct. Do not fabricate missing calls or results.
- [ ] Compare conversion of the provided archive and the same extracted JSONL: core record IDs and hashes must match.

### Task 4: Project validated UMIF into the existing Vault workflow

**Files:** Create `src/everos/entrypoints/memo_vault/{import_contracts,umif_projection}.py`; modify `src/everos/entrypoints/memo_vault/{imports,deepseek_harness,storage}.py` and `routes/imports.py`; extend `tests/unit/test_entrypoints/test_memo_vault_imports.py`.

**Interfaces:** Move `ImportWorkflowError`, `ParsedMessage`, `ParsedToolEvent`, and `ParsedImport` to `import_contracts.py`, re-exporting them from `imports.py` for existing callers. `project_for_vault(package: UmifPackage) -> ParsedImport`; the import batch stores the UMIF package reference and validation summary; Vault SQLite records source-record IDs, hashes, stage, target IDs, and last error.

- [ ] Preview: decode source → create UMIF → validate → show counts and skipped reasons without committing an archive.
- [ ] Commit: atomically retain original file, UMIF package, and normalized Vault rows; retry must reuse stable record IDs.
- [ ] Route both Markdown and Harness through this projector; verify the existing Markdown flow's observable behavior remains the same.
- [ ] Preserve structured tool events for future Agent mode; only supported user/assistant messages enter today's candidate extractor.

### Task 5: Make extraction failures diagnosable without changing review semantics

**Files:** Modify `src/everos/entrypoints/memo_vault/{adapter.py,routes/imports.py}`; inspect `src/everos/entrypoints/api/routes/memo_vault_candidates.py` and `src/everos/service/memo_vault_candidates.py`; extend existing route tests.

**Interfaces:** Import status identifies one of `decode`, `umif_validate`, `vault_commit`, `everos_health`, `everos_contract`, `model_boundary`, `model_episode`, `model_preference`, `candidate_persist`, with stable error code and safe summary.

- [ ] Preserve upstream structured errors and stage in the Vault batch/ledger and UI while excluding private message content.
- [ ] Verify that provider errors, invalid structured model output, and candidate persistence failures retain the original archive and UMIF package.
- [ ] Confirm candidates still require review and publication before the memory library or Memory Pack can include them.

### Task 6: End-to-end acceptance and documentation

**Files:** Add redacted fixtures under `tests/fixtures/memo_vault/`; update `docs/project-guide.zh-CN.md`, `docs/memo_vault_candidate_extraction.md`, and relevant API documentation.

- [ ] Verify the supplied Harness ZIP: structural counts → UMIF counts → Vault batch → candidate extraction → confirmation → formal memory query → Markdown Memory Pack export.
- [ ] Verify deterministic repeat import, a partial failure/retry, an orphan tool result, a missing timestamp, and an unsupported log version.
- [ ] Run focused unit/integration checks and a separate live-model acceptance with the configured EverOS service; report each result independently.
- [ ] Document supported record types, reported omissions, data-loss boundaries, and the still-pending Agent Case/Claude adapter work; note that the local Claude archives are available and have been structurally inspected.

## Explicitly Deferred

Claude's four referenced ZIPs are present and expose enough structure for a separate adapter plan after the shared UMIF core is reviewed. That follow-on must map Claude conversations (including observed tool blocks and parent links), project instructions/docs, file references, and saved memories; it must decide how to treat login history, thinking, injected prompts, and unavailable file payloads before implementation. DeepSeek Web export, attachments/Knowledge materialization, platform-native memory materialization, full Agent Case/Skill compilation, and direct `/memory/add`/`/flush` materialization require later reviewed slices. UMIF normalization improves input correctness and fault isolation; it does not by itself repair an Ollama provider or structured-output failure.
