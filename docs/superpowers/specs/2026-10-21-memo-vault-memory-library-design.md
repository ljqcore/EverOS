# Memo Vault Memory Library Design

**Date:** 2026-10-21

## Goal

Implement the MEMO Vault Memory Library as a real, project-scoped view of memories that a user confirmed through candidate review. The library reads official memory content from EverOS and uses Vault metadata only to identify approved records and display governance fields.

## Confirmed Existing Flow

Candidate confirmation is implemented in `src/everos/entrypoints/memo_vault/routes/candidates.py`. It checks candidate status, revision, project, source evidence, and content; publishes the approved content through `EverOSAdapter.publish_approved`; then records the EverOS memory ID, target namespace, kind, memory type, status, revision, evidence kind, external-use rule, and expiry in the Vault `memories` table. EverOS publication is idempotent and writes Atomic Fact, Episode, or Profile data through the corresponding native writer.

The library must continue from this flow. It must not expose pending/rejected candidates as formal memories and must not use Vault candidate text as the source of displayed memory content.

## User Requirements

- Provide a project-space sidebar with the count of visible formal memories.
- Provide keyword search and a current-validity filter.
- Display memory type, a content preview, project namespace, external-use policy, validity status, and revision in the list.
- Clicking a row opens a right-side detail drawer with full content and available source evidence.
- Preserve current memory-type names and data. Type taxonomy changes are out of scope.
- Isolate every request by the current Vault identity and the selected existing project.
- Show truthful loading, empty, unavailable, stale-index, and error states.

## Architecture

The Vault `memories` table remains the governance registry: it provides the allowlist of confirmed EverOS memory IDs and Vault-owned metadata such as namespace, kind, revision, external-use policy, and expiration. EverOS remains the source of the formal memory body. The Vault backend joins these sources by the EverOS memory ID and returns a normalized library item.

All EverOS reads go through `EverOSAdapter`; the Vault service does not inspect EverOS private files, directories, or tables. Adapter requests derive `app_id` and `user_id` from the persisted Vault identity. `project_id` comes from a validated Vault project selection. The adapter pins all three values into every EverOS request and verifies returned scope and IDs before joining results.

### EverOS `/memory/get`

Extend the existing paginated read contract to support `atomic_fact`, in addition to the existing user-owned `episode` and `profile` records. Add an Atomic Fact response item and wire `atomic_fact_repo` into `GetManager`. Preserve the existing owner XOR rules, user scope, project scope, deprecated-record exclusion, filtering, sorting, and pagination.

Add an optional exact `memory_id` selector to the get request. It is separate from the open filter DSL and is always combined with the existing owner/app/project predicates. An ID lookup returns zero or one item and cannot bypass scope checks.

The existing `/memory/search` response nests Atomic Facts under each matching Episode (`data.episodes[].atomic_facts[]`). That response is query-ranked and does not provide a complete standalone Atomic Fact listing, so the library will not use it as its list source.

### Vault read and search behavior

For a project-scoped library list, the service reads confirmed records from Vault, fetches the corresponding EverOS records by memory type and scope using the paginated get contract, and intersects them with the Vault allowlist. A Vault row with no matching EverOS record is reported as temporarily unavailable/syncing or stale; its Vault copy is not substituted as formal content.

Keyword search is a case-insensitive literal search over the full EverOS content of the confirmed records in the selected project. The list API returns previews; the detail API fetches the full EverOS record on demand.

For Profile candidates, EverOS stores several profile items in a project-scoped profile record. The candidate-specific published ID is resolved by matching the `memo_vault_candidate_id` embedded in the relevant `explicit_info` or `implicit_traits` item. The library shows that specific candidate-linked item as the Vault memory, not the entire aggregated profile as one candidate.

Candidate source evidence is loaded through the Vault candidate/evidence/message relationships. Missing source data is marked unavailable; no source is fabricated.

### Frontend

Implement the Memory Library page in `apps/memo-vault-ui/src/App.tsx` and `src/styles.css`, following the supplied screenshots:

- Left sidebar: All plus project spaces and their counts.
- Main pane: keyword input, validity selector, and rows showing type, truncated memory preview, namespace, external-use policy, status, and revision.
- Right-side drawer: full selected memory, type, namespace, revision, external-use setting, validity, and evidence/source details.
- The preview uses responsive CSS line clamping so visible text follows the available row width; full content is fetched only when a row is opened.
- Add explicit loading, empty, request-failed, EverOS-unavailable, and index-not-yet-visible states.

The screenshot's edit, revoke, delete, Memory Pack, authorization, and version-history controls are not part of this feature because their corresponding mutation or audit contracts are not implemented.

## Read-After-Publish Consistency

Candidate publication writes through EverOS Markdown writers, while `/memory/get` reads the EverOS index. Index visibility may lag publication. The library must treat an approved Vault row missing from EverOS as an index synchronization state, not as a reason to display Vault content as if it were an EverOS read. The implementation must use the existing real EverOS health/read result to represent this state and support refresh/retry. No fake progress or synthetic record is allowed.

## Error and Isolation Behavior

- Unknown project IDs are rejected before EverOS access.
- Every list and detail lookup is pinned to current `app_id`, `user_id`, and the selected `project_id`.
- A memory ID not registered as confirmed in that project is not returned, even if it exists in EverOS.
- EverOS unavailable or malformed responses produce a stable API error and a recoverable UI state.
- A Vault-confirmed ID missing from EverOS is omitted from normal content and exposed as a sync/missing status where applicable; no Vault-stored content is presented as canonical.
- Expiration is computed from `valid_until`; expired records are excluded by the default “valid” filter and can be shown through the alternate filter with an expired status.

## Acceptance Criteria

1. Confirming an evidenced candidate makes its exact EverOS memory ID and content available in the selected project's library after EverOS indexing completes.
2. Pending and rejected candidates never appear in the library.
3. Atomic Fact, Episode, and candidate-linked Profile records list and open with the right content and metadata.
4. Keyword search checks full content, not only the visible preview, and is constrained to the selected project.
5. A memory from another project, another app, or another user cannot be retrieved by changing a memory ID or query parameter.
6. EverOS unavailability, delayed index visibility, and missing records are shown truthfully without substituting Vault candidate content.
7. The library UI matches the supplied list and right-side detail drawer pattern and retains the current type labels.

## Out of Scope

- Changes to candidate confirmation semantics or memory-type taxonomy.
- Editing, revoking, deleting, or restoring formal memories.
- Memory Pack and ADP export.
- Multi-user authentication, cloud reads, and direct EverOS storage access.
- Semantic/vector search; the MVP search is literal keyword matching over scoped confirmed memories.
