# 偏好候选与 DeepSeek 最终回复筛选设计

## 背景

候选抽取目前借用 `ProfileExtractor` 的画像结果，再按宽泛关键词筛选“偏好”。它会把“资料和偏好”一类的画像表述误认成偏好；LLM 请求失败时只记录 warning 并跳过当前 MemCell。DeepSeek Harness 导入会保存可见的 user/assistant 消息，但 assistant 中带工具调用的中间消息也进入 MemCell，容易混入情节归纳。

## 目标

1. 只把用户明确表达、对未来交互或推荐有持续作用的偏好作为偏好候选。
2. 每条偏好必须带有可在同一 MemCell 的 user 原文中逐字核对的证据；证据关联只包含这些 user 消息。
3. DeepSeek 原始导出完整归档；UMIF/归一化会话保留所有已解析的可见 user/assistant 消息及独立工具记录。只有用户消息和每个 Harness turn 最后一条含可见文本且不含工具调用的 assistant 消息参与记忆抽取。
4. 候选审核界面只展示 Episode 和偏好两类候选标签/筛选项；API 和历史数据兼容层暂时保留。

## 不在范围内

- 不删除或改写 Harness 原始归档文件（含其原始推理块）、工具调用/结果记录或已解析可见消息。规范化消息继续只从 `text` block 取内容，不将 `reasoning` block 转为会话文本。
- 不改变 EverOS 正常 Episode/Profile 提示词和生产记忆管线。
- 不改候选审核以外的记忆库、Memory Pack 或导出类型。
- 不将偏好失败扩大为整批导入失败；保留当前 MemCell 级部分失败行为。

## 设计

### 偏好抽取

- 新增 Vault 专用 `PREFERENCE_PROMPT_ZH` 与结构模型，直接从 MemCell 中的 user 消息抽取，不再将通用画像列表筛成偏好。
- 只抽取稳定的交互、表达或推荐偏好；排除个人资料、一次性需求、计划、决定、待办、助手观点及提示词复述。
- 每项输出 `content` 和 `evidence`。提示词要求 `evidence` 是用户原话的连续摘录；代码再做逐字/空白归一化核验，并用窄范围表达信号过滤明显非偏好结果。打开证据时优先用这段原话做词项定位。
- 无匹配偏好或证据不匹配时不生成候选。候选来源消息和 MemCell 片段只引用包含该原话的 user 消息。
- LLMError 仍只跳过当前 MemCell；日志增加安全的错误码/原因字段（如库提供），不记录提示词、对话或响应正文。

### DeepSeek Harness 输入筛选

- 解析可见文本时继续排除 `reasoning` 和 `tool-call` block 的内容。
- 对每个 turn，只有最后一条 assistant/message 本身包含可见文本且没有 `tool-call` block 时，才把它作为可供记忆抽取的最终回复。若 turn 缺失，则按最近一条 user 消息分组，再应用相同规则。
- Harness 的所有 user/assistant 可见消息继续转换成 UMIF `Message` 并保存；通过 `routing_hints.user_memory` 标记是否参与记忆抽取。
- Vault 投影和 `normalized_messages.memory_input` 保存此资格。通用 Markdown/文本导入默认为可参与抽取；现有读取来源、证据、完整会话的查询不加筛选。
- 抽取入口只读取 `memory_input=1` 的非重复消息。
- 增加 Harness adapter parser version，便于诊断新旧导入行为。升级后同一个原始 Harness 文件可按新 parser version 再归档一次以重新抽取；旧批次及其候选保留，不回写或自动删除。

### 候选审核类型

- 类型筛选和卡片类型标记只展示 `episode` 与 `preference`。
- `atomic_fact` 的可编辑选项只允许偏好；Episode 显示为固定类型。
- 后端契约和旧候选仍兼容已有类型，不做数据迁移、不改变记忆库显示。

## MemCell 切分说明

输入先按约 2,200 tokens 和最多 20 条消息做操作性分块；单条过长消息按约 1,400 tokens 切成保留字符偏移的片段。随后由 EverAlgo boundary detector 根据消息、时间和话题边界继续划分 MemCell。它不是按会话数量均分。最终 EpisodeExtractor 对每个 MemCell 调用一次。

## 验收标准

- “用户明确说过的资料和偏好”这类画像说明不能成为偏好候选。
- 有偏好候选时，来源摘录可以在其关联 user 原文中核验；assistant 的复述不算用户证据。
- DeepSeek UMIF/原始归档仍包含所有可见消息；候选抽取忽略 assistant 工具调用中间消息，仅纳入每轮最终可见回复。
- 候选审核类型筛选和卡片不再出现事实、画像、决策、待办标签。
- 数据库既有数据可通过默认列值读取；通用导入行为保持原样。
