# MEMO Vault MVP Implementation Plan

**Goal:** Build a local web application skeleton for Import, Candidate Review, Memory Library, Memory Pack, and ADP Export Beta, then implement one real path through EverOS.

**Architecture:** A React/Vite console talks to a separate FastAPI Vault service on loopback. The Vault service owns import evidence and workflow metadata in a local directory/SQLite database and accesses durable approved memories only through an `EverOSAdapter`; EverOS API gaps are added behind that adapter when each feature is integrated.

**Tech Stack:** Python 3.12, FastAPI/Pydantic already used by EverOS, SQLite for Vault workflow metadata, React, TypeScript, Vite.

**Spec:** `MEMO_VAULT_MVP_DEVELOPMENT_PLAN_V3.zh-CN.md` and `MEMO Vault MVP 交互设计 V3对齐版.html`.

## Global Constraints

- Run the demo locally and bind both services to `127.0.0.1`.
- Keep EverOS as the only durable approved-memory store.
- Archive original evidence before extraction; extraction failure must not remove the archive.
- Isolate unreviewed candidates from the approved-memory scope.
- Do not claim encryption, Vault locking, MCP authorization, or full audit-chain support in this five-feature demo.
- Cloud extraction is out of scope; do not silently fall back from local processing.
- The first importer accepts Markdown, TXT, and the documented normalized JSON format; platform-specific export formats are later adapters.
- ADP export requires tool calls, observations, outcome, and explicit per-trace consent.

## Review Focus

- Unsupported or malformed import files must not be reported as archived.
- Candidate records without a verifiable evidence reference must not be bulk-confirmable.
- EverOS unavailability must leave archived source material intact.
- Pack generation must exclude inactive and `external_use=deny` memories, and require confirmation for `ask` memories.
- ADP traces missing tool calls, observations, outcome, or consent must not be downloadable.

## File Structure

- `src/everos/entrypoints/memo_vault/`: standalone FastAPI entrypoint and Vault API contracts/routes.
- `apps/memo-vault-ui/`: React/Vite frontend, API client, and the five-feature navigation shell.
- `.memo-vault/` (runtime, ignored/configured): SQLite metadata and archived evidence; never committed.
- `EverOSAdapter`: boundary for EverOS health, extraction, approved-memory publish, search, and fetch.

## Phases

1. **Skeleton (current task):** standalone FastAPI app, health/capability response, typed route placeholders that return explicit 501 until implemented, React/Vite shell with five real navigation destinations and health display, local run instructions.
2. **Import:** safe preview, normalized message/trace contract, file hashing/deduplication, evidence archive, and separate archive/extract states.
3. **Extraction and review:** adapter-backed local EverOS extraction in an isolated candidate scope; evidence mapping; confirm/edit/reject transitions; no unreviewed candidate enters approved scope.
4. **Memory Library:** publish approved content to EverOS, search/list/detail through the adapter, and show Vault-owned governance metadata alongside EverOS IDs.
5. **Memory Pack:** Markdown and `vault-memory/1` JSON preview/export, namespace/type filters, budget, evidence mode, `external_use` enforcement, and export confirmation.
6. **ADP Export Beta:** trace selection, redaction preview, consent, `adp-candidate/1` schema validation, and JSONL download.
7. **End-to-end demo:** import a normalized JSON fixture containing a conversation and complete Agent trace; approve a sourced candidate; find it in the library; export a Memory Pack and validated ADP JSONL.

## Skeleton API Contract

Vault endpoints are versioned under `/api/v1`; EverOS remains under `/api/v2`.

- `GET /api/v1/system/health`
- `POST /api/v1/imports/preview`
- `POST /api/v1/imports/{batch_id}/archive`
- `POST /api/v1/imports/{batch_id}/extract`
- `GET /api/v1/imports`
- `GET /api/v1/candidates`
- `POST /api/v1/candidates/{candidate_id}/confirm`
- `POST /api/v1/candidates/{candidate_id}/reject`
- `GET /api/v1/memories`
- `GET /api/v1/memories/{memory_id}`
- `POST /api/v1/packs/preview`
- `POST /api/v1/packs/export`
- `GET /api/v1/adp/traces`
- `POST /api/v1/adp/validate`
- `POST /api/v1/adp/export`

Unimplemented business routes return a structured `FEATURE_NOT_IMPLEMENTED` error; they must not return simulated successful data.

## EverOS Adapter Contract

The Vault domain will call an interface equivalent to:

```python
health() -> EverOSHealth
extract(batch_id, scope, messages) -> list[CandidateDraft]
publish_approved(record) -> EverOSMemoryRef
search(query, namespace, limit) -> list[EverOSMemoryRef]
get(memory_id) -> EverOSMemoryRef
```

The adapter initially maps to existing EverOS `/health`, `/api/v2/memory/add`, `/flush`, `/get`, and `/search`. If exact approved-content publishing, stable IDs, or candidate isolation cannot be supported, add the smallest versioned EverOS endpoint required; do not bypass the adapter or silently write candidates into the approved scope.
