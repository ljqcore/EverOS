# MEMO Vault Import MVP

This local prototype currently implements the generic file import flow:

1. Select the generic-file source.
2. Upload a `.json`, `.md`, `.txt`, or bounded `.zip` archive for server-side checks and parsing.
3. Review real message counts and samples, choose a project space, and confirm archival.
4. Optionally submit each complete conversation to EverOS in the selected project space.
5. Review the archive receipt and extraction outcome.

JSON must be a non-empty array of `{ "role": "user", "content": "..." }`
messages or an object containing a `messages` array. Markdown recognizes
`## User` / `## Assistant` headings; text recognizes `User:` / `Assistant:`
lines. A text file without these explicit role markers is kept as one user
message. Message hashes normalize Unicode and whitespace. Duplicate messages
across the current import or earlier batches remain linked to the raw evidence,
are marked in preview and excluded from extraction.

ZIP archives are inspected without extracting to disk. Only `.json`, `.md`, and
`.txt` members are parsed. Nested archives, unsafe paths, encrypted entries,
symlinks/special files, unsupported compression methods, and suspicious
compression ratios are rejected. Defaults are 100 MiB per upload, 50 MiB total
uncompressed size, 100 archive entries, and at most 8 path levels. Configure
these with
`MEMO_VAULT_MAX_IMPORT_BYTES`, `MEMO_VAULT_MAX_ARCHIVE_UNPACKED_BYTES`,
`MEMO_VAULT_MAX_ARCHIVE_FILES`, and
`MEMO_VAULT_MAX_ARCHIVE_COMPRESSION_RATIO` (default: 200).

The dedicated DeepSeek Harness source accepts direct v4 `session.v4.jsonl`
files. It imports visible user/assistant text for normal candidate extraction
and archives `tool/call` and `tool/result` records separately. Reasoning blocks,
tool-call blocks embedded in assistant messages, and recognized Harness runtime
context are excluded from the conversation stream. ZIP-contained JSONL files
are not supported.
Markdown and HTML-like content is kept as text in the preview; the UI does not
interpret or execute it as markup or script. A full batch must parse before a
preview is created, and the original file plus normalized messages are written
to the archive only after confirmation.

On first startup, this local Vault creates and persists one stable `app_id`,
`user_id`, and `agent_id` in its SQLite database. Projects are listed and
created in the Vault's own `project_spaces` table because EverOS has no project
listing API. EverOS receives the same `app_id/project_id` for future imports;
user and assistant turns stay in one conversation session and both use the
stable `user_id`, because both are part of the user's chat history. The stable
`agent_id` is reserved for future structured tool-call experience data.
Structured tool calls are not submitted yet; tool-role rows stay in the Vault
archive for later support. The current local prototype has one Vault identity
and does not provide account login or multi-user authentication.

The default local data directory is `~/.memo-vault`. Its SQLite database stores
the Vault identity, project spaces, batches, and normalized messages. Set
`MEMO_VAULT_DATA_DIR` to choose another directory.
The EverOS endpoint defaults to `http://127.0.0.1:8000` and can be changed with
`MEMO_VAULT_EVEROS_URL`. Local extraction requests allow up to 600 seconds by
default for Ollama inference; change this with
`MEMO_VAULT_EVEROS_TIMEOUT_SECONDS`. Archival works without EverOS; extraction
failures leave the original file and normalized messages in place.

From the repository root, start the Vault API:

```bash
source .venv/bin/activate
export MEMO_VAULT_DATA_DIR="$PWD/.memo-vault"
uvicorn everos.entrypoints.memo_vault.app:app --host 127.0.0.1 --port 8765
```

In another terminal, start the UI:

```bash
cd apps/memo-vault-ui
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite forwards `/api/*` to the Vault API on port
8765. Only generic files are enabled. Import history, other platform exporters,
candidate review, and batch-detail pages remain out of scope.
