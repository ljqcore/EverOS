# 实现计划：偏好候选与 Harness 最终回复

> **给实现者：** 按任务顺序执行。实现完成后仅做静态检查和前端构建；当前任务约束不要求运行测试。

**目标：** 修正 Vault 的偏好候选语义，避免 Harness assistant 工具调用中间消息污染记忆，并将候选审核类型收敛为 Episode/偏好。

**设计：** 见 `docs/superpowers/specs/2026-10-23-preference-and-harness-final-answer-design.md`。原始来源完整留存，`memory_input` 只控制抽取入口。

**技术栈：** Python、EverAlgo/UMIF、SQLite、React/TypeScript。

### 任务 1：专用偏好抽取

- 修改 `src/everos/service/memo_vault_candidate_prompts.py`：添加中文偏好提示词，约束长期/可复用偏好，并要求精确用户原话证据。
- 修改 `src/everos/service/memo_vault_candidates.py`：新增偏好输出 schema 和直接抽取/JSON 校验；只读取当前 MemCell 的 user 消息；核验证据；以 user 消息作为候选来源；不再调用 ProfileExtractor 后按宽关键词过滤。
- 同文件优化跳过日志的错误诊断字段，不记录私人内容。

### 任务 2：标记并筛选 Harness 记忆输入

- 修改 `src/everos/entrypoints/memo_vault/deepseek_harness.py`：按 Harness turn 标记每轮最后一条有可见文本且不含工具调用的 assistant 消息；所有消息仍进入 UMIF。
- 修改 `src/everos/entrypoints/memo_vault/umif_projection.py`：将 UMIF `routing_hints.user_memory` 投影为 `ParsedMessage.memory_input`；generic 导入默认可抽取。
- 修改 `src/everos/entrypoints/memo_vault/import_contracts.py`：增加默认 `True` 的抽取资格字段，并升级 Harness parser version。
- 修改 `src/everos/entrypoints/memo_vault/storage.py` 与 `imports.py`：增加带默认值的 SQLite 列并持久化该字段。
- 修改 `src/everos/entrypoints/memo_vault/routes/imports.py`：候选抽取只读取可参与抽取的非重复消息；来源查看查询保持完整。
- 修改 `src/everos/entrypoints/memo_vault/imports.py`：同一 Harness 原始文件允许在 parser version 改变后重新归档一次，避免旧版本归档阻断新筛选规则。

### 任务 3：收敛候选审核 UI 类型

- 修改 `apps/memo-vault-ui/src/App.tsx`：移除事实、画像、决策、待办的筛选项及候选类型展示；atomic fact 编辑只允许偏好，Episode 类型固定展示。
- 保留 `apps/memo-vault-ui/src/api.ts` 与后端契约对历史类型的读取兼容。

### 任务 4：静态核对与构建

- 检查修改文件的语法、类型、SQL 插入列和值数量，以及关键来源查询仍读取完整消息。
- 运行 `git diff --check`、Python AST 解析和前端 `npm run build`；不运行测试套件。
- 汇报偏好 warning 的语义、证据策略、MemCell 切分和 Harness 过滤边界。
