# MEMO Vault Memory Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a real Memory Pack preview, selection, copy, and download flow for confirmed EverOS memories across all six current memory kinds.

**Architecture:** Keep EverOS as the canonical memory body source and the Vault `memories` table as the confirmation and policy allowlist. Add a focused `MemoryPackService` that consumes canonical records through `MemoVaultLibraryService`, applies status, `external_use`, evidence, and budget rules, and renders Markdown or `vault-memory/1` JSON. The existing exports API and SQLite export log provide the interface and audit boundary; the React page handles configuration and final user confirmation.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, React 19, TypeScript, Vite.

**Spec:** Approved in-chat design from 2026-10-21. Per the user's instruction, this plan is written directly without a separate spec document.

## Global Constraints

- EverOS is the only source of formal memory content; the Vault confirmed-memory registry is the allowlist.
- Pending, rejected, unregistered, withdrawn, deleted, expired, and `external_use=deny` memories never enter an export.
- Validate every requested namespace against an existing Vault project; a project selection never implies its child projects.
- Read only user-owned memories pinned to the Vault `app_id`, `user_id`, and selected `project_id`; do not export Agent-owned memories.
- Expose all six current kinds in the type filter: `preference`, `fact`, `decision`, `todo`, `episode`, and `profile`. Default to all six selected.
- MVP formats are Markdown and `vault-memory/1` JSON. Do not enable OKF.
- `external_use=allow` is selected by default; `ask` is opt-in per item and requires confirmation on every copy/download; `deny` cannot be selected.
- Evidence defaults to ID references. Evidence quotes are optional, separately identified, and never expand to the full source conversation.
- The token estimate is explicitly approximate and includes each rendered item plus its selected evidence text. Budget selection omits whole items and never silently truncates content. Preserve the V3 order `decision → preference → fact → todo`; place `episode` and `profile` after those kinds, then sort within each kind by newest first.
- Do not persist exported memory bodies or write them to ordinary logs. Store only export metadata, selected IDs/revisions, confirmations, format, timestamp, and content hash.
- Keep this local-first and single-user. Add no new memory backend or external dependency.

## Review Focus

- A memory ID from a different project must not be returned, and the response must not reveal whether that ID exists elsewhere.
- A selected Profile memory must contain only the candidate-linked Profile entry returned by the current library mapping, not the aggregate Profile record.
- `external_use=ask` must stay excluded unless explicitly selected and reconfirmed for the current delivery action.
- A status, revision, canonical body, or selection change between preview and export must produce a stale-preview response instead of a different download.
- EverOS offline or a confirmed ID missing from the index must not cause the exporter to fall back to candidate text or fabricate a memory.

## File Map

- Modify `src/everos/entrypoints/memo_vault/library.py`: expose full canonical, confirmed memory sources and evidence references for the pack service.
- Modify `src/everos/entrypoints/memo_vault/contracts.py`: complete typed preview and export request/response contracts and support all six kinds.
- Create `src/everos/entrypoints/memo_vault/memory_pack.py`: pure selection, eligibility, budget, evidence, rendering, and hash logic.
- Modify `src/everos/entrypoints/memo_vault/routes/exports.py`: connect `/packs/preview` and `/packs/export` to the service and translate stable errors.
- Modify `src/everos/entrypoints/memo_vault/storage.py`: add an idempotent migration for export audit metadata and a helper that records no body text.
- Modify `src/everos/entrypoints/memo_vault/routes/system.py`: mark Memory Pack ready only after the full path is available.
- Modify `apps/memo-vault-ui/src/api.ts`: define Pack types and preview/export API calls.
- Modify `apps/memo-vault-ui/src/App.tsx`: replace the Memory Pack placeholder with the working UI flow.
- Modify `apps/memo-vault-ui/src/styles.css`: add the two-column preview/configuration layout and responsive behavior.
- Add backend tests under `tests/unit/test_entrypoints/` and `tests/unit/test_entrypoints/test_api/test_routes/` for the source projection, renderer, and API rules.

## Interfaces

### Library source projection

Add `MemoVaultLibraryService.list_pack_sources(project_id: str) -> list[PackSourceMemory]` in `library.py`. The caller invokes it separately for each selected project; it validates each project before contacting EverOS, uses only confirmed Vault rows, joins canonical EverOS bodies through the existing adapter, and returns lifecycle/expiry/policy metadata plus available evidence. Missing canonical records are represented as unavailable; Vault candidate text is never used as a body fallback.

`PackSourceMemory` contains the Vault and EverOS IDs, project/namespace, kind, memory type, revision, canonical content when available, EverOS timestamp, candidate `created_at` as recorded time, Vault `confirmed_at`, external-use policy, validity/lifecycle status, evidence kind, canonical content hash, and evidence references.

The current `candidate_evidence` table has no standalone evidence ID. Generate a stable reference as `ev_` plus the first 24 hex characters of SHA-256 over the NUL-separated candidate ID, message ID, character start/end, and stored quote hash. Return the source message ID, matched excerpt from the current library evidence mapping, stored quote hash, and source availability with it so the reference is derived from stored provenance rather than invented content. `snippet` uses a shortened matched excerpt; `full` uses the entire matched excerpt returned by `select_evidence_excerpt`, never the complete archived message or conversation.

### Memory Pack contracts

- `PackPreviewRequest`: `namespaces: list[str]`, `kinds: list[MemoryKind]` (all six; default all), `format: Literal["markdown", "vault-memory/1"]`, `token_budget: int` (100–32000, default 4000), `evidence_mode: Literal["none", "id", "snippet", "full"]` (default `id`), and `memory_ids: list[str] | None`. `None` means include eligible `allow` items by default and leave `ask` items out; a supplied list is the exact per-export selection.
- `PackPreviewData`: rendered preview text, `generated_at`, `preview_sha256`, an `items` list for every eligible `allow`/`ask` row (ID, revision, kind, namespace, policy, display content, included flag, and exclusion reason), selected `ask` IDs, exclusion counts/reasons, included count, estimated token count, and budget. Never return denied-body text; show only its count/reason.
- `PackExportRequest`: the same selection settings with an explicit `memory_ids` list, `preview_sha256`, `preview_generated_at`, `confirmed_ask_ids`, `confirm_evidence`, `confirm_unrecoverable_transfer`, and `delivery_action: Literal["copy", "download"]`.
- `PackExportData`: exported content, matching SHA-256, format, generated time, included IDs/revisions, included count, and estimated token count.
- `MemoryPackService.preview(request: PackPreviewRequest, sources: list[PackSourceMemory]) -> PackPreviewData` builds from current source records. `MemoryPackService.export(request: PackExportRequest, sources: list[PackSourceMemory]) -> PackExportData` rebuilds and verifies the exact preview hash before returning content. The route records audit metadata only after this succeeds.
- API routes remain `POST /api/v1/packs/preview` and `POST /api/v1/packs/export`, wrapped in the normal `ApiEnvelope`.

### Frontend contracts

- Add `PackKind`, `PackPreview`, and export response types in `api.ts`; all kind values match the backend six-kind literal.
- Add `previewMemoryPack(request, signal?)` and `exportMemoryPack(request)` helpers. The UI creates a Blob for download and uses Clipboard API for copy only after the server accepts the final confirmation.

---

### Task 1: Expose canonical Pack source records through the Library boundary

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/library.py`
- Test: `tests/unit/test_entrypoints/test_memo_vault_pack_sources.py`

**Interfaces:**
- Consumes: `VaultStore`, `EverOSAdapter`, `_confirmed_rows`, `_canonical_records`, `_evidence`, current project validation, and expiry/lifecycle rules.
- Produces: `PackSourceMemory` and `MemoVaultLibraryService.list_pack_sources(project_id: str) -> list[PackSourceMemory]`.

- [ ] **Step 1: Add source projection tests**

  Cover confirmed rows only; canonical EverOS body wins when it differs from candidate text; every returned row is pinned to the selected project and Vault identity; six `kind` values survive mapping; Profile output is candidate-linked; active missing-index rows have no body; withdrawn/deleted rows have no exportable body; and `ask`/`deny` are represented as policy metadata.

- [ ] **Step 2: Run the source projection tests and confirm the missing behavior**

  Run: `pytest tests/unit/test_entrypoints/test_memo_vault_pack_sources.py -q`
  Expected: new source-projection assertions fail before implementation.

- [ ] **Step 3: Add the typed Pack source record and `list_pack_sources`**

  Validate the project before EverOS access. Fetch only through the existing adapter with persisted `app_id`, `user_id`, and that project ID. Use the confirmed registry as the allowlist, select `c.created_at` for the recorded time, preserve all six kinds, derive expiry from `valid_until`, and keep candidate text out of returned content fields.

- [ ] **Step 4: Add deterministic evidence references**

  Extend the existing evidence mapping to return `evidence_id`, message ID, matched excerpt, stored quote hash, and availability. Derive the ID from the persisted evidence key and `quote_sha256` as defined above; do not add a new random ID or schema column. Reuse the current canonical-content matching behavior so stale or unrelated quotes are not exported.

- [ ] **Step 5: Run the source projection tests**

  Run: `pytest tests/unit/test_entrypoints/test_memo_vault_pack_sources.py -q`
  Expected: PASS, including scope isolation and candidate-text exclusion cases.

---

### Task 2: Implement Pack policy, budgeting, and serialization

**Files:**
- Create: `src/everos/entrypoints/memo_vault/memory_pack.py`
- Modify: `src/everos/entrypoints/memo_vault/contracts.py`
- Test: `tests/unit/test_entrypoints/test_memo_vault_memory_pack.py`

**Interfaces:**
- Consumes: Task 1's `PackSourceMemory` and the request models in the Interfaces section.
- Produces: `MemoryPackService.preview(request, sources)`, `MemoryPackService.export(request, sources)`, `PackPreviewData`, `PackExportData`, stable eligibility decisions, renderers, estimates, and content hashes. This service stays independent of SQLite writes.

- [ ] **Step 1: Add policy and renderer tests**

  Cover all six kinds, Markdown and JSON schema tags, stable ordering, active/expired/lifecycle filtering, `allow` defaults, `ask` opt-in and visibility in the choice list, `deny` exclusion without denied content, missing canonical rows, all four evidence modes, exact quote references, whole-item budget omission with smaller later items considered, and deterministic hashes for the same generated timestamp and source revisions.

- [ ] **Step 2: Run the renderer tests and confirm the missing behavior**

  Run: `pytest tests/unit/test_entrypoints/test_memo_vault_memory_pack.py -q`
  Expected: new policy/format assertions fail before implementation.

- [ ] **Step 3: Define all-six-kind request and response models**

  Extend `PackPreviewRequest.kinds` to `preference | fact | decision | todo | episode | profile`, default all six, and retain the existing format, evidence, budget, and memory ID fields. Add typed preview/export response models and an export request with explicit final confirmations.

- [ ] **Step 4: Implement eligibility, selection, and deterministic ordering**

  Treat `memory_ids=None` as all eligible `allow` items; an explicit list is exact. Keep `ask` out unless selected and never admit `deny`. Select only active, unexpired rows with a canonical EverOS body. Return every eligible `allow`/`ask` choice in `PackPreviewData.items` so the UI can list and toggle it; return no denied content. Reject selected IDs outside the requested projects with a generic `PACK_SELECTION_INVALID` error. Order kinds as `decision`, `preference`, `fact`, `todo`, `episode`, `profile`; sort each kind newest first.

- [ ] **Step 5: Implement budget estimation and evidence modes**

  Use the prototype estimate `120 + Σ(2 * len(rendered_item_block) + 12)` and label it approximate; each rendered block includes memory content, exported evidence text/IDs, and per-item metadata. Respect the 100–32000 budget range. Walk the priority-sorted list and include an item only when its complete estimate fits; if an item does not fit, mark it over budget and continue, so a smaller later item can still fit. Never truncate text. Default evidence mode is `id`. `snippet` uses a shortened matched excerpt; `full` uses the full matched excerpt from `select_evidence_excerpt`, never the complete source message.

- [ ] **Step 6: Implement Markdown and `vault-memory/1` JSON renderers**

  Include only selected and policy-eligible canonical bodies. Markdown groups by kind and includes the safety note that the content is user data, not system instructions. JSON follows the V3 `vault-memory/1` mapping: top-level `schema_version` and `generated_at`; each record includes memory ID, revision, kind, namespace, `status: "confirmed"`, evidence kind/IDs, `recorded_at` from the candidate's stored `created_at`, `confirmed_at` from the Vault memory row, `confirmed_by: "local-user"`, validity, `supersedes: null`, `external_use`, `training_consent: false` (default deny because no grant is stored), content hash, and text. Do not add EverOS metadata that is not present in the mapped source record.

- [ ] **Step 7: Implement preview hashing and export revalidation**

  `preview` returns the serialized text, timestamp, hash, included records, exclusions, and estimate. `export` rebuilds with the same timestamp and inputs, verifies the submitted preview hash, then returns the generated text. Return `PACK_PREVIEW_STALE` (409) if records, selection, or rendered bytes changed.

- [ ] **Step 8: Run the policy and renderer tests**

  Run: `pytest tests/unit/test_entrypoints/test_memo_vault_memory_pack.py -q`
  Expected: PASS for both formats, all kinds, policy gates, evidence privacy, and budget boundaries.

---

### Task 3: Connect preview/export APIs and metadata-only audit

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/routes/exports.py`
- Modify: `src/everos/entrypoints/memo_vault/storage.py`
- Modify: `src/everos/entrypoints/memo_vault/app.py` only if a service factory is needed
- Test: `tests/unit/test_entrypoints/test_api/test_routes/test_memo_vault_exports.py`

**Interfaces:**
- Consumes: Task 2's `MemoryPackService.preview` and `.export`.
- Produces: working `POST /api/v1/packs/preview` and `POST /api/v1/packs/export`, stable errors, and one audit row per successfully generated Pack.

- [ ] **Step 1: Add route contract tests**

  Cover preview envelope shape; export envelope and content hash; unknown project; cross-project IDs; `ask` without final confirmation; evidence quote without evidence confirmation; stale preview; EverOS offline; and no export row when generation is rejected.

- [ ] **Step 2: Run the export route tests and confirm the missing behavior**

  Run: `pytest tests/unit/test_entrypoints/test_api/test_routes/test_memo_vault_exports.py -q`
  Expected: the Pack route assertions fail while handlers remain placeholders.

- [ ] **Step 3: Add backward-compatible export audit metadata migration**

  Extend the existing `exports` table with `metadata_json TEXT NOT NULL DEFAULT '{}'` through the existing initialization migration pattern. Add `VaultStore.record_export(...)` to write export type, format, selected IDs/revisions, hash, timestamp, namespace scope, delivery action, and confirmed `ask` IDs. Never pass rendered content to the audit helper.

- [ ] **Step 4: Connect the preview route**

  Construct `MemoVaultLibraryService` from `request.app.state.vault_store` and the existing `everos_adapter`; call `list_pack_sources` once per selected project, then pass the combined records to `MemoryPackService`. Return `ApiEnvelope[PackPreviewData]`. Map project, EverOS, invalid selection, and malformed upstream failures to stable API error codes.

- [ ] **Step 5: Connect the export route and final confirmation checks**

  Load fresh sources per selected project and pass them to `MemoryPackService.export`. Require exact selected IDs, a matching preview hash/timestamp, explicit confirmation for every included `ask` ID, a separate evidence confirmation for `snippet`/`full`, and an irreversible-transfer confirmation. Record the metadata only after successful rendering and hash validation. Return no body in errors or logs.

- [ ] **Step 6: Run the export route tests**

  Run: `pytest tests/unit/test_entrypoints/test_api/test_routes/test_memo_vault_exports.py -q`
  Expected: PASS, including stale and cross-scope requests being denied without information leakage.

---

### Task 4: Build the Memory Pack page

**Files:**
- Modify: `apps/memo-vault-ui/src/api.ts`
- Modify: `apps/memo-vault-ui/src/App.tsx`
- Modify: `apps/memo-vault-ui/src/styles.css`

**Interfaces:**
- Consumes: Task 3's preview and export contracts.
- Produces: project/type configuration, item selection, backend-generated preview, final confirmation dialog, copy/download, and honest loading/error/empty/stale states.

- [ ] **Step 1: Add frontend types and API helpers**

  Define all-six-kind Pack types and typed preview/export functions. Use `AbortSignal` or a request sequence so obsolete preview responses cannot replace a newer selection.

- [ ] **Step 2: Add page state and initial configuration**

  Maintain selected project IDs, all six kinds (checked by default), format, evidence mode, budget (default 4000), exact item selection, preview request sequence, preview result, and errors. Start with only the `personal` project selected when it exists; require an explicit project choice before requesting a preview otherwise. Do not persist `ask` selections or final confirmations across exports.

- [ ] **Step 3: Render the preview and configuration layout**

  Replace the generic placeholder for `pageId === "pack"` with the screenshot's two-column layout. Use existing project spaces as explicit scope choices; add type checkboxes for 偏好、事实、决策、待办、情节、画像. Group rows as `allow` (selected by default), `ask` (unselected), and `deny` (locked/excluded). Show valid-state exclusions, manual exclusions, index-unavailable rows, over-budget rows, included count, and approximate tokens.

- [ ] **Step 4: Render generated preview text and stale/error states**

  Display only text returned by `/packs/preview`. Refresh preview after scope/config/selection changes. Distinguish empty scope, no eligible memories, EverOS offline, missing canonical rows, stale preview, and API failure; provide retry without showing candidate fallback content.

- [ ] **Step 5: Add final confirmation, copy, and download**

  Before either action, show the exact included IDs/count, list selected `ask` memories, warn that delivered content cannot be recalled, and require the appropriate confirmations. Require a second evidence confirmation for `snippet`/`full`. On success copy returned content or download `memory-pack.md` / `memory-pack.json`; display API errors and clipboard failures clearly.

- [ ] **Step 6: Add responsive styling**

  Match the reference's preview/config panels on wide screens; stack panels on narrow screens; keep long memory text scrollable and safe to wrap; preserve accessible labels and focusable confirmation controls.

- [ ] **Step 7: Build the UI**

  Run: `npm run build` in `apps/memo-vault-ui`.
  Expected: TypeScript and Vite build succeed with no generated build artifacts added to source control.

---

### Task 5: Capability state and end-to-end acceptance

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/routes/system.py`
- Test: previously added Pack source, service, and route test modules

**Interfaces:**
- Consumes: completed backend endpoints, audit logging, and UI.
- Produces: truthful `memory_pack: ready` capability and recorded acceptance of preview → confirmation → copy/download.

- [ ] **Step 1: Keep capability state truthful**

  Change `memory_pack` from `not_started` to `ready` only when both endpoints and the UI flow are connected. Do not alter ADP capability state.

- [ ] **Step 2: Verify the six-kind and policy acceptance matrix**

  Exercise each kind (`preference`, `fact`, `decision`, `todo`, `episode`, `profile`) through preview and both formats. Confirm `allow`, `ask`, `deny`, expired, withdrawn, deleted, missing-index, selected/deselected, and over-budget behavior against the Global Constraints.

- [ ] **Step 3: Verify preview/export consistency and metadata-only audit**

  Confirm a stable selection downloads the preview hash; changing revision/content/status between preview and export requires refresh; successful copy/download creates one audit row with IDs/revisions/hash and no content; rejected exports create no successful export row.

- [ ] **Step 4: Run the focused backend checks and frontend build**

  Run: `pytest tests/unit/test_entrypoints/test_memo_vault_pack_sources.py tests/unit/test_entrypoints/test_memo_vault_memory_pack.py tests/unit/test_entrypoints/test_api/test_routes/test_memo_vault_exports.py -q`
  Run: `npm run build` in `apps/memo-vault-ui`.
  Expected: all focused backend tests and the frontend build pass.

## Acceptance Checklist

- [ ] Preview and downloaded/copyable content have the same hash and item set.
- [ ] All six labels are selectable and can be exported in Markdown and `vault-memory/1` JSON.
- [ ] The Vault registry and scoped EverOS response are both required for inclusion.
- [ ] `ask` requires per-item selection and confirmation on every delivery; `deny` cannot be included.
- [ ] Evidence defaults to IDs; quote modes show privacy warnings and never include a full source conversation.
- [ ] Budget estimates are labeled approximate and never cut a memory body mid-item.
- [ ] Stale previews, missing index records, and EverOS failures are recoverable and never use candidate text.
- [ ] Audit rows contain no exported memory body.
- [ ] The UI handles empty, loading, error, and narrow-screen states.
