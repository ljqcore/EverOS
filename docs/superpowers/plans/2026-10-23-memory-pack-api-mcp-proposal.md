# Memory Pack API and MCP Export Proposal

> Status: proposed design and phased development plan, pending product review. No product code is implemented by this document.
> Implementation handoff: after scope approval, use superpowers:executing-plans or explicitly approved subagent-driven-development for task execution.

**Goal:** Let an external application or MCP client receive a user-approved Memory Pack without copying text or downloading a file manually.

**Architecture:** Keep Vault as the authority for export policy. A shared delivery use case serves an authenticated external HTTP API; a separate MCP adapter calls that API. Reuse canonical EverOS reads and existing Pack serialization instead of exposing the core memory API as an export gateway.

**Tech stack:** Existing Python 3.12+, FastAPI, SQLite, Pydantic, React/TypeScript; an optional official MCP SDK dependency for the adapter, pinned to a tested client/protocol matrix during implementation.

**Spec:** Sections 3-8 of this proposal are the draft specification. This is a reviewable proposal, not an approved execution specification.

## 1. Verified baseline

Reviewed against the current working tree on 2026-10-23, including uncommitted Vault work. Older plans are not the source of truth.

- `docs/project-guide.zh-CN.md`: EverOS core and MEMO Vault are separate applications, normally on ports 8000 and 8765.
- `src/everos/entrypoints/memo_vault/routes/exports.py`: working `POST /api/v1/packs/preview` and `POST /api/v1/packs/export` already exist. ADP endpoints remain placeholders.
- `memory_pack.py`: selection, lifecycle filtering, approximate budgeting, Markdown/JSON rendering, content hashes, preview revalidation, and final confirmation checks already exist.
- `contracts.py`: Pack kinds are currently exactly `fact`, `episode`, `profile`; formats are `markdown` and `vault-memory/1`. Delivery actions are exactly `copy` and `download`.
- `library.py`: confirmed Vault rows are joined to scoped canonical EverOS content. Missing, inactive, and denied records do not fall back to candidate bodies. Local policy is revalidated after upstream awaits.
- `adapter.py`: canonical reads are paginated and validate identity/scope, duplicate IDs, and changing totals. Pack generation still loads full relevant project/type collections; token budget does not bound upstream work.
- `storage.py`: `exports` contains metadata-only export receipts; there is no external-client grant/token lifecycle or approved-Pack registry.
- `apps/memo-vault-ui/src/App.tsx`: browser preview -> final confirmation -> backend export -> clipboard/download.
- `docs/mcp.md`: the existing separate `everos-mcp` integration calls core `/api/v2/memory/*`, not Vault export policy. This is not an existing Vault MCP export implementation.
- Vault app/config currently provide a local identity, not authenticated owner sessions or multi-user isolation.

Verification performed:

```bash
.venv/bin/python -m pytest tests/unit/test_entrypoints/test_memo_vault_pack_sources.py tests/unit/test_entrypoints/test_memo_vault_memory_pack.py tests/unit/test_entrypoints/test_api/test_routes/test_memo_vault_exports.py -q
```

Result: **28 passed in 3.17s**. These are current Pack regression tests, not tests of the proposed external gateway.

## 2. Options and recommendation

| Option | What changes | Advantages | Limitations |
| --- | --- | --- | --- |
| Script the existing preview/export API | Add examples and a client wrapper | Smallest change; useful for trusted owner scripts | Caller can assert confirmation booleans; preview discloses ask bodies; no delegated access boundary |
| Approved Pack with scoped external delivery | Persist approval manifest and grant; add authenticated delivery API and MCP adapter | Extends the current product directly; reproducible, reviewable content; bounded authorization | Requires approval persistence, credential management, and control-plane protection |
| Live Agent memory gateway | Add scoped search/list/get/build operations over current memory | Better for ongoing Agent context retrieval | Broader product: per-result policy, approval requests, query limits, indexing and pagination |

**Recommendation:** second option first, third as a follow-up. The first remains a trusted-owner integration technique, not the security model for external Agents.

**Working assumption:** initial export means receiving the exact user-selected Pack. Live retrieval is an extension, not silently included. If live retrieval is the priority, stage 4 becomes the primary deliverable and the scope/estimate must change.

## 3. Scope and invariants

- Only confirmed, active, unexpired memories with canonical bodies can leave Vault.
- Retain the current three Pack kinds. Source projection still recognizes older kinds; do not silently revive six-kind export from the historical plan.
- External format defaults to `vault-memory/1`; Markdown remains supported. No new memory schema is necessary for transport alone.
- External evidence mode defaults to `none`. MVP supports only `none` and `id`; the owner must explicitly choose IDs because source references also reveal metadata. Existing local excerpt export remains unchanged.
- `deny` never leaves. `ask` requires a trusted owner approval bound to this exact delivery; client flags cannot grant permission.
- A client credential authorizes a named client to consume a bounded approved Pack. It cannot create grants, approve its own request, edit memory, or read import archives.
- The credential is a bearer capability, not proof of a client's cryptographic identity. Display names alone do not prevent credential copying.
- Preserve the copy/download API contract. External clients use a separate route surface and response model.
- Delivery is pull-based. No third-party push/webhook, full Vault backup, ADP export, multi-account service, or all-project bulk dump in the MVP.
- Use English for new code/docs and existing datetime helpers for persisted UTC timestamps.

## 4. Proposed user and data flow

1. Owner selects projects, kinds, budget, memories, and permitted evidence mode using the existing Pack UI.
2. Owner chooses API/MCP delivery and reviews the exact payload plus recipient label, expiry, and read limit.
3. Trusted owner endpoint reloads canonical sources, validates the preview and per-item ask approval, and saves an immutable approval manifest.
4. Server issues a random opaque token once. Store only its verifier; never place it in query strings, ordinary logs, or a committed client config.
5. External client requests content using the token. Server resolves its scope; client cannot supply owner identity, expand projects, change format/evidence mode, or add memory IDs.
6. Server revalidates the grant, selected memory states and hashes; atomically reserves the allowed delivery and writes its receipt before returning bytes.
7. Revocation prevents future delivery admissions. Already returned bytes cannot be recalled.

Suggested MVP defaults: 24-hour grant expiry and one content delivery. Empty Packs cannot receive a grant. A future reusable grant may deliver allow-only content with an explicit owner-set read limit; it must not make ask approval reusable.

The owner action creates authorization, not an external delivery receipt. Do not count the approval itself as receipt by the consumer.

## 5. Approval, integrity, and concurrency

### Approval manifest

Persist `approved_pack_id`, fixed generation time, serializer version, exact format/evidence mode, selected IDs/revisions, namespace/type scope, budget, per-memory canonical hashes, approved artifact hash, and expiry. Bind consent to the manifest hash and grant. Do not store additional memory bodies in the export registry.

On delivery, reconstruct from current canonical content using the frozen generation time and serializer version. Require every approved member and artifact hash to match. If a selected memory was edited, withdrawn, expired, deleted, denied, or disappeared, reject the entire Pack as `PACK_APPROVAL_STALE`; never silently omit it or add replacements. A change to an unrelated unselected memory must not invalidate an approved Pack.

The existing preview hash covers the broader source set. Keep it for local preview -> approval validation, but do not use it as the persistent approved-Pack identity: define a separate manifest hash over approved members and rendering configuration.

Pin `generated_at`; otherwise repeated rendering changes bytes. Do not call private renderer helpers from an MCP tool: expose a tested delivery renderer contract. If an old serializer version is no longer available after upgrade, require reapproval rather than producing different bytes under an old hash.

### Admission boundary

Perform slow upstream reads before the final local transaction. Then use a SQLite write transaction to recheck grant status/expiry/use count, local revisions/policy/expiry, and manifest identity; reserve use and write the receipt atomically. No upstream await belongs inside that transaction.

A revocation committed before this transaction blocks delivery; a request admitted before revocation may finish. This is the promised revocation boundary. Do not claim all in-flight bytes can be stopped. Core changes outside Vault lack a cross-service transaction; document that delivery validates the canonical version observed during its read, not a distributed linearizable snapshot.

### Retry semantics

Default single-delivery tokens are consumed when server delivery is admitted, even if the network subsequently fails. Do not promise exactly-once receipt or automatic replay of ask content. Let the owner inspect the receipt and reauthorize if needed. Authorization creation can use an owner-scoped idempotency key to avoid duplicate grants on UI retries.

## 6. API surface and authorization boundary

Proposed paths; these are new contracts, not claims about existing endpoints.

| Audience | Operation | Contract |
| --- | --- | --- |
| Owner console | `POST /api/v1/pack-authorizations` | Current preview inputs/hash plus recipient, expiry and final confirmations; returns approved Pack ID, grant ID and one-time-visible token |
| Owner console | `GET /api/v1/pack-authorizations` | Metadata/status only; never returns token secrets or Pack bodies |
| Owner console | `DELETE /api/v1/pack-authorizations/{grant_id}` | Revoke future delivery admissions; idempotent |
| External client | `GET /api/v1/external/packs/{pack_id}` | Authorized metadata only; no selection rows, ask text, or wider project statistics |
| External client | `POST /api/v1/external/packs/{pack_id}/deliver` | Authenticated bounded delivery; returns exact JSON or Markdown artifact bytes |

`POST` delivery reflects token consumption and avoids prefetch/cache semantics. Use `Cache-Control: no-store`. Return request/receipt IDs and `X-Content-SHA256` in headers. The artifact hash is over the exact UTF-8 body produced by the pinned renderer, not a JSON transport envelope or an MCP wrapper. Client libraries may parse JSON after validating those bytes.

Invalid, expired, revoked, exhausted tokens and inaccessible Pack IDs use a generic authorization failure. Only a valid grant bound to the requested Pack may receive specific `PACK_APPROVAL_STALE`, upstream-unavailable, or budget/payload errors. No response reveals whether a foreign project or memory exists.

### Two trust planes

Keep owner controls and external delivery on distinct ASGI applications/listeners, with an explicit route allowlist. Never expose the whole current Vault application via a reverse proxy intended for external delivery. Core EverOS remains private.

Owner grant creation/revocation needs a locally provisioned owner credential/session, origin/host checks and CSRF protection for cookie-authenticated mutations; loopback and CORS alone are insufficient. External tokens must fail on owner and existing preview/library/import routes, including if supplied to the control listener. Owner-side changes must include a browser bootstrap/session mechanism; shipping a grant endpoint into the current unauthenticated app is not sufficient.

MVP threat model: trusted local OS account and trusted owner UI; protected API delegation to external consumers. A same-user local process can already access local files and the unauthenticated core API. Scoped Vault tokens do not sandbox arbitrary same-user Agents. Stronger isolation requires separate OS/service identities or protecting every core read surface and storage access, and is outside this MVP.

## 7. MCP integration

MCP is an adapter over the external delivery API. It does not access SQLite, read Markdown directly, call core memory search, or accept `confirm_*` booleans as owner consent.

Initial tools:

- `get_pack_info(pack_id)`: returns only authorized Pack metadata/status.
- `read_memory_pack(pack_id)`: performs delivery; returns parsed JSON through the SDK's negotiated structured result support, with a text fallback for tested older clients. Preserve JSON schema version and receipt metadata.

Each stdio process receives its Vault URL, token and fixed Pack ID through environment or a local protected credential reference. Do not include a grant creation tool. Tool annotations must accurately reflect consuming a one-time delivery; read-only wording does not imply retry safety. Label memory text as untrusted user data, not instructions; retain existing training-consent metadata without claiming downstream enforcement.

Start with stdio for local clients. Select the SDK/protocol version by testing actual target clients, rather than assuming the latest published protocol is universally supported. A separate Vault adapter avoids exposing the existing MCP server's write tools accidentally. Extending the separate EverOS-MCP repository is an alternative only if it gains an explicit Vault-only mode and independent URL/credential configuration.

Remote MCP is a subsequent milestone: Streamable HTTP, TLS, origin validation and the MCP HTTP authorization profile, including OAuth discovery and resource/audience binding. A static token on a custom HTTP endpoint is not sufficient to claim compatibility with OAuth-only MCP hosts.

References consulted on 2026-10-23:

- [MCP transports](https://modelcontextprotocol.io/specification/latest/basic/transports)
- [MCP authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization)
- [Existing EverOS-MCP repository](https://github.com/EverMind-AI/EverOS-MCP)

## 8. Persistence and component boundaries

Add tables with idempotent migrations:

- `approved_packs`: immutable manifest, artifact/manifest hashes, renderer version and expiry; metadata only.
- `export_grants`: Pack binding, token verifier, recipient label, expiry/revocation/use count; secret returned once.
- `delivery_receipts`: request/grant/Pack IDs, transport, selected revisions/hash, admission outcome and timestamp; no payload/token.

Retain historical `exports` rows. Either extend them for new delivery receipts or use the new table, but do not reinterpret historical copy/download records as verified client receipt. Failed authorization attempts must not create successful export rows; rate-limit and redact security events separately.

Keep HTTP/MCP endpoints thin. Proposed application service: `src/everos/service/memo_vault_exports.py`, with explicit source-loader, renderer, clock and repository ports. It must not import `everos.entrypoints.*`. Existing Vault library/renderer/store implementations are injected by the composition root. Put shared neutral delivery types/ports in the service module or a focused `src/everos/service/memo_vault_export_contracts.py`; HTTP DTO conversion stays in entrypoints. This permits reuse without moving the whole Vault subsystem in this feature.

New HTTP DTOs: `src/everos/entrypoints/memo_vault/export_contracts.py`; owner routes: `routes/pack_authorizations.py`; external routes/app: `routes/external_packs.py` and `external_app.py`. Authentication adapters live in `entrypoints/memo_vault/auth.py`; persistence methods/migrations initially extend the existing `storage.py`. MCP entrypoint lives in `entrypoints/memo_vault_mcp/` and uses only the HTTP contract.

## 9. Phased implementation plan

### Task 1: Delivery domain and renderer contracts

- [ ] Define typed approval manifest, grant, receipt, and delivery errors, with explicit source/renderer/repository ports.
- [ ] Add tests for reconstruction with a fixed timestamp, selected-member hashes, stale selected members, unrelated memory changes, unsupported renderer version, and current three-kind behavior.
- [ ] Implement manifest generation and byte-identical re-rendering through a public renderer adapter; preserve local preview/export behavior.
- [ ] Verify the new domain tests plus the existing 28 Pack tests before committing this unit.

**Files:** new service modules above; existing `memory_pack.py`, `library.py`, and their tests. New test: `tests/unit/test_service/test_memo_vault_export_delivery.py`.

### Task 2: Owner authentication and authorization persistence

- [ ] Define and test the local owner bootstrap/session contract before exposing grant mutations; external token must never authenticate as owner.
- [ ] Add migration tests for old databases, repeated initialization, grant hashing, one-time secret display, expiry, revocation, and idempotent creation.
- [ ] Implement approved Pack/grant storage and trusted owner creation/list/revocation endpoints. Validate the existing preview and final confirmations on creation; reject empty Packs.
- [ ] Test forged ask confirmations from external clients, foreign IDs, CSRF/origin/host failures, and token redaction.

**Files:** `auth.py`, `export_contracts.py`, `routes/pack_authorizations.py`, `storage.py`, `app.py`, `config.py`. Tests: `tests/unit/test_entrypoints/test_memo_vault_export_auth.py` and `test_memo_vault_pack_authorizations.py`.

### Task 3: External delivery API and atomic receipts

- [ ] Write API tests for exact bytes/hash/content type, valid metadata, generic unauthorized failures, and zero successful receipts on rejected delivery.
- [ ] Implement the external app with only the two allowlisted routes and scoped bearer verification.
- [ ] Implement the final admission transaction, use reservation and metadata-only receipt. Test two simultaneous reads of a single-use grant, revocation during upstream reads, grant expiry, memory expiry, and policy changes before admission.
- [ ] Inject network/upstream failures: no stale/candidate fallback and no claim of client receipt; verify documented token consumption on response failure.
- [ ] Bound request/response bytes, upstream load/concurrency/timeouts and rate limits independently of approximate token budget. Suggested initial response cap: 1 MiB, with whole-response rejection before admission if exceeded.

**Files:** `routes/external_packs.py`, `external_app.py`, service/repository adapters, `config.py`. Test: `tests/unit/test_entrypoints/test_memo_vault_external_packs.py`.

### Task 4: Owner UI and API client example

- [ ] Add API/MCP delivery alongside copy/download using the owner authorization endpoint; do not make `delivery_action="api"` an authorization mechanism.
- [ ] Show exact recipient, expiry, content/evidence scope and single-use semantics; require per-delivery ask confirmation and transfer acknowledgement.
- [ ] Display the secret once, provide a protected configuration recipe, and show grant status/revoke controls. No tokens in URLs, browser analytics or persisted UI settings.
- [ ] Add a minimal HTTP client example that consumes the token and parses `vault-memory/1`; validate bytes against the response hash.
- [ ] Build the UI and exercise authorization -> API delivery -> receipt -> exhausted/revoked status with synthetic data.

**Files:** existing UI `src/api.ts`, `src/App.tsx`, `src/styles.css`; new focused UI components if needed; `examples/memo_vault_pack_client.py`.

### Task 5: stdio MCP adapter

- [ ] Test the adapter against a fake external HTTP API: no owner/core calls, no token leakage, structured result and text fallback, stable unauthorized/stale/upstream errors.
- [ ] Implement `get_pack_info` and `read_memory_pack` without duplicating Pack policy or schema transformation.
- [ ] Add optional MCP dependency/entrypoint and packaging checks; send diagnostics to stderr and protocol output to stdout.
- [ ] Run one actual target MCP host integration with synthetic allow/ask/deny records; verify one delivery consumes one approval and retries do not silently redeliver.
- [ ] Document supported host/protocol versions and configuration separately from existing `docs/mcp.md` core integration.

**Files:** `src/everos/entrypoints/memo_vault_mcp/`, `pyproject.toml`, lockfile, new `tests/unit/test_entrypoints/test_memo_vault_mcp.py`, new English Vault export guide.

### Task 6: End-to-end acceptance and capability reporting

- [ ] Verify API/MCP yield the same approved artifact semantics, member set and content hash while keeping transport metadata separate.
- [ ] Exercise canonical-store outage, missing index, stale approval, duplicate requests, expired/exhausted/revoked grants, mixed-project inputs and source evidence isolation.
- [ ] Verify externally exposed OpenAPI contains no owner/library/import/core routes and that a reverse-proxy allowlist cannot accidentally publish them.
- [ ] Advertise `external_pack_api` and `vault_mcp_stdio` independently; do not report remote MCP/OAuth, live query or ADP as ready.
- [ ] Run focused new and existing tests, UI build, lint/import rules, datetime and language checks. Record any pre-existing failures separately.

## 10. Review focus and completion criteria

Five failures requiring explicit coverage:

1. External preview or metadata reveals ask/deny/unapproved content: Tasks 2-3.
2. A stolen/wrong-Pack/external token can mutate owner controls or expand scope: Tasks 2-3.
3. Concurrent delivery/revocation lets a one-use approval admit two responses: Task 3.
4. A selected record changes between approval and delivery or after an upstream await: Tasks 1 and 3.
5. JSON envelopes, timestamps, serializer upgrades or MCP formatting change the claimed artifact hash: Tasks 1 and 5-6.

MVP is complete when a user authorizes an exact Pack once, an HTTP client and a tested MCP host can consume it without manual file handling, all policy and lifecycle restrictions apply, and the owner can revoke future access with an honest metadata-only audit trail.

Planning estimate, not a measured commitment: one developer familiar with this codebase, approximately 8-12 working days across domain/persistence (2), owner authorization (2-3), external API/concurrency (2), UI/client (1-2), MCP/integration/docs (1-3), with overlap dependent on review. Remote OAuth/MCP and live retrieval are separately estimated after requirements are fixed.

## 11. Follow-up: live retrieval

If needed, create a different grant mode `live_scope` with exact project/kind allowlists, budget/evidence limits, expiry and rate limits. Effective visibility is the intersection of grant scope, request scope, current confirmed/lifecycle state and external-use policy. New allow memories entering a scope must be explicitly explained when granting that mode.

Start live mode with allow-only retrieval. Ask content stays unavailable until a trusted owner creates an approval bound to an exact response. Search/list/get/build/preview all require the same egress filter before any content or source metadata is returned. Never route live queries straight to the existing core MCP tools. Pagination needs bounded work, deterministic ordering, opaque scoped cursors and explicit snapshot/change semantics.

Full-history export, incremental synchronization/tombstones, remote HTTP MCP and third-party push connectors are independent follow-up requirements; do not infer them from Memory Pack transport support.
