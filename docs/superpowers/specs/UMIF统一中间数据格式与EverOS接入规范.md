---
title: UMIF 统一中间数据格式与 EverOS 接入规范
version: 0.1.0-draft
status: Draft
date: 2026-10-22
audience:
  - 产品经理
  - 架构师
  - 后端开发人员
  - 数据迁移开发人员
  - 测试人员
  - 编码大模型与 Agent
---

# UMIF 统一中间数据格式与 EverOS 接入规范

## 1. 文档目的

本文定义一个面向大模型数据迁移和 Agent 记忆构建的统一中间数据格式：

> **UMIF：Unified Memory Interchange Format**

UMIF 用于将 ChatGPT、Claude、DeepSeek、DeepSeek Harness、Claude Code、Codex 等系统导出的异构数据，转换为稳定、可验证、可追溯的中间表示，再由统一编译器投递到 EverOS。

本规范同时作为：

- 数据迁移功能的产品与技术需求；
- 平台适配器的开发契约；
- UMIF 到 EverOS 编译器的实现依据；
- 测试、验收和回归评测依据；
- 编码大模型修改相关代码时的约束文档。

本文不把上游平台的导出格式当作稳定 API。所有平台数据必须先转换为 UMIF，不允许平台适配器直接写 EverOS Markdown、SQLite 或 LanceDB。

## 2. 背景和设计目标

上游平台的数据可以分为三类主要信息：

1. 用户与模型之间的对话；
2. Agent 的工具调用、执行结果和任务轨迹；
3. 项目附件、项目文档、Instructions 和知识资料。

它们在 EverOS 中对应不同的处理链路：

```text
用户与模型对话
    └── /memory/add
        └── Boundary → MemCell → Episode → Fact/Profile/Foresight

Agent 工具轨迹
    └── /memory/add（agent mode）
        └── MemCell → Agent Case → Case Cluster → Agent Skill

项目附件/项目文档
    └── /knowledge/documents
        └── Knowledge Document → Knowledge Topic → Search Index
```

UMIF 的目标是：

- 完整保存上游数据，避免过早丢失语义；
- 对 ChatGPT、Claude、DeepSeek 等来源使用统一模型；
- 兼容 EverOS 当前公开 API；
- 为 EverOS 未来增加直接记忆导入、来源追踪和分支支持保留空间；
- 支持幂等导入、失败恢复、审计和重复运行；
- 支持用户记忆、Agent 记忆和 Knowledge 三条目标链路；
- 支持大型导出包的流式解析和处理；
- 支持对导入质量进行量化测试。

## 3. 非目标

UMIF v1 不负责：

- 直接定义 EverOS 最终 Markdown 的内部格式；
- 代替 EverOS 的边界检测、记忆抽取和检索逻辑；
- 将所有平台私有字段提升为公共字段；
- 自动判断所有事实是否真实；
- 自动把 system prompt 转换成用户画像；
- 保存或传播不必要的隐藏思维链；
- 把导出包直接恢复为上游平台的可继续会话。

## 4. 规范性关键字

本文中的关键字含义如下：

- **必须（MUST）**：实现不可违反的要求；
- **不得（MUST NOT）**：实现不可执行的行为；
- **应该（SHOULD）**：除非存在明确理由，否则应遵守；
- **不应该（SHOULD NOT）**：除非存在明确理由，否则不应执行；
- **可以（MAY）**：可选能力。

## 5. 总体架构

```text
┌──────────────────────────────────────────────────────────┐
│                 平台原始导出包                            │
│ ChatGPT │ Claude │ å Web │ Harness │ 其他系统      │
└─────────┬────────┬──────────────┬─────────┬──────────────┘
          │        │              │         │
          ▼        ▼              ▼         ▼
┌──────────────────────────────────────────────────────────┐
│                  平台适配器层                             │
│ 解析、分支恢复、身份映射、文件发现、事件投影、格式校验     │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│                     UMIF Package                          │
│ Manifest │ Principal │ Session │ Event │ Asset │ Document │
│ Native Memory │ Feedback │ ID Map │ Blob Store            │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│                  UMIF → EverOS 编译器                     │
│ 验证、路由、线性化、工具配对、批处理、幂等、状态跟踪       │
└──────────────┬────────────────┬──────────────────────────┘
               │                │
               ▼                ▼
       /api/v2/memory/*  /api/v2/knowledge/*
               │                │
               ▼                ▼
      用户记忆 / Agent记忆      Knowledge Wiki
```

平台适配器只负责“源数据到 UMIF”。它不得直接决定最终 Episode、Fact、Profile、Case 或 Skill 的内容。

## 6. UMIF 包结构

推荐使用以下目录结构：

```text
umif-package/
├── manifest.json
├── principals.jsonl
├── sessions.jsonl
├── events.jsonl
├── assets.jsonl
├── documents.jsonl
├── memories.jsonl
├── feedback.jsonl
├── id-map.jsonl
├── import-ledger.sqlite
└── blobs/
    └── sha256/
        ├── ab/
        │   └── abcdef...
        └── cd/
            └── cdef12...
```

### 6.1 文件职责

| 文件 | 必需 | 说明 |
|---|---:|---|
| `manifest.json` | 是 | 包版本、来源、文件哈希、生成信息 |
| `principals.jsonl` | 是 | 用户、Agent、工具、系统身份 |
| `sessions.jsonl` | 是 | 对话、Agent Run、子 Agent 和分支关系 |
| `events.jsonl` | 是 | 消息、工具调用、工具结果和状态事件 |
| `assets.jsonl` | 否 | 图片、音频、PDF 等二进制元数据 |
| `documents.jsonl` | 否 | 项目文档、Instructions、Artifact、知识资料 |
| `memories.jsonl` | 否 | 上游平台明确保存的用户 Memory |
| `feedback.jsonl` | 否 | 点赞、点踩、任务成败和人工评分 |
| `id-map.jsonl` | 导入后必需 | UMIF ID 到 EverOS ID 的映射 |
| `import-ledger.sqlite` | 推荐 | 导入状态、幂等、重试和错误记录 |
| `blobs/` | 否 | 按 SHA-256 保存的文件内容 |

除 `manifest.json` 外，结构化记录应使用 UTF-8 JSONL。每行必须是一个完整 JSON 对象，不允许跨行 JSON。

## 7. Manifest 定义

```json
{
  "format": "umif",
  "schema_version": "1.0.0",
  "package_id": "pkg_20261022_001",
  "created_at": "2026-10-22T10:00:00Z",
  "generator": {
    "name": "umif-export-converter",
    "version": "0.1.0"
  },
  "source_exports": [
    {
      "provider": "chatgpt",
      "product": "chatgpt-web",
      "export_version": null,
      "archive_name": "chatgpt-export.zip",
      "archive_sha256": "sha256:...",
      "exported_at": null
    }
  ],
  "default_scope": {
    "workspace_id": "personal",
    "project_id": null
  },
  "files": [
    {
      "path": "sessions.jsonl",
      "sha256": "sha256:...",
      "record_count": 120
    }
  ],
  "privacy": {
    "classification": "private",
    "contains_personal_data": true
  }
}
```

Manifest 中列出的文件必须具有 SHA-256 和记录数。导入前必须验证文件哈希；验证失败时不得继续写入 EverOS。

## 8. 统一记录信封

所有 JSONL 记录使用以下公共外层：

```json
{
  "schema_version": "1.0.0",
  "record_type": "event.message",
  "record_id": "rec_4e477fb92ba75ef1",
  "source": {},
  "scope": {},
  "occurred_at": "2026-10-20T08:30:00.123Z",
  "timestamp_ms": 1792485000123,
  "sequence": 12,
  "state": "active",
  "provenance": {},
  "routing_hints": {},
  "privacy": {},
  "payload": {},
  "extensions": {}
}
```

### 8.1 公共字段

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| `schema_version` | string | 是 | UMIF SemVer 版本 |
| `record_type` | string | 是 | Discriminator |
| `record_id` | string | 是 | UMIF 全局稳定 ID |
| `source` | object | 是 | 上游来源与原生 ID |
| `scope` | object | 是 | 工作区、项目、Session、分支 |
| `occurred_at` | RFC 3339/null | 否 | 原始事件时间 |
| `timestamp_ms` | integer/null | 否 | Unix 毫秒时间 |
| `sequence` | integer | 是 | Scope 内稳定顺序，从 0 开始 |
| `state` | enum | 是 | 活跃、删除、撤销等状态 |
| `provenance` | object | 是 | 适配器、内容哈希和时间质量 |
| `routing_hints` | object | 否 | 路由建议，不是最终决策 |
| `privacy` | object | 否 | PII、脱敏和数据级别 |
| `payload` | object | 是 | 记录类型特有内容 |
| `extensions` | object | 否 | 平台私有数据 |

### 8.2 Source

```json
{
  "provider": "chatgpt",
  "product": "chatgpt-web",
  "export_version": null,
  "archive_id": "pkg_20261022_001",
  "native_type": "message",
  "native_id": "msg_abc123",
  "native_parent_id": "node_parent_001"
}
```

`provider` 建议使用稳定小写标识：

```text
chatgpt
claude
deepseek
deepseek_harness
claude_code
codex
unknown
```

### 8.3 Scope

```json
{
  "workspace_id": "personal",
  "project_id": "project-a",
  "session_id": "conv_abc123",
  "branch_id": "main"
}
```

### 8.4 State

支持：

```text
active
deleted
redacted
superseded
tombstone
```

适配器不得直接丢弃删除、编辑或被替代的消息，应使用 `state` 和引用关系保存其状态。

### 8.5 Provenance

```json
{
  "adapter": "chatgpt-export-adapter",
  "adapter_version": "1.0.0",
  "imported_at": "2026-10-22T10:00:00Z",
  "content_sha256": "sha256:...",
  "time_quality": "source"
}
```

`time_quality`：

```text
source
inferred
adjusted
unknown
```

### 8.6 Routing Hints

```json
{
  "user_memory": "allow",
  "agent_memory": "auto",
  "knowledge": "deny",
  "archive": "allow"
}
```

每个目标支持：

```text
allow
deny
auto
review
```

路由建议不得覆盖导入策略和安全策略。例如，项目文档即使被错误标记为 `user_memory=allow`，编译器仍应拒绝将其直接作为用户画像输入。

### 8.7 Extensions

所有平台专用信息必须放入命名空间：

```json
{
  "chatgpt": {},
  "claude": {},
  "deepseek": {},
  "deepseek_harness": {}
}
```

核心代码不得依赖某个平台 `extensions` 字段才能处理通用记录。

## 9. 稳定 ID 和幂等规则

### 9.1 Record ID

有原生 ID 时：

```text
record_id = UUIDv5(
  provider + native_type + native_id + branch_id
)
```

无原生 ID 时：

```text
record_id = SHA256(
  provider + session_id + sequence + canonical_payload
)
```

### 9.2 Content Hash

`content_sha256` 应基于规范化后的 `payload` 计算，不包括：

- `imported_at`；
- 运行时错误；
- EverOS 目标 ID；
- 非确定性排序字段。

### 9.3 重复导入

导入器必须使用 `record_id + content_sha256` 判断：

| 情况 | 行为 |
|---|---|
| 相同 ID、相同 Hash | 跳过 |
| 相同 ID、不同 Hash | 作为更新或冲突处理 |
| 新 ID、相同 Hash | 根据去重策略决定 |
| 已 Tombstone | 不重新写入，除非显式恢复 |

仅依赖 EverOS 当前内部消息 ID 不足以保证导入幂等。

## 10. Principal 身份定义

```json
{
  "schema_version": "1.0.0",
  "record_type": "principal",
  "record_id": "principal_user_memo",
  "source": {
    "provider": "chatgpt",
    "native_type": "account",
    "native_id": "user-123"
  },
  "scope": {
    "workspace_id": "personal",
    "project_id": null,
    "session_id": null,
    "branch_id": null
  },
  "occurred_at": null,
  "timestamp_ms": null,
  "sequence": 0,
  "state": "active",
  "provenance": {
    "adapter": "chatgpt-export-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "unknown"
  },
  "payload": {
    "principal_id": "person:memo",
    "kind": "human",
    "display_name": "Memo",
    "is_self": true,
    "is_memory_subject": true,
    "aliases": [
      {
        "provider": "chatgpt",
        "native_id": "user-123"
      },
      {
        "provider": "claude",
        "native_id": "account-456"
      }
    ]
  },
  "extensions": {}
}
```

`kind`：

```text
human
agent
tool
system
organization
unknown
```

关键字段：

- `is_self`：是否为导出数据的本人；
- `is_memory_subject`：是否允许围绕该身份形成 Fact/Profile；
- `aliases`：跨平台身份合并依据。

编译到 EverOS 时，必须生成路径安全的 `sender_id`，允许字符范围为：

```text
[a-zA-Z0-9_.@+-]+
```

原始 ID 与目标 ID 的关系必须写入 `id-map.jsonl`。

## 11. Session 定义

```json
{
  "schema_version": "1.0.0",
  "record_type": "session",
  "record_id": "session_chatgpt_abc123",
  "source": {
    "provider": "chatgpt",
    "product": "chatgpt-web",
    "native_type": "conversation",
    "native_id": "abc123"
  },
  "scope": {
    "workspace_id": "personal",
    "project_id": null,
    "session_id": "abc123",
    "branch_id": "main"
  },
  "occurred_at": "2026-10-20T08:30:00Z",
  "timestamp_ms": 1792485000000,
  "sequence": 0,
  "state": "active",
  "provenance": {
    "adapter": "chatgpt-export-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "source"
  },
  "payload": {
    "session_kind": "chat",
    "title": "旅行计划讨论",
    "participants": [
      "person:memo",
      "agent:chatgpt"
    ],
    "started_at": "2026-10-20T08:30:00Z",
    "ended_at": "2026-10-20T09:15:00Z",
    "status": "completed",
    "parent_session_id": null,
    "forked_from_event_id": null,
    "model": {
      "provider": "openai",
      "model_id": "unknown"
    },
    "context_document_ids": [],
    "working_directory": null,
    "outcome": null
  },
  "extensions": {}
}
```

`session_kind`：

```text
chat
agent_run
subagent_run
research_run
imported_memory
```

`status`：

```text
completed
failed
cancelled
interrupted
unknown
```

### 11.1 分支规则

UMIF 必须保存：

- `branch_id`；
- `parent_session_id`；
- `forked_from_event_id`；
- 消息之间的 `reply_to_event_id`；
- 编辑关系 `edited_from_event_id`。

EverOS 的单个 Session 是线性的。编译器至少支持：

- `active-branch-only`：只导入当前主分支，默认策略；
- `all-branches`：每个叶子分支生成独立 EverOS Session。

不得把互斥分支直接拼接进同一 EverOS Session。

## 12. 用户对话消息定义

```json
{
  "schema_version": "1.0.0",
  "record_type": "event.message",
  "record_id": "event_msg_001",
  "source": {
    "provider": "claude",
    "native_type": "message",
    "native_id": "msg_001"
  },
  "scope": {
    "workspace_id": "personal",
    "project_id": "writing-project",
    "session_id": "claude-conv-123",
    "branch_id": "main"
  },
  "occurred_at": "2026-10-20T08:31:00Z",
  "timestamp_ms": 1792485060000,
  "sequence": 1,
  "state": "active",
  "provenance": {
    "adapter": "claude-export-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "source"
  },
  "routing_hints": {
    "user_memory": "allow",
    "agent_memory": "auto",
    "knowledge": "deny"
  },
  "payload": {
    "message_id": "msg_001",
    "turn_id": "turn_001",
    "author_principal_id": "person:memo",
    "role": "user",
    "content_parts": [
      {
        "type": "text",
        "text": "我以后写 Python 项目时优先使用 uv。",
        "language": "zh-CN"
      }
    ],
    "reply_to_event_id": null,
    "edited_from_event_id": null,
    "finish_reason": null
  },
  "extensions": {}
}
```

### 12.1 Role

UMIF 支持：

```text
user
assistant
system
developer
observer
```

EverOS 当前只接受 `user | assistant | tool`。编译规则：

| UMIF Role | EverOS 行为 |
|---|---|
| `user` | 转换为 `user` |
| `assistant` | 转换为 `assistant` |
| `system` | 不发送给 `/memory/add` |
| `developer` | 不发送给 `/memory/add` |
| `observer` | 默认仅归档 |

System/Developer 内容应根据策略转换为：

- Project Instructions 文档；
- Knowledge Document；
- Agent 配置；
- 或仅归档。

不得把 system/developer 内容伪装成用户消息，否则会污染用户 Profile 和 Fact。

## 13. Content Part 定义

规范消息内容必须使用数组，不使用单字符串：

```json
{
  "type": "text",
  "text": "正文",
  "language": "zh-CN"
}
```

附件引用：

```json
{
  "type": "pdf",
  "asset_id": "asset_sha256_abc",
  "name": "需求文档.pdf",
  "mime_type": "application/pdf",
  "caption": "用户上传的项目需求"
}
```

UMIF 支持：

```text
text
image
audio
pdf
document
html
email
code
json
file
```

### 13.1 EverOS 映射

| UMIF | EverOS ContentItem |
|---|---|
| `text` | `text` |
| `image` | `image` |
| `audio` | `audio` |
| `pdf` | `pdf` |
| `document` | `doc` |
| `html` | `html` |
| `email` | `email` |
| `code` | `text` 或 `doc` |
| `json` | `text` 或 `doc` |
| `file` | 根据 MIME 和扩展名决定 |

EverOS 非文本 ContentItem 必须提供 `uri` 或 `base64`。UMIF 只保存 `asset_id`，编译器负责生成安全的 `file://` URI 或受限 Base64：

```json
{
  "type": "pdf",
  "uri": "file:///safe-import-root/blobs/sha256/ab/abcdef",
  "ext": "pdf",
  "name": "需求文档.pdf"
}
```

大文件应该使用 `file://` 或受控 HTTP URL，不应通过 Base64 大批量提交。

## 14. 工具轨迹定义

工具调用使用两个独立事件：

```text
event.tool_call
event.tool_result
```

该设计兼容并行调用、失败尝试、重试、Harness 事件流和 OpenAI Tool Calls。

### 14.1 Tool Call

```json
{
  "schema_version": "1.0.0",
  "record_type": "event.tool_call",
  "record_id": "event_call_001",
  "source": {
    "provider": "deepseek",
    "product": "deepseek-harness",
    "native_type": "tool_call",
    "native_id": "call_001"
  },
  "scope": {
    "workspace_id": "coding",
    "project_id": "everos",
    "session_id": "dsh-session-789",
    "branch_id": "main"
  },
  "occurred_at": "2026-10-20T08:32:00Z",
  "timestamp_ms": 1792485120000,
  "sequence": 3,
  "state": "active",
  "provenance": {
    "adapter": "deepseek-harness-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "source"
  },
  "routing_hints": {
    "user_memory": "deny",
    "agent_memory": "allow",
    "knowledge": "deny"
  },
  "payload": {
    "call_id": "call_001",
    "turn_id": "turn_001",
    "request_message_event_id": "event_assistant_001",
    "agent_principal_id": "agent:deepseek-harness",
    "tool_principal_id": "tool:exec-command",
    "tool_name": "exec_command",
    "arguments_text": "{\"cmd\":\"pytest -q\"}",
    "arguments": {
      "cmd": "pytest -q"
    },
    "parallel_group_id": null,
    "status": "requested"
  },
  "extensions": {}
}
```

`arguments_text` 必须保留原始参数；`arguments` 仅在解析成功时提供。不得假设工具参数始终是合法 JSON。

### 14.2 Tool Result

```json
{
  "schema_version": "1.0.0",
  "record_type": "event.tool_result",
  "record_id": "event_result_001",
  "source": {
    "provider": "deepseek",
    "product": "deepseek-harness",
    "native_type": "tool_result",
    "native_id": "result_001"
  },
  "scope": {
    "workspace_id": "coding",
    "project_id": "everos",
    "session_id": "dsh-session-789",
    "branch_id": "main"
  },
  "occurred_at": "2026-10-20T08:32:03Z",
  "timestamp_ms": 1792485123000,
  "sequence": 4,
  "state": "active",
  "provenance": {
    "adapter": "deepseek-harness-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "source"
  },
  "routing_hints": {
    "user_memory": "deny",
    "agent_memory": "allow",
    "knowledge": "deny"
  },
  "payload": {
    "call_id": "call_001",
    "tool_principal_id": "tool:exec-command",
    "status": "error",
    "is_error": true,
    "exit_code": 1,
    "duration_ms": 2850,
    "content_parts": [
      {
        "type": "text",
        "text": "1 failed, 32 passed"
      }
    ],
    "produced_asset_ids": []
  },
  "extensions": {}
}
```

### 14.3 EverOS 编译规则

Tool Call 必须合并到关联的 assistant 消息：

```json
{
  "sender_id": "deepseek_harness",
  "role": "assistant",
  "timestamp": 1792485120000,
  "content": "我先运行测试。",
  "tool_calls": [
    {
      "id": "call_001",
      "type": "function",
      "function": {
        "name": "exec_command",
        "arguments": "{\"cmd\":\"pytest -q\"}"
      }
    }
  ]
}
```

Tool Result 转换为：

```json
{
  "sender_id": "deepseek_harness",
  "role": "tool",
  "timestamp": 1792485123000,
  "content": "1 failed, 32 passed",
  "tool_call_id": "call_001"
}
```

无 `tool_call_id` 的结果必须被标记为 orphan。编译器必须尝试从上下文恢复；无法恢复时不得伪造关联关系。

## 15. Asset 定义

所有二进制内容按 SHA-256 去重保存：

```json
{
  "schema_version": "1.0.0",
  "record_type": "asset",
  "record_id": "asset_sha256_abcdef",
  "source": {
    "provider": "chatgpt",
    "native_type": "attachment",
    "native_id": "file-123"
  },
  "scope": {
    "workspace_id": "personal",
    "project_id": "project-a",
    "session_id": "abc123",
    "branch_id": "main"
  },
  "occurred_at": "2026-10-20T08:31:00Z",
  "timestamp_ms": 1792485060000,
  "sequence": 0,
  "state": "active",
  "provenance": {
    "adapter": "chatgpt-export-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:abcdef",
    "time_quality": "source"
  },
  "payload": {
    "asset_id": "asset_sha256_abcdef",
    "original_name": "system-design.pdf",
    "mime_type": "application/pdf",
    "extension": "pdf",
    "size_bytes": 481920,
    "sha256": "abcdef...",
    "blob_path": "blobs/sha256/ab/abcdef...",
    "source_uri": null,
    "generated_by_event_id": null,
    "attachment_scope": "project",
    "available": true
  },
  "extensions": {}
}
```

`attachment_scope`：

```text
message
session
project
workspace
generated_output
```

一个 Asset 可以同时被消息、Document 和 Tool Result 引用，不应复制文件内容。

## 16. Document 定义

消息附件与项目文档必须区分：

- 消息附件参与单次 Episode/Case 上下文；
- 项目文档进入 Knowledge，供跨会话检索。

```json
{
  "schema_version": "1.0.0",
  "record_type": "document",
  "record_id": "document_project_spec",
  "source": {
    "provider": "claude",
    "native_type": "project_file",
    "native_id": "file-456"
  },
  "scope": {
    "workspace_id": "personal",
    "project_id": "agent-memory",
    "session_id": null,
    "branch_id": null
  },
  "occurred_at": "2026-10-10T09:00:00Z",
  "timestamp_ms": 1791622800000,
  "sequence": 0,
  "state": "active",
  "provenance": {
    "adapter": "claude-export-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "source"
  },
  "routing_hints": {
    "user_memory": "deny",
    "agent_memory": "deny",
    "knowledge": "allow"
  },
  "payload": {
    "document_id": "document_project_spec",
    "document_kind": "knowledge",
    "title": "Agent Memory Requirements",
    "asset_ids": [
      "asset_sha256_abcdef"
    ],
    "inline_text": null,
    "mime_type": "application/pdf",
    "language": "zh-CN",
    "version": "1",
    "category_hint": "Technology",
    "source_type": "claude-project",
    "related_session_ids": [
      "claude-conv-123"
    ],
    "supersedes_document_id": null
  },
  "extensions": {}
}
```

`document_kind`：

```text
knowledge
project_instruction
artifact
code_snapshot
report
reference
generated_output
```

### 16.1 EverOS 路由

| Document Kind | 行为 |
|---|---|
| `knowledge` | 上传 Knowledge Document |
| `project_instruction` | 生成 Markdown 后上传 Knowledge，或进入应用配置 |
| `artifact` | 根据 MIME 和保留策略上传 Knowledge |
| `code_snapshot` | 有长期价值时上传 Knowledge |
| `report` | 上传 Knowledge |
| `reference` | 上传 Knowledge |
| `generated_output` | 默认归档，人工确认后入库 |

上传目标：

```http
POST /api/v2/knowledge/documents
```

## 17. 平台原生 Memory 定义

Claude、ChatGPT 等系统明确保存的 Memory 不应伪装成普通聊天消息，应使用 `memory.assertion`：

```json
{
  "schema_version": "1.0.0",
  "record_type": "memory.assertion",
  "record_id": "memory_claude_001",
  "source": {
    "provider": "claude",
    "native_type": "saved_memory",
    "native_id": "memory-001"
  },
  "scope": {
    "workspace_id": "personal",
    "project_id": null,
    "session_id": null,
    "branch_id": null
  },
  "occurred_at": "2026-09-12T10:00:00Z",
  "timestamp_ms": 1789207200000,
  "sequence": 0,
  "state": "active",
  "provenance": {
    "adapter": "claude-export-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "source"
  },
  "routing_hints": {
    "user_memory": "allow",
    "agent_memory": "deny",
    "knowledge": "deny"
  },
  "payload": {
    "memory_id": "memory-001",
    "subject_principal_id": "person:memo",
    "assertion_type": "preference",
    "text": "用户偏好简洁、直接的技术回答。",
    "confirmation": "provider_saved",
    "confidence": null,
    "valid_from": null,
    "valid_until": null,
    "source_event_ids": [],
    "supersedes_memory_id": null
  },
  "extensions": {}
}
```

`assertion_type`：

```text
identity
preference
goal
constraint
relationship
habit
plan
foresight
other
```

`confirmation`：

```text
user_explicit
provider_saved
model_inferred
importer_inferred
```

### 17.1 当前 EverOS 兼容路径

EverOS 当前没有直接导入 Atomic Fact/Profile 的公开 API。兼容方案是生成 `session_kind=imported_memory` 的专用 Session，将 Memory 作为带来源说明的用户消息提交，再调用 `/flush`。

该方案会经过 LLM 重新抽取，不能保证原文无损。

### 17.2 推荐的 EverOS 扩展

建议新增：

```http
POST /api/v2/memory/import
```

支持导入：

- Episode；
- Atomic Fact；
- Profile assertion；
- Foresight；
- Agent Case；
- Agent Skill。

请求必须包含：

```text
source_record_id
content_hash
provenance
idempotency_key
import_mode = trusted | reextract
```

## 18. Feedback 定义

```json
{
  "schema_version": "1.0.0",
  "record_type": "feedback",
  "record_id": "feedback_001",
  "source": {
    "provider": "chatgpt",
    "native_type": "message_feedback",
    "native_id": "feedback-001"
  },
  "scope": {
    "workspace_id": "personal",
    "project_id": null,
    "session_id": "abc123",
    "branch_id": "main"
  },
  "occurred_at": null,
  "timestamp_ms": null,
  "sequence": 0,
  "state": "active",
  "provenance": {
    "adapter": "chatgpt-export-adapter",
    "adapter_version": "1.0.0",
    "imported_at": "2026-10-22T10:00:00Z",
    "content_sha256": "sha256:...",
    "time_quality": "unknown"
  },
  "payload": {
    "target_record_id": "event_assistant_001",
    "feedback_type": "thumbs_down",
    "score": null,
    "label": "incorrect",
    "comment": null,
    "evaluator": "user",
    "task_outcome": "failed"
  },
  "extensions": {}
}
```

Feedback 默认不写入用户长期记忆。它可以用于：

- 降低 Agent Case 质量；
- 排除无效轨迹；
- 构建失败恢复案例；
- 评估 Skill 是否改善任务成功率。

## 19. 平台适配器契约

每个平台适配器必须实现以下逻辑接口：

```text
detect(input_path) -> DetectionResult
inspect(input_path) -> ExportSummary
convert(input_path, output_package, options) -> ConversionReport
validate(output_package) -> ValidationReport
```

### 19.1 `detect`

识别：

- 平台；
- 产品类型；
- 导出包版本；
- 压缩方式；
- 是否包含附件；
- 是否需要官方 codec。

### 19.2 `inspect`

只读统计，不生成 UMIF：

- 会话数；
- 消息数；
- 分支数；
- 工具调用数；
- 附件数及总大小；
- 文档数；
- 原生 Memory 数；
- 不支持的记录类型。

### 19.3 `convert`

必须：

- 生成稳定 ID；
- 保留原生 ID；
- 生成内容哈希；
- 维护事件顺序；
- 恢复分支关系；
- 提取附件到 Blob Store；
- 把平台私有字段放入 `extensions`；
- 输出错误和跳过原因。

### 19.4 `validate`

至少校验：

- JSONL 可解析；
- Schema 版本一致；
- Record ID 唯一；
- Scope 引用存在；
- Session 事件 sequence 不重复；
- Tool Result 可以解析到 Tool Call；
- Asset 文件存在且哈希正确；
- Document 引用的 Asset 存在；
- Principal 引用存在；
- 分支没有循环；
- Manifest 数量与实际记录一致。

## 20. 各平台映射要求

### 20.1 ChatGPT

| 源内容 | UMIF |
|---|---|
| Conversation | Session |
| Mapping Node | Message/Event |
| 当前叶子分支 | `branch_id=main` |
| 编辑分支 | 独立 Branch |
| Attachment | Asset |
| Library File | Asset + Document Candidate |
| User Account | Principal Alias |
| Message Feedback | Feedback |
| Model Comparison | Feedback/Evaluation Extension |

ChatGPT 对话通常是节点图。适配器必须从叶子节点沿 parent 链恢复分支顺序，不得直接依赖 JSON 对象顺序。

### 20.2 Claude

| 源内容 | UMIF |
|---|---|
| Conversation | Session + Message |
| Project | Scope/Project |
| Project Instructions | Document `project_instruction` |
| Project Knowledge | Asset + Document |
| Artifact | Document `artifact` |
| Saved Memory | `memory.assertion` |

如果导出不包含底层工具调用数据，不得根据最终回复猜测工具轨迹。

### 20.3 DeepSeek Web

| 源内容 | UMIF |
|---|---|
| Conversation | Session + Message |
| User Info | Principal Alias |
| Attachment | Asset，若实际存在 |

DeepSeek Web 主要形成用户记忆，不应默认形成 Agent Case。

### 20.4 DeepSeek Harness

| 源内容 | UMIF |
|---|---|
| Session Header | Session |
| User/Assistant Surface Event | Message |
| Tool Call | `event.tool_call` |
| Tool Result | `event.tool_result` |
| Sub-session | `subagent_run` Session |
| Attachment/File Reference | Asset/Document |
| CWD/Environment | Session Extension |
| Token Usage | Session/Event Extension |
| Failed Attempt | 状态事件或 Feedback |

Harness 日志是版本化事件流。适配器应使用对应版本的官方 codec 或逻辑事件投影，不应只写固定 V3/V4 行解析器。

## 21. UMIF 到 EverOS 的编译流程

```text
1. 验证 Manifest 与文件哈希
2. 读取 Principal，建立 sender_id 映射
3. 选择 Session 与分支
4. 按 sequence 线性化事件
5. 删除或单独路由 system/developer/observer
6. 合并 assistant Message 与 Tool Call
7. 将 Tool Result 转换为 role=tool
8. 将 Asset 转换为 EverOS ContentItem
9. 按消息数和 Token 数确定性分段
10. POST /api/v2/memory/add，defer_extraction=true
11. POST /api/v2/memory/flush
12. POST /api/v2/knowledge/documents
13. 等待 OME 和 Cascade
14. 查询 Episode/Profile/Case/Skill/Knowledge
15. 写入 id-map 和 import ledger
```

### 21.1 目标映射

| UMIF | EverOS 输入 | 预期结果 |
|---|---|---|
| Chat Session + Message | `/memory/add` | Episode、Fact、Profile、Foresight |
| Agent Run + Tool Event | `/memory/add` | Episode、Case、Skill |
| Message Asset | ContentItem | Episode/Case 上下文 |
| Project Document | `/knowledge/documents` | Document、Topic |
| Saved Memory | 合成 Session 或新 Import API | Fact/Profile/Foresight |
| Feedback | 导入器质量门控 | 影响 Case 选择 |
| System/Developer | Knowledge/配置 | 不污染用户画像 |

### 21.2 EverOS Message Payload

```json
{
  "session_id": "chatgpt-abc123-seg-001",
  "app_id": "personal-ai",
  "project_id": "personal",
  "messages": [
    {
      "sender_id": "memo",
      "sender_name": "Memo",
      "role": "user",
      "timestamp": 1792485060000,
      "content": "我以后写 Python 项目时优先使用 uv。"
    }
  ],
  "defer_extraction": true,
  "async_mode": false
}
```

一段完成后调用：

```json
{
  "session_id": "chatgpt-abc123-seg-001",
  "app_id": "personal-ai",
  "project_id": "personal"
}
```

发送至：

```http
POST /api/v2/memory/flush
```

### 21.3 分段规则

EverOS 单次 `/memory/add` 最多接受 500 条消息。编译器必须采用确定性分段：

1. 优先按源平台明确的 Session、Turn、任务边界切分；
2. 其次按长空闲时间和话题切换切分；
3. 每段建议不超过 20～50 条消息；
4. 同时设置 Token 上限；
5. Tool Call 与 Tool Result 不得跨段；
6. 一个 Agent 任务的最终 assistant 结果必须和该任务工具轨迹位于同段；
7. 重试时不得改变同一输入的分段结果。

目标 `session_id` 建议：

```text
<provider>-<native-session-hash>-seg-<number>
```

总长度不得超过 128。

### 21.4 时间戳规则

EverOS 内部消息 ID 基于：

```text
session_id + timestamp_ms + batch_index
```

编译器必须：

- 按 `sequence` 确定稳定顺序；
- 使用固定批次策略；
- 将秒转换成毫秒；
- 对同毫秒事件执行确定性微调；
- 在 UMIF 中保留原始时间和 `time_quality=adjusted`；
- 不得使用导入执行时间代替缺失的历史时间，除非显式标为 inferred。

### 21.5 Agent Mode

EverOS 当前 `memorize.mode` 是服务级配置，不是请求字段。导入包含工具轨迹的数据时必须使用：

```toml
[memorize]
mode = "agent"
```

`chat` 模式会过滤 tool 消息和带 `tool_calls` 的 assistant 消息。`agent` 模式仍会执行用户记忆流水线，因此可兼容普通对话。

建议后续为 `/memory/add` 增加请求级 `mode=chat|agent`。

### 21.6 Agent Case 形成条件

导入器不得承诺每个 Agent Session 都会生成 Case。当前默认条件包括：

- 至少三轮工具调用；
- Session 最终有 assistant 文本；
- 轨迹通过“值得提取”质量判断；
- Case 质量满足后续 Skill 聚类要求。

单个案例通常不会立即生成稳定 Skill。测试应导入多个相似高质量案例。

## 22. 用户记忆、Agent 记忆和 Knowledge 路由

### 22.1 用户记忆

适用：

- 用户与模型的普通对话；
- 用户明确表达的身份、偏好、计划、约束和经历；
- 平台明确保存的用户 Memory；
- Agent Session 中的用户任务描述。

预期生成：

```text
Episode
├── Atomic Fact
├── Foresight
└── Profile
```

项目文档中的内容不得自动当作用户事实。例如，项目文档中的公司地址不能推断为用户住址。

### 22.2 Agent 记忆

适用：

- 完整工具调用和工具结果；
- 任务目标、方法、失败、修复和结果；
- 可判断成功或失败的执行轨迹；
- 多个可聚类的相似任务。

预期生成：

```text
Agent Case
└── Agent Skill
```

普通网页问答、没有工具事件的聊天，不应被适配器伪造成 Agent 轨迹。

### 22.3 Knowledge

适用：

- 项目文档；
- Project Knowledge；
- PDF、DOCX、Markdown、代码资料；
- 长期参考报告；
- 经人工确认的 Artifact 和生成文件。

预期生成：

```text
Category
└── Knowledge Document
    └── Knowledge Topic
```

## 23. Import Ledger

推荐使用 SQLite 维护导入事务状态，至少包含：

```text
package_id
source_record_id
source_content_hash
target_app_id
target_project_id
target_session_id
target_kind
target_id
status
attempt_count
last_error
created_at
updated_at
```

状态建议：

```text
pending
validated
submitted
flushed
materialized
indexed
failed_retryable
failed_permanent
skipped_duplicate
```

EverOS 当前记忆链路并非端到端 exactly-once。导入器不得在未知失败后无条件重发整个 Session，必须先检查：

- `/tasks/{request_id}`；
- `/memory/get`；
- Markdown 文件；
- Ledger 中的上一次状态。

## 24. 安全和隐私要求

导出包可能包含账户信息、私人对话、公司文件、代码和密钥。

实现必须：

- 默认不导入手机号、邮箱、IP、设备 ID 等账户字段；
- 检测常见密钥、Token 和密码；
- 支持导入前脱敏预览；
- 不将隐藏思维链作为长期记忆；
- 不信任附件文件名和相对路径；
- 防止 ZIP Slip 和路径穿越；
- 对 Blob 使用 SHA-256 校验；
- 限制解压后的单文件和总大小；
- 对 `file://` 使用允许目录；
- 不自动执行导出包中的脚本；
- 不把文档中的提示注入内容提升为系统指令；
- 在日志中避免打印完整敏感消息和文件内容。

EverOS 默认没有内置认证。生产部署必须在 API 前增加认证、授权和网络隔离。

## 25. 错误处理

适配器和编译器必须区分：

### 25.1 可恢复错误

- 临时网络失败；
- EverOS 429；
- 异步任务尚未完成；
- Cascade 尚未同步；
- 可重试的模型或 embedding 错误。

### 25.2 永久错误

- JSON 结构无法识别；
- 文件哈希不一致；
- Tool Result 永远找不到 Call；
- 不支持的附件格式；
- 非法路径；
- ID 冲突且无冲突策略；
- 未来版本日志无法解码。

失败记录必须保留原始 `record_id`、错误码和安全摘要，不得静默跳过。

## 26. 验证规则

UMIF Validator 至少检查：

1. Manifest 与文件哈希一致；
2. Schema 版本受支持；
3. 每个 `record_id` 唯一；
4. `source.native_id` 在适用时存在；
5. Scope 引用有效；
6. Principal 引用有效；
7. Session 内 `sequence` 唯一且可排序；
8. Tool Result 引用存在的 Tool Call；
9. Tool Call 引用有效的 assistant Message；
10. Asset 文件存在、大小与哈希正确；
11. Document 引用的 Asset 存在；
12. 分支关系无循环；
13. 时间戳为正整数或明确标记缺失；
14. Content Part 类型可识别；
15. EverOS 目标 ID 可以安全映射；
16. Blob 路径不能离开 Package Root。

## 27. 测试方案

### 27.1 适配器保真测试

| 指标 | 验证内容 |
|---|---|
| 会话覆盖 | 源会话数与 UMIF Session 数 |
| 消息覆盖 | 源消息数、转换数、跳过数 |
| 顺序 | Role、sequence、timestamp |
| 分支 | 当前分支、编辑分支、父子关系 |
| 工具配对 | Call/Result 配对率 |
| 附件 | 数量、大小、SHA-256 |
| 文档 | Project 文件和 Instructions |
| 原生 Memory | 数量与原文一致 |
| 幂等 | 相同导出转换两次结果一致 |

### 27.2 EverOS 物化测试

检查：

- `/flush` 后 Episode Markdown 存在；
- Fact 和 Profile 最终生成；
- 合格 Agent 轨迹生成 Case；
- 多个相关 Case 最终形成 Skill；
- Knowledge Document 和 Topic 可查询；
- Cascade pending 最终归零；
- 删除派生索引后重建，检索结果基本等价。

### 27.3 Golden Set

测试集应人工标注：

```text
预期 Episode 边界
预期 Fact
禁止提取的 Fact
预期 Profile 字段
预期 Agent Case
任务成功/失败标签
预期 Skill 聚类
预期 Knowledge Topic
```

### 27.4 检索评测

指标：

- Recall@1、Recall@5；
- MRR、nDCG；
- Fact Precision/Recall；
- Profile 准确率；
- 无依据画像推断率；
- Case 提取率；
- Skill 聚类纯度；
- Knowledge Topic 覆盖率；
- 跨用户、跨项目泄漏率；
- Prompt Token、延迟和模型成本。

### 27.5 必测场景

1. 用户偏好发生更新或冲突；
2. 同一会话包含多个话题；
3. 同一导出包重复导入；
4. 导入过程中服务重启；
5. Tool Call 缺 Result；
6. Tool Result 缺 Call；
7. Agent 工具失败后恢复成功；
8. 多个相似 Agent Case 形成 Skill；
9. PDF/文档进入 Knowledge 后精确问答；
10. 用户 A 的记忆不能被用户 B 查询；
11. 项目 A 文档不能进入项目 B；
12. 删除 LanceDB 后重建索引；
13. 导出包包含路径穿越文件名；
14. 文档包含提示注入文本；
15. 多条消息共享同一毫秒时间戳。

## 28. 可视化和查看要求

UMIF 和 EverOS 数据适合构建以下视图：

### 28.1 用户记忆时间线

```text
Session → Episode → Atomic Fact
                  → Foresight
                  → Profile Change
```

### 28.2 Agent Case/Skill 图

```text
Source Session
  └── Tool Calls
      └── Agent Case
          └── Agent Skill
```

### 28.3 Knowledge 树

```text
Category
└── Document
    ├── Topic
    └── Original Asset
```

### 28.4 导入状态面板

至少展示：

- Package 和平台；
- Session、Message、Tool、Asset、Document 数量；
- pending/success/failed/skipped；
- Episode、Fact、Profile、Case、Skill 产出数量；
- OME 与 Cascade 状态；
- orphan tool result；
- 冲突和重复记录；
- 导入耗时与模型成本。

## 29. 实施阶段

### 阶段一：UMIF Core

实现：

- Manifest；
- Envelope；
- Principal；
- Session；
- Message；
- Tool Call/Result；
- Asset；
- Document；
- Validator；
- Import Ledger。

### 阶段二：平台适配器

建议顺序：

1. ChatGPT；
2. Claude；
3. DeepSeek Web；
4. DeepSeek Harness；
5. Claude Code/Codex。

### 阶段三：EverOS 编译器

实现：

- Principal 到 sender_id 映射；
- Session 分支选择；
- 工具调用合并；
- ContentItem 转换；
- 确定性分段；
- `/memory/add` 和 `/flush`；
- Knowledge 上传；
- OME/Cascade 等待；
- ID Map 回填。

### 阶段四：原生 Memory 与 Feedback

实现：

- `memory.assertion`；
- Feedback；
- Fact/Profile trusted import；
- Case 质量门控；
- 冲突和 supersede。

### 阶段五：可视化和评测

实现：

- 用户记忆时间线；
- Profile 视图；
- Case/Skill 关系图；
- Knowledge 树；
- 导入质量报告；
- A/B 评测。

## 30. Definition of Done

UMIF v1 第一阶段完成必须满足：

- [ ] JSON Schema 或 Pydantic 模型覆盖所有核心 Record Type；
- [ ] 同一个导出包重复转换产生字节级稳定的核心记录；
- [ ] Validator 可以发现坏引用、坏哈希和工具孤儿；
- [ ] ChatGPT、Claude、DeepSeek Web 各有真实脱敏 fixture；
- [ ] DeepSeek Harness 使用版本化 decoder 或官方逻辑事件投影；
- [ ] 普通对话可生成 EverOS Episode；
- [ ] 用户 Fact/Profile 最终可查询；
- [ ] 合格工具轨迹可生成 Agent Case；
- [ ] 多个相关案例可形成 Agent Skill；
- [ ] 项目文档可形成 Knowledge Document 和 Topic；
- [ ] 重复导入不会重复写入；
- [ ] 导入失败可以从 Ledger 安全恢复；
- [ ] 不存在跨用户、跨项目检索泄漏；
- [ ] 附件哈希和路径安全测试通过；
- [ ] 导入报告能解释所有跳过和失败记录；
- [ ] 开发文档包含新增字段的迁移策略。

## 31. 给编码大模型的执行说明

当编码大模型根据本文修改项目时，必须遵守：

1. 先检查当前 EverOS 版本、API DTO 和存储实现，不得仅根据本文猜测代码结构；
2. 先实现 UMIF Domain Model 和 Validator，再实现平台适配器；
3. 平台解析代码不得直接依赖 EverOS persistence 层；
4. EverOS 编译器不得读取平台私有 JSON，只接受 UMIF；
5. 所有 ID、排序、分段和哈希逻辑必须确定性；
6. 新增字段必须考虑旧 UMIF 包的兼容性；
7. 不得把 system/developer 消息转换成 user；
8. 不得根据自然语言猜测不存在的工具调用；
9. 不得执行导出包中的代码或脚本；
10. 不得在日志和测试快照中泄露真实用户数据；
11. 必须为每个平台建立最小、分支、多模态和损坏输入 fixture；
12. 必须测试重复导入、部分失败和进程重启；
13. 修改 EverOS API 时必须更新 OpenAPI、API 文档和集成测试；
14. 如果源码实现与本文冲突，应记录差异并更新规范，不得静默采用另一种语义；
15. 完成后必须报告支持范围、未支持字段、数据损失点和迁移风险。

建议编码顺序：

```text
models
→ canonical serialization
→ validator
→ fixture
→ one provider adapter
→ EverOS compiler
→ import ledger
→ integration tests
→ additional adapters
→ visualization
```

## 32. 相关资料

- EverOS 仓库：<https://github.com/EverMind-AI/EverOS>
- EverOS API：<https://github.com/EverMind-AI/EverOS/blob/main/docs/api.md>
- EverOS Memory：<https://github.com/EverMind-AI/EverOS/blob/main/docs/how-memory-works.md>
- EverOS Storage：<https://github.com/EverMind-AI/EverOS/blob/main/docs/storage_layout.md>
- EverOS Knowledge：<https://github.com/EverMind-AI/EverOS/blob/main/docs/knowledge.md>
- EverOS Multimodal：<https://github.com/EverMind-AI/EverOS/blob/main/docs/multimodal.md>
- OpenAI 数据导出：<https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-%20data>
- Anthropic 数据导出：<https://privacy.claude.com/en/articles/9450526-export-your-claude-data>
- DeepSeek Harness Session Export：<https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session-query/session-log-export/README.md>

## 33. 待决策事项

以下事项需要在开发前或阶段一内确认：

1. UMIF Schema 使用 JSON Schema、Pydantic，还是两者都生成；
2. `import-ledger.sqlite` 是否属于 UMIF Package，还是导入器运行目录；
3. 原生 Memory 第一版采用合成 Session，还是直接开发 `/memory/import`；
4. ChatGPT 多分支默认只导入活动分支，还是允许用户选择；
5. 项目 Instructions 默认进入 Knowledge，还是独立配置存储；
6. `code_snapshot` 的大小和保留策略；
7. 是否允许同一个 Document 同时作为消息附件和 Knowledge；
8. Profile 和 Skill 更新历史是否使用 Git 保存；
9. 可视化界面直接读取 EverOS API，还是增加统一查询服务；
10. 是否需要为导入来源增加 EverOS 原生 provenance 字段。

