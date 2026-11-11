# E6 验收映射复核（2026-11-11，Asia/Shanghai）

代码基线：E5 修复提交 `1b80f0a`；E5 五项门禁通过后才修改 E6，E6 五项门禁通过后才通知进入 E7。本切片不修改 extensions，不启动独立运行时，不增加任意工具或 Provider。

## 有证据：验收映射

| 用户子项 | 当前实现证据 | 测试证据 |
| --- | --- | --- |
| AI 工具调用 | `ai/providers.py:52`，复用当前组织模型配置，发送一个 Chat Completions 请求，`required` 工具选择、关闭并行，只接受一个 function tool call。`ai/views.py:84` 固定三个别名，`:579` 模型规划入口，只发送选定 Feature 的编号、名称、字段上下文；结果经既有工具提案校验，绝不自动执行 | `ai/tests/test_tool_planning.py:39`、`:56`、`:141`、`:151`；mock 证明固定别名、无记录内容、零/多个调用和错误 JSON 拒绝；不等于真实供应商验收 |
| 工具参数和风险等级 | `ai/views.py:61` 固定 create/update/delete，明确类型、必填、UUID、正整数、额外参数拒绝；`:425` 服务端实际校验，create=medium、update/delete=high | `ai/tests/test_tool_calls.py:45`、`:52` |
| 方案预览 | `ai/views.py:464` 校验当前组织、权限、动作开关及数据范围后生成提案；`:483` 保存字段、权限、manifest 快照和数据版本 | `ai/tests/test_tool_calls.py:66`、`:79`；`ai/tests/test_tool_planning.py:94`、`:110` 证明模型调用期间失去操作/AI 权限或成员关系即拒绝 |
| 字段/权限/数据差异 | `ai/views.py:523` 将字段定义和权限/数据范围的 before/after 与数据 added/changed/removed 分开呈现。记录工具不修改 Feature 字段或权限定义，因此这两项 before/after 相同；`:687` 确认时重新计算并比较全部预览和差异，过期即拒绝 | `ai/tests/test_tool_calls.py:79`、`:89`、`:152` |
| 用户确认 | `ai/views.py:687` 要求 `confirm is True`，只允许作者在当前组织确认一次；`frontend/src/views/AiView.vue:331` 显示风险和确认框，`:633` 为固定工具表单、自然语言规划入口、字段/权限/数据预览 | `ai/tests/test_tool_calls.py:102`；前端类型检查和构建通过，未将其声明为浏览器端到端验收 |
| 撤销与事务回滚 | `ai/views.py:725` 对已确认 create/update/delete 作补偿撤销，重验当前逆向操作权限、动作开关、manifest、own 范围、记录执行后快照；数据有后续变化则拒绝覆盖。`:770` 显式确认撤销；执行/补偿都使用内层 savepoint，失败后在外层写失败审计 | `ai/tests/test_tool_calls.py:111`、`:137`、`:152`、`:182`、`:226`，覆盖三种补偿、并发版本拒绝，以及 record 成功审计或最终 tool 成功审计抛错后的数据/状态/成功审计原子回滚 |
| 完整审计与隔离 | `ai/views.py:446` 统一记录 proposed/planned/confirmed/revoked/reverted/拒绝/失败事件，记录工具、风险、对象、操作者、组织和结果，排除提示词与数据字段值；`:649` 详情读取重验当前权限和 own 范围，API 不返回内部 undo 快照。`organizations/services.py:107` 不复用已失效成员缓存 | `ai/tests/test_tool_calls.py:182`、`:200`、`:226`；跨组织/降权拒绝；独立隔离数据库复核脚本与输出 `e6-independent-review.py`、`e6-independent-review.txt` |

前端新增工具状态在 `frontend/src/views/AiView.vue:271` 监听组织切换清空，并使用请求代数与组织编号丢弃异步迟到响应；普通 `ai.use` 用户可选择工具页签，无需 `feature.manage`。此行为经类型检查与构建，尚无浏览器自动化证据。

## 有证据：命令与原始输出

| 命令 | 退出码 | 结果/证据 |
| --- | ---: | --- |
| `.venv/bin/pytest -q ai/tests/test_tool_calls.py ai/tests/test_tool_planning.py ai/tests/test_feature_planning.py` | 0 | 24 passed；`e6-focused.txt` |
| `.venv/bin/pytest -q` | 0 | 85 passed；`e6-pytest.txt` |
| `.venv/bin/python manage.py makemigrations --check --dry-run` | 0 | No changes detected；`e6-migrations.txt` |
| `.venv/bin/python manage.py check` | 0 | No issues；`e6-django-check.txt` |
| `npm exec vue-tsc -- --noEmit`（frontend） | 0 | `e6-vue-tsc.txt` |
| `npm run build`（frontend） | 0 | `e6-vite-build.txt`；仅 chunk size 提示 |
| `PYTHONPATH=. .venv/bin/python test-evidence/verify-20261111/e6-independent-review.py` | 0 | 独立隔离数据库 2 tests：模型等待期间撤销 ai.use 或成员关系均 403，原记录不变；`e6-independent-review.txt` |
| `.venv/bin/python -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); import django; django.setup(); from ai.models import LLMProviderConfig; print("configuration_count=" + str(LLMProviderConfig.objects.count()))'` | 0 | `configuration_count=0`；`e6-model-availability.txt`；只查数量，不输出密钥 |

跳过项：无门禁因失败而跳过；Windows 验收按用户决定暂缓，未修改 acceptance 工作流。

**文档声明（独立复审代理的执行报告）**：修复前的临时 stdin 测试曾退出 1（1 项失败）：模型调用期间撤销 `ai.use` 后仍返回 201 并含预览。该失败只保留在会话工具记录（chunk `be84c7`），原脚本和原输出文件未保留，不能冒充完整归档证据。修复后上述项目回归及独立脚本重验退出 0；本目录 `e6-independent-review.py` / `.txt` 仅是修复后的材料，不是原始失败材料。

## 实际限制、文档声明与推断

- **BLOCKED（有证据）**：当前本地没有任何模型配置，真实供应商 `tool_calls` 兼容性和真实模型提案质量未验收。解除条件：在目标组织配置可用的现有 OpenAI-compatible 模型与账号，使用同一固定工具入口做真实调用并归档结果。mock 结果仅证明本地控制流与协议解析，不冒充真实调用。
- **有证据**：工具只有三种现有 Feature 记录操作；生成的方案不会直接执行。记录工具的字段/权限差异是“相同快照”，不代表新增字段或权限编辑工具。
- **有证据**：已执行撤销是安全的补偿操作，不抹除审计；后续数据变更、权限/manifest 变化时拒绝撤销。没有 undo 快照的历史 confirmed 提案不能补偿撤销。
- **文档声明**：E8 SDK、Provider、模板生态和独立进程运行时是“建议，待确认，当前不实施”；核心继续单机运行。三个项目只统一证据字段，不共享运行时代码。
- **推断**：当前自动化测试足以验证本切片受控执行边界；不推断真实模型表现、Windows 行为或完整 E7 验收状态。
