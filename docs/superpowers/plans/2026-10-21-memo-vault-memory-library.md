# MEMO Vault Memory Library Implementation Plan

> **For agentic workers:** Execute this plan task by task in the current workspace. The implementation follows the approved design spec linked below.

**Goal:** Implement a project-scoped Memory Library that displays and searches only Vault-confirmed EverOS memories, with full detail and source evidence on demand.

**Architecture:** Extend EverOS `/memory/get` with paginated Atomic Fact reads and a scope-pinned exact native-memory ID selector. In MEMO Vault, use the `memories` table as an allowlist/governance registry and retrieve canonical body content through `EverOSHttpAdapter`; normalize Episode, Atomic Fact, and candidate-linked Profile records for the API and UI. Build a screenshot-aligned project sidebar, searchable list, and right-side detail drawer.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, EverOS index repositories, SQLite, HTTPX, React 19, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-10-21-memo-vault-memory-library-design.md`

## Global Constraints

- EverOS is the only source of formal memory content; Vault stores workflow and governance metadata.
- Every EverOS read is pinned to the current Vault `app_id`, `user_id`, and a validated `project_id`.
- The Vault `memories` table is the allowlist; pending, rejected, or unregistered EverOS records are never returned.
- User and assistant chat memories belong to the Vault `user_id`; this feature does not read Agent memories.
- Keep the existing memory type labels and candidate confirmation behavior unchanged.
- Treat missing EverOS index rows as synchronization/missing state; never substitute candidate text as formal memory content.
- Do not add edit, revoke, delete, Memory Pack, ADP, or authorization controls.

## Review Focus

- A globally valid memory ID requested under the wrong project, app, or user must return no record.
- Candidate publication writes Markdown before index visibility; the UI must say the record is syncing when the approved registry row is absent from `/get`.
- Profile is one EverOS row containing arrays of entries; only entries marked with the matching `memo_vault_candidate_id` may become individual Vault memories.
- Expired confirmed entries remain visible under the expired filter and are absent from the default valid view.
- Search must match full EverOS content even when the table preview is truncated.

---

### Task 1: Extend EverOS `/memory/get` for Atomic Facts and exact IDs

**Files:**
- Modify: `src/everos/memory/get/dto.py`
- Modify: `src/everos/memory/get/manager.py`
- Modify: `src/everos/service/get.py`
- Reference: `src/everos/infra/persistence/records/atomic_fact.py`

**Interfaces:**
- Consumes: Existing `GetRequest`, `FilterNode`, `IndexRepository.find_where_paginated`, scope compiler, and `atomic_fact_repo`.
- Produces: `GetMemoryType.ATOMIC_FACT`; `GetAtomicFactItem(id, user_id, app_id, project_id, session_id, timestamp, parent_id, fact)`; `GetData.atomic_facts`; optional `GetRequest.memory_id: str | None`.
- Exact ID selection is an additional predicate combined with the manager's required `owner_id`, `owner_type`, `app_id`, and `project_id` predicates. It does not enter the user filter DSL.
- Native `memory_id` exact lookup applies to Episode and Atomic Fact. Profile remains a single scoped profile row; Vault resolves its candidate-level IDs from the item's `memo_vault_candidate_id`.

- [ ] **Step 1: Add Atomic Fact DTO and exact-ID request field**

  Add the enum value, response item, always-present response array, and optional validated `memory_id` to the `/get` DTO. Extend the user-owner/type validator to allow Atomic Fact. Keep `extra="forbid"`, existing XOR validation, and default project scope.

- [ ] **Step 2: Wire Atomic Fact repository and exact scoped reads**

  Inject `atomic_fact_repo` into the lazy `GetManager` in `src/everos/service/get.py`. In `GetManager`, compile the normal scope predicate first, combine an exact `id` predicate when `memory_id` is set, and route paginated Atomic Fact requests through the Atomic Fact repository. Shape `fact`, timestamp, session, and parent metadata without exposing index implementation fields.

- [ ] **Step 3: Preserve profile and pagination behavior**

  Keep Profile reads as a scoped one-row lookup. For native exact-ID requests on Episode/Atomic Fact, return at most one result while preserving the existing response envelope and count semantics. Existing requests that omit `memory_id` retain current pagination behavior.

- [ ] **Step 4: Update the public `/memory/get` API description**

  Update the `/get` route docstring and `docs/api.md` for Atomic Fact support, `memory_id`, and the hard scope predicates. Document that Profile is still returned as one scoped aggregate row.

- [ ] **Step 5: Review the API contract and scope path**

  Confirm the new path is wired in both `/api/v1` and `/api/v2` by the existing router registration, the filter compiler still pins all scope fields, and no agent-owned type can be queried with `user_id`.

---

### Task 2: Implement Vault memory service and scoped library endpoints

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/adapter.py`
- Modify: `src/everos/entrypoints/memo_vault/contracts.py`
- Modify: `src/everos/entrypoints/memo_vault/routes/memories.py`
- Create: `src/everos/entrypoints/memo_vault/library.py`
- Reference: `src/everos/entrypoints/memo_vault/storage.py`
- Reference: `src/everos/entrypoints/memo_vault/routes/candidates.py`

**Interfaces:**
- Consumes: Task 1's `/memory/get` response and optional `memory_id` selector; `VaultStore.get_identity()`, `list_projects()`, `has_project()`; `memories` and candidate evidence tables.
- Produces: `EverOSMemoryRecord(memory_id, memory_type, content, timestamp, metadata)`; adapter methods `list_user_memories(*, app_id, project_id, user_id, memory_type) -> list[EverOSMemoryRecord]` and `get_user_memory(*, app_id, project_id, user_id, memory_id, memory_type) -> EverOSMemoryRecord | None`; normalized `LibraryMemory` API records.
- Vault HTTP contract: `GET /api/v1/memories?project_id=...&q=...&status=valid|expired|all` returns normalized list records, visible total, and missing-index IDs; `GET /api/v1/memories/summary` returns per-project visible-valid and syncing counts; `GET /api/v1/memories/{vault_memory_id}?project_id=...` returns the full canonical EverOS body, governance fields, and evidence references. Register `/summary` before the dynamic `/{vault_memory_id}` route.
- `vault_memory_id` addresses the Vault registry row (`memories.id`). `everos_memory_id` remains an explicit separate field. Profile records are flattened only where an entry carries the matching candidate marker.

- [ ] **Step 1: Add typed EverOS memory record mapping to the adapter**

  Implement a page loop over `/api/v2/memory/get` for `episode` and `atomic_fact`, requiring stable `total_count`/`count` behavior and validating every returned item's `app_id`, `project_id`, and owner. Read `profile` as the single scoped record and flatten only `explicit_info` / `implicit_traits` entries containing `memo_vault_candidate_id`; use that marker as the Vault-published profile memory ID and `description` as content.

- [ ] **Step 2: Build a Vault library service around the approval registry**

  Create `MemoVaultLibraryService` taking a `VaultStore` and `EverOSAdapter`. Read only `memories.status='confirmed'` records whose `namespace` is the requested project. Fetch EverOS data grouped by native memory type, intersect on `everos_memory_id`, and build canonical memory records with Vault `kind`, `revision`, `external_use`, `valid_until`, and `evidence_kind`.

- [ ] **Step 3: Implement project validation, search, status, and index-sync behavior**

  Reject unknown project IDs before upstream requests. Use the current Vault identity rather than client-supplied owner fields. Apply casefolded literal keyword matching against full canonical EverOS content before generating list previews. Derive valid/expired status from `valid_until`; `valid` is the default. Return missing confirmed IDs separately as index-sync/missing metadata without returning Vault candidate text.

- [ ] **Step 4: Implement full detail and source evidence mapping**

  Validate the registry ID and project before reading EverOS. Fetch a scoped exact native record for Episode/Atomic Fact; fetch the scoped Profile and locate the exact marker for Profile candidates. Load evidence by joining registry/candidate ID through `candidate_evidence`, `normalized_messages`, and `import_batches`; return filename, source message IDs, quotes, and evidence availability.

- [ ] **Step 5: Connect the Vault routes to the service**

  Replace both placeholder handlers in `routes/memories.py` with query-validated handlers, envelope responses, and stable errors for invalid project, unknown/unapproved ID, EverOS unavailable, and malformed upstream response. Instantiate the service using the app's existing `vault_store` and `everos_adapter`.

- [ ] **Step 6: Add visible per-project counts**

  Add `GET /memories/summary` returning `{projects: [{project_id, visible_valid_count, syncing_count}]}`. Count only canonical EverOS-visible records as visible; count registered, confirmed, currently valid IDs missing from EverOS as syncing. Keep each EverOS read individually scoped to a known project; do not send a wildcard project query.

---

### Task 3: Implement the Memory Library UI

**Files:**
- Modify: `apps/memo-vault-ui/src/api.ts`
- Modify: `apps/memo-vault-ui/src/App.tsx`
- Modify: `apps/memo-vault-ui/src/styles.css`

**Interfaces:**
- Consumes: Task 2 list, summary, and detail response types.
- Produces: Memory Library page with independent selected-library-project state, list/search/status state, selected record, detail drawer, loading/error/sync state, and typed API helpers.

- [ ] **Step 1: Add library contracts and typed API helpers**

  Define `LibraryMemory`, `LibraryEvidence`, `LibraryProjectCount`, and API result types in `api.ts`. Add list/search/status, summary, and detail functions using `URLSearchParams` and encoded IDs. Preserve the standard API envelope error handling.

- [ ] **Step 2: Add independent library state and data loading**

  Add selected library project, status filter, search query, list, count summary, loading, error, index-sync, and detail state to `App.tsx`. Do not reuse import `projectId` as the library sidebar selection. The All sidebar item fans out to individually scoped list requests for each known project and merges the results; it never sends a wildcard project ID upstream. Load counts from the summary endpoint and reload the selected project's list when project, query, or status changes. Cancel or ignore stale responses after selection changes.

- [ ] **Step 3: Render the screenshot-aligned list and project sidebar**

  Render All and project entries with counts. Render search and validity controls and rows for type, preview, namespace, external-use policy, status, and revision. Use responsive CSS line clamping for the preview; do not truncate the API's search source text.

- [ ] **Step 4: Render detail drawer and evidence**

  On row selection, fetch full detail by the Vault memory ID and selected project. Show complete content, metadata, and available source evidence in a right-side drawer. Provide close behavior and clear loading/error states.

- [ ] **Step 5: Add honest empty and failure states**

  Distinguish no confirmed records, no keyword matches, pending index synchronization, EverOS offline, missing canonical records, and API failure. Add a refresh/retry action for index synchronization. Never render candidate content as a library fallback.

---

### Task 4: Connect feature capability status and confirm the completed flow

**Files:**
- Modify: `src/everos/entrypoints/memo_vault/routes/system.py`
- Modify: `apps/memo-vault-ui/src/api.ts`
- Reference: `apps/memo-vault-ui/package.json`

- [ ] **Step 1: Mark the library capability ready**

  Change the health feature map's `library` state to `ready` only after both list and detail endpoints are connected. Keep Memory Pack and ADP states unchanged.

- [ ] **Step 2: Verify candidate confirmation to library behavior by tracing the implementation**

  Confirm that the existing confirmation route stores `memories.id`, `everos_memory_id`, namespace, type, status, revision, and governance settings; the library service then requires `confirmed`, obtains canonical content from EverOS, and matches the correct profile item when applicable.

- [ ] **Step 3: Build the frontend and inspect the final diff**

  Run `npm run build` in `apps/memo-vault-ui`; inspect output and changed files for TypeScript/build errors, unintended scope changes, and generated artifacts. Do not run or add tests unless separately requested.

