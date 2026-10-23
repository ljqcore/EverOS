# MemCell 来源证据与中文候选实施计划

**目标：** 按已批准的设计将候选实际输入 MemCell、关键原文位置与中文 Episode/Profile 输出接入 MEMO Vault。

**状态：** 已实施；Python 语法解析和前端生产构建通过。未运行测试。

**范围：** 只改候选审核“打开原对话”弹窗和记忆库详情“来源证据”区域；不改其他页面布局与交互。

**实现顺序：**

1. 在 EverOS 候选抽取时记录消息字符跨度和来源哈希，并接入现有中文 Episode/Profile 提示语。
2. 在 Vault 持久化并校验来源片段与归档文件哈希；显式区分片段哈希异常和旧候选回退；空摘录不再阻止打开来源。
3. 建立候选与记忆库共用的来源片段和关键位置读取逻辑。
4. 修改指定的两个 UI 区域，支持片段展示、高亮和完整会话定位。
5. 检查变更差异及格式，并运行 Python AST 语法解析与前端生产构建；未运行测试。

**涉及文件：**

- `src/everos/service/memo_vault_candidates.py`：精确来源跨度和中文提示语。
- `src/everos/entrypoints/memo_vault/storage.py`：候选来源片段持久化列和旧库迁移。
- `src/everos/entrypoints/memo_vault/evidence.py`：共享片段读取、来源校验、关键位置选择。
- `src/everos/entrypoints/memo_vault/routes/imports.py`、`routes/candidates.py`：保存来源片段并提供来源 API。
- `src/everos/entrypoints/memo_vault/library.py`：记忆详情使用共享片段读取。
- `apps/memo-vault-ui/src/api.ts`、`App.tsx`、`styles.css`：只更新两个约定区域。

**全局约束：** 关键位置只能返回归档原文跨度；没有匹配时仍可查看完整 MemCell；旧数据须明确标记为关联消息精度；人工审核仍是内容准确性的最终依据。

**实现说明：** 当前 MEMO Vault 未接入本地语义检索服务，因此关键位置使用词面匹配；匹配不足时保留并展示完整 MemCell。归档文件需同时位于安全归档目录内且 SHA-256 与导入批次记录一致，候选才可作为有效来源。
