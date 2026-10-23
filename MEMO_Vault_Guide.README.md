# EverOS 项目结构与开发上手指南

> 盘点基准：当前工作区代码，2026-10-23；包含尚未提交的实现。此分支正在开发 MEMO Vault 相关能力；本指南描述工作区现状，不代表这些改动已经合并或发布。

## 1. 项目是什么

EverOS 是供 AI Agent 和对话应用使用的本地优先记忆框架。它负责从对话中整理记忆、保存记忆并在之后检索。正式记忆以 Markdown 文件为准，SQLite 保存运行状态，LanceDB 保存可重建的搜索索引。

当前工作区还包含 **MEMO Vault**：一个本地记忆管理界面，让用户导入对话、查看和审核候选记忆、管理已确认记忆，并将选定的记忆导出为 Memory Pack。它由 React 前端和独立的 FastAPI 服务组成，通过 HTTP 调用 EverOS。

```text
浏览器中的 MEMO Vault（React / Vite，默认 5173 端口）
                 │ /api/*
MEMO Vault API（FastAPI，默认 8765 端口）
  ├─ SQLite：项目、导入批次、消息、候选关联和审计记录
  ├─ 证据归档：原始导入文件
  └─ EverOSAdapter：调用 EverOS API
                 │
EverOS API（FastAPI，默认 8000 端口）
  ├─ Markdown：正式记忆
  ├─ SQLite：系统状态
  └─ LanceDB：搜索索引
```

这两套 API 是两个独立服务。MEMO Vault 的 `/api/v1` 和 EverOS 的 `/api/v1` 路径前缀相同，但默认监听不同端口。

## 2. 仓库根目录

| 目录或文件 | 内容与用途 |
|---|---|
| `src/everos/` | Python 后端主程序，见下文的分层说明。 |
| `apps/memo-vault-ui/` | MEMO Vault 的 React、TypeScript、Vite 前端。 |
| `tests/` | 单元、集成和端到端测试，以及测试用的样例数据。 |
| `docs/` | API、架构、配置、存储、运维说明，以及 MEMO Vault 需求和设计记录。 |
| `benchmarks/` | 记忆检索等能力的评测适配器、配置、数据和指标。 |
| `examples/` | EverOS 与 Langfuse、本地 Ollama 等环境的示例。 |
| `use-cases/` | Claude Code 插件、演示项目和外部项目集成样例。 |
| `scripts/` | 开发、数据处理和端到端流程辅助脚本。 |
| `deploy/` | 部署辅助内容；目前包含 Netlify relay。 |
| `data/` | 仓库工作区数据目录，不是 Python 源码入口。 |
| `.github/`、`.claude/`、`.agents/` | CI、协作规范、代码规则和开发流程配置。 |
| `pyproject.toml`、`uv.lock`、`Makefile` | Python 项目信息、锁定依赖和常用开发命令。 |
| `README.md`、`README.zh-CN.md`、`QUICKSTART.md` | 项目简介和使用入门。 |
| `MEMO_VAULT_MVP_DEVELOPMENT_PLAN_*.zh-CN.md` | MEMO Vault 方案与迭代计划；部分内容早于当前代码。 |

`.venv/`、`apps/memo-vault-ui/node_modules/`、`dist/` 和缓存目录属于本地依赖、构建产物或工具缓存，不是主要业务源码。`.everos-local/`、`.everos-ollama/` 和 `.memo-vault/` 是本机配置或运行数据目录，也不是 Python 包的一部分。

## 3. 后端代码怎么分层

主要代码位于 `src/everos/`，按“入口接收请求、业务层组织流程、记忆领域处理规则、基础设施读写数据”的方向划分：

| 目录 | 用通俗的话说 | 常见内容 |
|---|---|---|
| `entrypoints/api/` | EverOS 的 HTTP 接口入口 | FastAPI 应用、健康检查、记忆、知识库和其他 API 路由。 |
| `entrypoints/memo_vault/` | MEMO Vault 的独立后端 | Vault FastAPI 应用、导入解析、UMIF 投影、项目与候选管理、记忆库、Memory Pack、EverOS 适配器。 |
| `umif/` | 各来源共用的中间数据格式 | 记录模型、稳定 ID、包读写和导入前校验；不依赖 DeepSeek 或 Vault 数据库。 |
| `entrypoints/cli/` | 命令行入口 | `everos` 命令及其子命令。 |
| `entrypoints/tui/` | 终端界面入口 | 文本界面和交互演示。 |
| `service/` | 业务流程协调层 | 把入口、记忆规则和存储能力串成“添加、检索、候选发布”等用例。 |
| `memory/` | 记忆业务规则 | 抽取、检索、级联处理、生命周期和提示词相关逻辑。 |
| `infra/` | 数据读写实现 | Markdown、SQLite、LanceDB、Milvus 等存储适配，以及后台任务实现。 |
| `core/` | 多模块共用的运行底座 | 应用生命周期、上下文、中间件、日志、指标、追踪和持久化接口。 |
| `component/` | 可替换的外部能力 | LLM、Embedding、重排、解析、分词、配置和通用工具。 |
| `config/` | 默认配置与提示词配置 | 应用设置和 Prompt Slot 默认内容。 |
| `templates/` | 随程序分发的模板 | 初始化配置等模板文件。 |

排查一个请求时，可以从 `entrypoints` 找到路由，再沿着调用进入 `service`、`memory`，最后查看 `infra` 中的数据读写实现。MEMO Vault 自己的导入、候选、记忆库和 Memory Pack 逻辑主要在 `entrypoints/memo_vault/`，它通过 `EverOSAdapter` 与核心服务交互。

### MEMO Vault 关键实现入口

| 功能 | 优先阅读的文件（相对于仓库根目录） |
|---|---|
| 导入与 UMIF | `entrypoints/memo_vault/imports.py`、`deepseek_harness.py`、`umif_projection.py`（均在 `src/everos/` 下），以及 `src/everos/umif/`。 |
| 候选抽取 | `src/everos/entrypoints/api/routes/memo_vault_candidates.py`、`src/everos/service/memo_vault_candidates.py` 与 `memo_vault_candidate_prompts.py`。 |
| 人工候选与审核 | `src/everos/entrypoints/memo_vault/routes/candidates.py`、`contracts.py`、`storage.py`。 |
| 来源片段与定位 | `src/everos/entrypoints/memo_vault/evidence.py`；候选来源接口和记忆库共用。 |
| 正式记忆与生命周期 | `src/everos/entrypoints/memo_vault/library.py`、`adapter.py`，以及 `src/everos/service/memo_vault_lifecycle.py`。 |
| Memory Pack | `src/everos/entrypoints/memo_vault/memory_pack.py`、`routes/exports.py`、`library.py`。 |

上表中未单独写出完整路径的文件名，与同一格前面的文件位于同一目录。

### MEMO Vault 前端

`apps/memo-vault-ui/` 是独立的网页前端：

- `src/App.tsx`：页面导航和导入、候选审核、记忆库、Memory Pack 等页面流程。
- `src/api.ts`：浏览器调用后端的 API 函数和数据类型。
- `src/styles.css`：页面样式。
- `src/main.tsx`：React 应用启动入口。
- `vite.config.ts`：开发时把 `/api/*` 请求转发给本机 8765 端口的 Vault API。

## 4. MEMO Vault 新需求与当前代码状态

以下状态按当前工作区源代码判断。“接口已声明”不一定意味着功能完整；例如 ADP Export 的路由存在，但处理函数仍返回未实现错误。

| 功能 | 当前代码中的职责和状态 |
|---|---|
| 导入与归档 | 已实现预览、文件安全检查、重复检测、确认归档和抽取请求。通用格式支持 JSON、Markdown、TXT 和受限 ZIP；DeepSeek Harness v4 支持直接导入 `session.v4.jsonl` 或仅含该文件的安全 ZIP。两条路径先转换成 UMIF 并校验，再投影到 Vault；预览可查看记录数、校验摘要和来源事件冲突，冲突会阻止归档。原文件与 UMIF 包一起保留，抽取失败不会删除它们。UMIF 目前是内部转换与归档格式，不等于已开放任意 UMIF 包上传入口。 |
| 候选抽取与中文输出 | 按 MemCell 生成情节（Episode）和画像（Profile）草稿，显式使用中文提示语。画像只读取用户消息，要求证据能匹配用户原文，过滤缺少中文、琐碎或重复的结果；当前不是调用独立偏好抽取函数的流程。抽取本身不写入正式记忆。 |
| 候选审核 | 已有列表筛选、编辑、逐条确认/拒绝及前端批量审核。当前界面只提供情节、画像两类；画像在候选契约中仍用 `kind=preference`，新候选的实际 `memory_type=profile`。历史事实、决策、待办等值仍有兼容逻辑，不代表界面继续开放这些类型。 |
| 人工新增 | 可填写情节或画像、项目空间、长期/30 天/90 天有效期、外发策略及正文，保存后进入待审核列表；确认后才发布到 EverOS，有效期从确认时起算。保留 `origin=manual`、`evidence_kind=human_authored` 标记，不伪造原文件或对话证据，也不要求导入来源校验。 |
| 来源证据与原对话 | 新抽取保存有序消息、字符范围和输入哈希，展示精确输入片段（`exact_input`）；旧数据回退为关联消息（`linked_messages`）。候选弹窗和记忆库详情共用来源片段及按当前正文计算的关键位置，可展开完整归档聊天并定位。原文件读取检查安全路径及 SHA-256；没有匹配摘录不等于来源丢失。当前关键位置使用词面匹配，未接入语义召回。 |
| 记忆库 | 已有正式记忆列表、搜索、详情、修正、撤销和删除标记相关接口。默认从 EverOS 正式记忆读取，再结合 Vault 的项目范围和生命周期信息展示。 |
| **Memory Pack 导出** | **已实现预览与导出。** 用户可按项目空间、记忆类型（事实、情节、画像）和近似 token 预算选择内容；格式支持 Markdown 或 `vault-memory/1` JSON。Markdown 只输出记忆正文；JSON 可选择不带证据、仅证据 ID 或带匹配摘录。只有已确认的 EverOS 正式记忆可进入 Pack；`deny` 项被排除，`ask` 项需要逐条选择并在交付前确认。服务端会重新核对预览快照，提示预算排除项；含来源摘录时要求确认，复制或下载前也要求确认内容交付后无法撤回。导出记录包含范围、格式、版本和内容哈希等信息。 |
| ADP Export Beta | 前端展示 Beta 入口，后端有 3 条 API 路由，但当前处理函数仍调用 `not_implemented`，不能视为已可导出。 |
| 账号、多用户与完整加密 | 方案中有相关安全和产品目标；当前代码仍是单机本地 Vault 身份，不应描述成已支持多账号、登录隔离或完整加密保险箱。 |
| 外部 API/MCP 交付、多平台连接与自动抓取 | 当前 Pack 可经本地预览/导出接口复制或下载；面向外部客户端的授权交付 API/MCP 仍是提案，没有客户端凭证或授权包注册表。EverOS 既有 MCP 集成不能视为 Vault 授权导出。其他部分来源仍未开放自动同步。 |

**文档与代码有时间差。** `MEMO_VAULT_MVP_DEVELOPMENT_PLAN_V4.zh-CN.md` 和 `apps/memo-vault-ui/README.md` 描述的基线较早，其中把候选审核、记忆库或 Memory Pack 标记为规划中；当前工作区对应路由、页面和服务代码已经增加。本指南以代码为现状依据，同时保留上述尚未实现的边界。

### 导入到正式记忆的实际流程

1. 文件预览：通用导入或 DeepSeek Harness 适配器转换成 UMIF，检查结构、引用、文件哈希及重复/冲突，再生成 Vault 预览。
2. 确认归档：保存原文件、UMIF 包及标准化消息、独立工具轨迹。归档成功与抽取成功是两个状态；可先归档、稍后抽取。
3. 请求抽取：Vault 按会话读取非重复且 `memory_input=1` 的消息，调用 EverOS 的候选抽取接口。DeepSeek 保留所有已解析的可见 user/assistant 消息供回看，但仅用户消息和每轮最后一条符合条件的助手回复参与抽取；若该轮最后一条助手消息没有可见文本或含工具调用，该轮不纳入助手回复。`reasoning` 不转换成对话，工具调用/结果另存轨迹。
4. 划分 MemCell：先按约 2,200 tokens、最多 20 条消息分块，单条长消息按约 1,400 tokens 切片并保留字符偏移，再做话题/时间边界检测。Episode 使用该单元；Profile 只使用其中的用户片段及可匹配原话证据。Profile 的格式或 LLM 错误会跳过当前单元的画像并保留已生成情节，不应据此认为每批都会产生画像。
5. 人工审核：核对来源、改写正文并设置项目、有效期和外发策略；确认后才调用 EverOS 发布。人工新增从审核队列开始，不经过文件导入与抽取。
6. 管理与导出：记忆库读取 EverOS 正式正文，结合 Vault 保存的来源及生命周期展示。修正、撤销、删除后，后续 Pack 会重新读取并检查状态；已交付的内容无法收回。

原文件可用、输入片段可还原和关键句已定位是三个不同状态，均不等于机器已核实记忆内容正确。升级解析器后的行为不会自动回写旧批次或旧候选。

## 5. API 数量与入口

### 统计口径

以下数字按 FastAPI 源码中显式声明的 HTTP 方法和路由计算：同一个方法与路径算一个操作；不计 FastAPI 自动提供的 `/docs`、`/openapi.json` 等文档端点，也不把同一路由因版本前缀不同而误算成不同业务功能。

| 服务 | 不同接口操作 | 实际挂载说明 |
|---|---:|---|
| EverOS 核心 API | **20** | 18 个业务操作分别挂在 `/api/v1` 和 `/api/v2`，另有不带版本前缀的 `/health`、`/metrics`，共 38 个方法与路径组合。 |
| MEMO Vault API | **25** | 全部挂在独立服务的 `/api/v1` 下；其中 3 个 ADP 操作是未实现占位。 |
| 合计 | **45** | 这是两个 FastAPI 应用的源码路由声明数，不代表同一端口上的 45 个可用接口。 |

### EverOS 核心 API：20 个操作

除 `/health` 和 `/metrics` 外，核心业务 API 同时接受 `/api/v1` 和 `/api/v2` 前缀；`/api/v2` 是当前规范名称，`/api/v1` 是兼容入口。

| 范围 | 数量 | 用途 |
|---|---:|---|
| `/health`、`/metrics` | 2 | 服务健康与运行指标。 |
| `/memory/*` | 4 | 添加记忆、结束批次写入、搜索和读取记忆。 |
| `/memo-vault/candidates/*` | 3 | 从对话抽取候选、发布人工批准的候选、修改已发布记忆生命周期。 |
| `/ome/trigger` | 1 | 手动触发离线记忆整理流程。 |
| `/knowledge/*` | 9 | 上传、替换、删除、查询知识文档与主题、知识搜索和分类列表。 |
| `/cascade/quiesce` | 1 | 控制后台级联任务停止接收新工作。 |

### MEMO Vault API：25 个操作

以下路径都以 `/api/v1` 开头，但运行在 MEMO Vault 服务（默认 8765 端口），不是 EverOS 核心 API（默认 8000 端口）。

| 范围 | 数量 | 用途 |
|---|---:|---|
| `/system/health` | 1 | Vault 和 EverOS 健康状态。 |
| `/projects` | 2 | 查询和创建项目空间。 |
| `/imports/*` | 5 | 预览、提交归档、取消预览、发起抽取、查询导入状态和 UMIF 校验摘要。 |
| `/candidates`、`/candidates/*` | 6 | 人工新增、候选列表、GET/POST 两种来源读取（POST 可传当前草稿正文定位）、确认和拒绝。 |
| `/memories/*` | 6 | 记忆概览、查询、详情、修正、撤销和删除。 |
| `/packs/preview`、`/packs/export` | 2 | Memory Pack 预览与正式导出。 |
| `/adp/*` | 3 | 轨迹列表、校验、导出；当前为未实现占位。 |

## 6. 第一次阅读建议

1. 先读 [中文项目介绍](../../../README.zh-CN.md) 和 [Quickstart](../../../QUICKSTART.md)，了解 EverOS 的使用方式。
2. 再读 [架构说明](../../architecture.md) 与 [记忆工作方式](../../how-memory-works.md)，了解代码分层和数据流。
3. 查核心 API 时读 [EverOS API 参考](../api.md)；Vault API 从 `src/everos/entrypoints/memo_vault/routes/` 及本文第 5 节开始。
4. 阅读 [候选抽取说明](memo_vault_candidate_extraction.md)、[UMIF 规范](UMIF统一中间数据格式与EverOS接入规范.md)、[来源片段设计](2026-10-23-memcell-evidence-and-chinese-output-design.md) 和 [人工新增实施记录](../plans/2026-10-23-manual-memory-candidate.md)。设计中的偏好/事实类型映射已有后续调整，应以当前源码为准。
5. [外部 API/MCP 交付提案](../plans/2026-10-23-memory-pack-api-mcp-proposal.md) 用于了解后续方向，不能作为已实现能力说明。
6. 按功能追代码：前端从 `apps/memo-vault-ui/src/App.tsx` 开始，后端从对应 `entrypoints/.../routes/` 开始，再跟到服务和存储实现。相关测试位于 `tests/unit/test_entrypoints/test_memo_vault_*.py`、`test_deepseek_harness.py`、`test_umif_end_to_end.py`、`tests/unit/test_umif/` 及服务/API 路由测试目录；测试文件存在不代表本次已执行通过。

## 7. 本机启动 MEMO Vault（Ollama，五终端方式）

下面以 **Ubuntu / WSL2 + Bash** 为例，仓库路径为 `~/EverOS`。首次使用先完成环境准备，之后日常使用直接按后面的五终端流程启动。服务地址分别是 Ollama `11434`、EverOS `8000`、Vault `8765`，前端为 `5173`。

### 首次使用：安装工具和依赖

`source .venv/bin/activate` **只激活已有虚拟环境，不会创建环境或下载依赖**。新用户需要先安装工具，再安装项目依赖。

| 工具/环境 | 要求与用途 |
|---|---|
| Git、curl | 获取代码、下载安装工具和检查 HTTP 接口。 |
| Python | 项目要求 **3.12 及以上**；下面固定用 3.12，由 uv 安装。 |
| uv | 根据 `pyproject.toml` 和 `uv.lock` 创建 `.venv` 并安装后端依赖。 |
| Node.js、npm | 使用 Node.js **22.12+ 的 22 系列或 24 LTS**；当前前端依赖的引擎范围为 `^20.19.0 || >=22.12.0`，新环境可选 24 LTS。 |
| Ollama | 运行聊天模型与 embedding 模型；模型需要另外下载，见终端 2。 |

**1. 安装基础工具和 uv。** 已安装的工具可以跳过。Ubuntu / WSL2 中执行：

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

uv 安装方式见 [官方安装文档](https://docs.astral.sh/uv/getting-started/installation/)。Node.js 请按 [官方下载页](https://nodejs.org/en/download) 选择 Linux 对应的安装方式，安装后在当前终端检查：

```bash
node --version
npm --version
```

Node.js 版本门槛也可查 [Vite 官方说明](https://vite.dev/guide/)。在 WSL2 中应使用 Linux 侧的 Node.js/npm，并在 WSL2 终端执行本文命令。

**2. 安装 Ollama。** Linux / WSL2 安装命令来自 [Ollama 官方下载页](https://ollama.com/download/linux)：

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
```

安装后是否已自动启动服务，以后面的终端 1 检查为准。本指南按 Ollama 与后端运行在同一 Linux / WSL2 环境、通过 `127.0.0.1:11434` 连接配置。

**3. 准备本项目源码。** 使用包含本文所述 MEMO Vault 实现的代码副本，并放到 `~/EverOS`；当前工作区仍含未提交实现，直接克隆上游仓库不保证包含这些功能。拿到项目后先确认关键文件存在：

```bash
cd ~/EverOS
ls pyproject.toml uv.lock
ls src/everos/entrypoints/memo_vault/app.py
ls apps/memo-vault-ui/package.json apps/memo-vault-ui/package-lock.json
```

**4. 创建 Python 虚拟环境并安装后端依赖。**

```bash
cd ~/EverOS
uv python install 3.12
uv sync --locked --python 3.12
source .venv/bin/activate
python --version
python -c "import everos, fastapi, uvicorn, multipart; print('Backend dependencies OK')"
.venv/bin/everos --help
```

`uv sync` 会创建仓库下的 `.venv/`，安装本地 EverOS 包、FastAPI、Uvicorn、上传解析、存储、模型客户端和 EverAlgo 等声明的依赖；无需逐个手动 `pip install`。`--locked` 使用仓库锁文件并检查它与依赖声明是否一致，失败时先确认拿到的 `pyproject.toml` 与 `uv.lock` 属于同一版本。

**5. 安装前端依赖。**

```bash
cd ~/EverOS/apps/memo-vault-ui
npm ci
cd ~/EverOS
```

`npm ci` 根据 `package-lock.json` 安装 React、TypeScript、Vite 等依赖到 `node_modules/`。Python 的 `.venv` 不包含这些前端依赖，也不包含 Ollama 程序或模型。首次准备需要联网下载这些工具、依赖和模型。

### 首次使用：准备配置文件

项目已提供依赖清单和 Ollama 配置样例，无需从另一台机器复制 `.venv/` 或另写一份 `requirements.txt`。各类文件的用途如下：

| 文件 | 用途 |
|---|---|
| `pyproject.toml`、`uv.lock` | 后端依赖声明及锁定版本，交给 `uv sync` 安装。 |
| `apps/memo-vault-ui/package.json`、`package-lock.json` | 前端依赖声明及锁定版本，交给 `npm ci` 安装。 |
| `examples/local-ollama/everos.toml` | 可复用的 Ollama 模型配置样例，首次复制到独立 memory root。 |
| `.everos-ollama/everos.toml`、`ome.toml` | EverOS 的本机运行配置，由初始化命令生成；前者再换成本地 Ollama 样例。 |
| `examples/local-ollama/memo-vault.env.example` | Vault 环境变量样例，可复制并在启动 Vault 的终端显式加载。 |

**1. 初始化 EverOS 的独立运行目录。以下仅在首次创建 `.everos-ollama` 时执行：**

```bash
cd ~/EverOS
.venv/bin/everos init --root .everos-ollama
cp examples/local-ollama/everos.toml .everos-ollama/everos.toml
```

已有配置的用户直接检查文件，保留自己的配置，不要重复执行上面的复制命令。样例配置的关键值为：

| 配置项 | 本地值 |
|---|---|
| `llm.model` | `qwen2.5:3b` |
| `embedding.model` | `qwen3-embedding:0.6b` |
| 两者的 `base_url` | `http://127.0.0.1:11434/v1` |
| 两者的 `api_key` | `ollama`，仅为非空占位值，无需购买或填写真实 Key。 |
| `memorize.mode` | `chat` |

完整参数见 [Ollama 配置样例](../../../examples/local-ollama/everos.toml)。模型名称必须与终端 2 下载的名称一致。

**2. 可选：把 Vault 环境变量保存为本机配置文件。** 首次创建：

```bash
cd ~/EverOS
mkdir -p .memo-vault
cp examples/local-ollama/memo-vault.env.example .memo-vault/runtime.env
```

之后可编辑 `.memo-vault/runtime.env`。文件内容如下，其中 `$PWD` 在加载时展开，因此要先进入仓库根目录：

```bash
export MEMO_VAULT_DATA_DIR="$PWD/.memo-vault"
export MEMO_VAULT_EVEROS_URL="http://127.0.0.1:8000"
export MEMO_VAULT_EVEROS_TIMEOUT_SECONDS=600
```

Vault 当前直接读取进程环境变量，**不会自动加载这个文件**。终端 4 可以保留后面的 `export` 方式，也可以替换为：

```bash
cd ~/EverOS
source .venv/bin/activate
source .memo-vault/runtime.env
uvicorn everos.entrypoints.memo_vault.app:app --host 127.0.0.1 --port 8765
```

两种方式选择一种即可。`.memo-vault` 的 SQLite 数据库、证据目录和本地身份由 Vault 首次启动自动初始化；不需要额外安装数据库服务器。以后在新终端仍需激活环境并设置或加载变量，但不需要每次重装依赖。切换数据目录会切换所使用的 Vault 数据和身份，应固定使用同一目录。

完成以上准备后，按下面五个终端启动；Ollama 的进程参数仍在终端 1 设置，模型仍在终端 2 下载。

### 终端 1：启动 Ollama

若 Ollama 已由系统服务启动，先检查：

```bash
systemctl status ollama
```

如果服务正在运行，不要再运行第二个 `ollama serve`。如果 WSL 没有 systemd 服务，就在此终端启动：

```bash
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_CONTEXT_LENGTH=8192
ollama serve
```

这些环境变量作用于此终端启动的 Ollama 进程；不会修改已经运行的系统服务配置。

### 终端 2：下载并检查模型

```bash
cd ~/EverOS
ollama pull qwen2.5:3b
ollama pull qwen3-embedding:0.6b
ollama list
curl http://127.0.0.1:11434/api/tags
```

### 终端 3：启动 EverOS API

```bash
cd ~/EverOS
.venv/bin/everos server start --root .everos-ollama
```

另开终端检查：

```bash
curl http://127.0.0.1:8000/health
```

### 终端 4：启动 MEMO Vault 后端

```bash
cd ~/EverOS
source .venv/bin/activate
export MEMO_VAULT_DATA_DIR="$PWD/.memo-vault"
export MEMO_VAULT_EVEROS_URL="http://127.0.0.1:8000"
uvicorn everos.entrypoints.memo_vault.app:app --host 127.0.0.1 --port 8765
```

检查 Vault 配置的 EverOS 地址：

```bash
curl http://127.0.0.1:8765/api/v1/system/health
```

响应中的 `data.everos_base_url` 应为 `http://127.0.0.1:8000`，`data.everos_status` 应为 `online`，`data.data_dir` 应指向本仓库的 `.memo-vault`。只看到 Vault 接口返回，并不表示 EverOS 已连通。

### 终端 5：启动前端

```bash
cd ~/EverOS/apps/memo-vault-ui
npm run dev
```

打开 `http://127.0.0.1:5173`，再重试抽取。Vite 会将 `/api/*` 转发给 `http://127.0.0.1:8765`；抽取请求由 Vault 再调用 EverOS，浏览器不直接调用 Ollama。

### 抽取失败时按链路检查

- Ollama：`ollama list` 和 `/api/tags` 是否包含上述两个模型；EverOS 的 `.everos-ollama/everos.toml` 是否指向同一 Ollama 地址。
- EverOS：`/health` 是否可达，终端 3 是否有模型连接、超时或结构化输出错误。
- Vault：`/api/v1/system/health` 是否显示正确的 EverOS 地址和 `online`；终端 4 的导入/抽取错误是否与同一批次对应。
- 前端：是否能访问 Vault，导入是否已归档。对失败批次使用“重试抽取”；抽取失败不会删除已归档原文件。查看新抽取结果后，再审核入库或导出 Pack。

## 8. 常用词语

- **候选记忆**：系统从导入对话中提取的草稿，需要用户审核；审核前不等于正式记忆。
- **MemCell**：从参与抽取的消息中划出的记忆单元；来源片段可记录实际输入的消息顺序和字符范围。
- **UMIF**：各来源转换后的统一中间数据格式，用于校验、归档和向 Vault 投影；不是正式记忆本身。
- **画像与偏好标识**：当前 UI 将 `kind=preference` 显示为“画像”，新数据写入 EverOS 的类型为 `profile`；阅读旧设计时要核对这一差异。
- **正式记忆**：已确认并写入 EverOS 的记忆内容，当前以 Markdown 记录作为权威来源。
- **证据**：指向原始导入文件或对话消息的信息，用于回看记忆从何而来。
- **项目空间**：MEMO Vault 中的范围边界；查询和导出时先选定项目，避免把不同项目的记忆混在一起。
- **Memory Pack**：把用户选定且符合外发策略的正式记忆整理成便于复制或下载的内容包。

