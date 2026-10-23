# MEMO Vault 本地候选抽取

## 导入前的 UMIF 层

DeepSeek Harness v4 可上传 `session.v4.jsonl` 或包含这一文件的 ZIP；通用 JSON/Markdown/TXT 导入也先转换为 UMIF。流程为“原始文件 → 来源适配器 → UMIF 校验 → Vault 标准化消息与工具轨迹 → 候选抽取”。UMIF 包保存在批次的证据目录 `umif/`，与原始文件同时归档；SQLite 的 `umif_record_map` 记录源记录 ID、内容哈希和投影目标 ID。预览仅返回 UMIF 包 ID、记录数与安全的校验摘要，不会提交正式记忆。

当前 Harness 适配器生成 Principal、Session、Message、Tool Call、Tool Result。可见 user/assistant 文本进入候选流程；system/developer 消息、工具轨迹和其他未处理事件不会伪装成用户聊天。工具参数原文保存在 UMIF 的 `arguments_text`，即使它不是合法 JSON；未处理事件按类型计数。`assets.jsonl`、`documents.jsonl`、`memories.jsonl` 和 Claude 适配器仍属后续工作；本次 UMIF 核心已为这些独立记录类型留出包结构。

`GET /api/v1/imports/{batch_id}/status` 返回归档/抽取状态、`error_stage`、安全错误码和 UMIF 包相对路径。候选抽取失败后原始文件与 UMIF 包仍在，可用相同批次重试。`error_stage` 可定位到健康检查、EverOS 返回合同、模型调用/结构化输出或候选落库；这不能替代模型服务本身的日志。UMIF 不会自动修复 Ollama 的结构化输出问题。正式记忆和 Memory Pack 仍只接收人工审核后的候选。

MEMO Vault 的“立即抽取”使用 EverOS 的用户聊天提取能力，但不调用普通 `/api/v2/memory/add` 与 `/flush` 组合。那条常规管线会触发用户记忆与 Agent 记忆策略，并写入 EverOS 记忆存储；导入审核流程不能把未审核结果写入正式记忆。

Vault 按会话调用 EverOS 的 `POST /api/v2/memo-vault/candidates/extract`。EverOS 对 user 和 assistant 消息运行会话边界识别与 Episode 抽取，并对包含 user 发言的分段运行默认 `ProfileExtractor`；只把 `explicit_info` 中明确属于偏好的条目转为偏好候选，忽略 `implicit_traits`，不生成事实候选。没有明确偏好时只返回情节候选；偏好抽取失败也不会丢弃已生成的情节。该专用路径不写入 MemCell、Episode、AtomicFact、Profile 或 AgentCase 存储，也不触发 OME 策略。没有抽取结果时返回真实的空候选列表。

这条候选路径会使用 EverOS 当前 `[llm]` 配置的模型进行边界、Episode 与 Profile 抽取；本地 Ollama 示例配置对应 `qwen2.5:3b`。Episode 使用 EverOS 默认提示语。Profile 使用 EverOS 默认提示语，但本流程只保留明确表达的偏好；画像中的隐式特征不会成为 Vault 候选。偏好候选以 EverOS 的 AtomicFact 存储类型发布，Vault 保留“偏好”分类。

Episode 和 Profile 调用不传入提示语覆盖，因此由 EverOS `EpisodeExtractor` 和 `ProfileExtractor` 使用各自的默认提示语。输入消息保留 `user` / `assistant` 显式角色，并继续按项目约定将两种聊天角色都归属到 `user_id`；Profile 抽取只在分段内存在 user 发言时运行。抽取输出仍须人工审核，默认提示语和结构化输出都不能保证事实正确。已经抽取并保存在 Vault 的旧候选不会因抽取逻辑更新而自动改写。

Vault 收到结果后，在一个 SQLite 事务中写入 `candidates` 和 `candidate_evidence`，再把批次状态置为已抽取。每条候选关联本会话实际参与抽取的标准化消息；原始文件及消息不会因抽取失败而变更。候选尚未审核，不属于 EverOS 正式记忆。

消息身份规则：user 和 assistant 聊天消息在 EverOS 算法输入中都使用稳定的 `user_id`；`agent_id` 是请求合同中的预留字段，本阶段不用于聊天记忆归属。tool、system、developer 等非聊天角色会保留在 Vault 归档中，但不会被转换成 assistant 或送入本地聊天抽取。结构化工具轨迹及其 Agent 经验抽取后续单独实现。

## 候选审核与正式记忆发布

Vault 的 `GET /api/v1/candidates` 返回候选、导入批次信息和来源消息索引，不在列表响应中重复传送整条原文。用户可以按状态、候选类型、来源（`import` / 预留的 `agent`）和证据状态筛选；四个筛选控件位于同一行。页面左侧卡片只显示短预览，选中后右侧显示完整候选内容、审核字段和来源索引。点击“打开原对话”会调用 `GET /api/v1/candidates/{candidate_id}/source/{message_id}`，先校验该消息属于候选及归档批次，再按会话顺序返回归档的标准化消息，在滚动弹窗中展示。右上角的“人工新增”当前仅为禁用的后续入口。

审核时可选择已有命名空间、长期/30 天/90 天有效期，以及导出时确认/允许外发/不可外发。候选确认后，这些值保存在 Vault 的 `candidates` 和 `memories` 治理元数据中；30/90 天到期时间由服务端计算为 UTC 时间。目前记忆检索和导出治理尚未实现，因此到期和外发策略尚未在下游执行，不能把字段保存视为完整的策略执行。

确认请求带候选 revision；Vault 将候选置为 `publishing` 后，把人工审核后的确切文本发到 EverOS，不再运行 LLM 抽取。AtomicFact 写入事实日志，Episode 写入情节日志，Profile 条目合并进对应 `app_id/project_id/users/<user_id>/user.md`。候选只有收到 EverOS 的正式记忆 ID 后才会进入 `confirmed` 状态；发布失败会恢复为待审核。EverOS 以候选 ID 作为幂等键，重复请求返回同一条记忆回执。Profile 是聚合文件，单条候选回执 ID 标识本次画像贡献，而非另一份画像文件。拒绝只更新 Vault 审核状态，不写 EverOS。

本阶段将偏好、事实、决策和待办都存为 EverOS 当前已有的 user AtomicFact 记录；Vault 保留其 UI 分类，EverOS 记忆底座暂不新增四套数据结构。人工新增后续仍进入相同审核流程，需要支持记忆类型、内容、证据关联或“人工撰写”标记及用户确认，本轮不提供新增入口。

Vault 的 `GET /api/v1/system/health` 每次对 EverOS `/health` 做最多 3 秒的轻量探测。前端每 15 秒刷新 EverOS 在线状态；该状态独立于 Vault API 的可用状态。

## API

`POST /api/v2/memo-vault/candidates/extract`

请求包含 `batch_id`、`session_id`、`app_id`、`project_id`、稳定的 `user_id`、预留的 `agent_id`，以及一个会话中的 user/assistant 消息。成功响应包含真实候选数、情节与可能为空的偏好候选，以及来源消息 ID。Vault 客户端不得以 `/memory/flush` 作为导入候选抽取的替代接口。

`POST /api/v2/memo-vault/candidates/{candidate_id}/publish` 接收经过用户审核的确切记忆文本、底层类型与必要元数据，并按候选 ID 幂等写入对应 EverOS user 存储；该接口不调用模型。旧请求默认 `atomic_fact`。

## 候选类型与证据

当前导入候选流程使用 EverOS `EpisodeExtractor` 生成 `episode` 候选，使用默认 `ProfileExtractor` 输出中的明确偏好生成 `preference` 候选。独立 `AtomicFactExtractor` 与事实候选生成实现仍保留在代码中，但本导入流程不调用它。偏好、决策、待办在 EverOS 中以 AtomicFact 底层类型发布；Vault 保存来源消息 ID 作为候选关联，并保存原消息全文作为可追溯上下文，暂不推断候选对应的精确字符区间。工具轨迹抽取留待后续实现。

导入候选的证据状态按原始文件是否仍存在于本批次的归档目录判定：文件存在即显示“有归档来源”，不再用候选文字与消息文本的词面匹配来否定来源。候选详情中的消息链接仍需通过批次、引用和归档检查，供用户定位具体对话。该状态只表示原文件可追溯，不代表候选内容已通过语义核验，仍需人工核对；原文件缺失时不能确认入库。非导入来源仍沿用原有消息来源与明显英文专名检查。现有候选不会因规则更新而自动改写或删除。
