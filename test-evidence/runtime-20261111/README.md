# 本地实例升级与真实 HTTP 验收（2026-11-11，Asia/Shanghai）

## 有证据：升级前事实与备份

代码基线 `485ef06`，`main` 工作区干净，领先 `origin/main` 9 个未推送提交。实际 `.env` 将数据目录设为仓库内 `data/`，绑定 `127.0.0.1:8000`，允许主机仅 `127.0.0.1,localhost`，DEBUG=true；Secret Key 已配置但不输出其值。初始 `./status.sh` 退出 1、报告已停止，8000 无监听，没有发现本项目外部生产访问。

实际数据库为 `data/db.sqlite3`（409600 字节），完整性检查 `ok`；用户、组织、成员、角色、审计、Feature、记录和 AI 配置均为 0，uploads 为空。待迁移不止 E7：`ai.0006_toolcallproposal`、`organizations.0006_role_data_scope`、`extensions.0001_initial`、`extensions.0002_controlled_catalog_review` 四项尚未应用。

- 先执行已有 `./backup.sh`，退出 0，使用 SQLite backup API 得到一致性 DB 备份；完整性 `ok`。命令见 `backup-command.txt`。
- 数据库备份：`/Users/dundundebaba/sync/code/open/bixi-seed/data/backups/db-20261111-163853.sqlite3`，SHA-256 `bfc6ec5334a38d1ac0d9ab861686b2922b5fcc28a9dde56a801b2358a42cf034`。
- 私有补充归档保存 DB 备份、data 下日志/上传/其他文件与 `.env`，排除 backups 递归：`data/backups/maintenance-20261111-local-upgrade/pre-upgrade-data-and-env.tar.gz`，SHA-256 `afce9b15611fba1971bf4f54b3164092649a11ea2190430ffb6dfd8af27d9cc0`。归档和 DB 备份权限 600，私有目录 700；`.env` 内容没有进入 Git 或证据，证据仅记录其存在、SHA 和恢复路径。
- 备份元数据见 `backup-metadata.json`。结束时再次计算，原备份、归档和 `.env` 的 SHA 均未改变，见 `cleanup.json`。

## 有证据：恢复演练与实际迁移

先以私有 `recovery-check/` 作为独立 `BIXI_DATA_DIR`，调用现有 `restore_data --input` 恢复备份；恢复副本的 DB SHA 与原备份一致，然后应用四项迁移。成功后才升级实际本地库。

| 命令/行为 | 退出码 | 证据 |
| --- | ---: | --- |
| `.venv/bin/python manage.py restore_data --input <上述DB备份>`（独立 recovery-check 数据目录） | 0 | `recovery-restore.txt` |
| `.venv/bin/python manage.py migrate --noinput`（独立副本） | 0 | `recovery-migrate.txt` |
| 对备份每张原表逐原始行、原始列与升级后副本比较 | 0 | `recovery-preservation.json`；原行全部保留，完整性 ok |
| `.venv/bin/python manage.py migrate --noinput`（实际 `.env` 数据目录） | 0 | `actual-migrate.txt`；四项均 OK |
| 对备份原行与升级后实际库逐行比较 | 0 | `actual-preservation.json`；原行全部保留，完整性 ok |
| `.venv/bin/python manage.py showmigrations --plan` | 0 | `actual-showmigrations.txt`；四项均 `[X]` |

恢复路径保留在上述私有目录；实际本地库未执行 reset、删除原始数据或回退。升级前数据与配置的完整备份仍可恢复。原有行保持证明包括 Django 自身表，迁移新增的 content type、permission 和 migration 记录另行保留。

## 有证据：真实启动、登录和 E6/E7 HTTP 行为

`http-smoke.py` 使用真实 `127.0.0.1:8000` HTTP、Cookie Session 和 CSRF；没有使用 Django TestClient、mock HTTP 或 mock 模型。临时密码只存在私有 600 文件，未进入参数、日志或 Git。临时组织和账户元数据见 `fixture-metadata.json`。

命令：`.venv/bin/python test-evidence/runtime-20261111/http-smoke.py --credentials <私有临时凭据文件>`，最终退出 **0**，**53 项 HTTP 检查均满足预期**，见 `http-results.json`。

- 启动与停止：已有 `./start.sh` 退出 0；运行中两次 `./status.sh` 均退出 0、health 正常；`./stop.sh` 退出 0；停止后 status 退出 1 并明确“已停止”，这是预期状态。证据：`start-command.txt`、`running-status.txt`、`final-running-status.txt`、`stop-command.txt`、`stopped-status.txt`。
- 页面 `/`、实际构建 JS/CSS、health、CSRF、两个临时账户登录及 `/auth/me/` 均 200。
- E7：目录读取、创建、validate、当前 hash+显式确认收录均通过；缺少确认、旧 hash、重复收录返回 409；其他组织不能 validate/enable，返回 404。`enabled` 仅表示目录收录，`execution_status=not_loaded_or_executed`；包含 `raise RuntimeError(...)` 的草稿文本未被执行。
- E6：固定 create/update/delete 的提案、字段/权限/数据差异、显式确认、三种补偿撤销和审计均通过；未确认时记录数不变，跨组织详情/确认/撤销均 404，重复确认 400，后续数据写入后撤销 409 且后续值保留。内部 undo 不返回浏览器。
- 审计：HTTP 查询确认 proposed/confirmed/reverted、record 写入/补偿、E7 created/validated/enabled、确认拒绝、撤销失败和模型配置失败事件；`http-results.json` 只保存动作计数及状态，不保存密码、Cookie、请求正文或响应正文。
- **真实模型 BLOCKED / 用户指示暂缓**：实际本地 `LLMProviderConfig` 数量为 0；真实 `/api/ai/tool-plan/` 返回 422，未调用供应商、未花费模型费用。这是无配置行为证据，不是模型调用通过。用户随后要求模型配置“先等等吧”，因此本轮不再寻找凭据或补配账号；待用户恢复该项后，再使用现有 Provider 配置与归档真实提案结果。

首轮结果保留在 `first-run-*`：更新工具收到 400，因为验收脚本将普通记录 API 返回的字符串编号直接传入要求整数的工具参数。只修复验收脚本的 `int(record_id)`，未修改产品参数契约；先清理本次临时组织中的首轮对象再重跑，见 `first-run-fixture-reset.json`。未用 skip 掩盖失败。

## 有证据：清理、交接和门禁

验证完 logout、停止服务，再仅删除本次创建的 2 个临时账户、2 个临时组织及其关联验收对象和新建权限种子；未删除任何原始行。临时凭据文件已删除。用户、组织、成员、角色、权限、审计、Feature、记录、工具提案、扩展草稿、模型配置和 Session 均恢复为 0，完整性 `ok`，实例恢复原始停止状态，见 `cleanup.json`、`after-cleanup-status.txt`。

本次无产品代码修改；变更只包含本目录复现脚本/证据和交接文档。提交前再次运行既有五项门禁：pytest **97 passed**，迁移漂移检查、Django check、vue-tsc、Vite build 均退出 **0**，无 skipped/deselected，构建仅有 chunk size 提示。命令、退出码与结果见 `commands.json`、`pytest.txt`、`migrations-check.txt`、`django-check.txt`、`vue-tsc.txt`、`vite-build.txt`。

## 文档声明与推断边界

- 实际本地迁移和真实 HTTP 的阻塞已解除；真实模型和无环境的 Windows 验收继续阻塞。HTTP 页面/资源通过不等于真实浏览器交互矩阵通过。
- 首次跨执行工具调用时，start 曾返回健康后在下一次工具调用发现进程消失，日志没有应用退出异常；在同一存活验证进程内，完整 start→53 项 HTTP→status→stop 均通过。执行工具清理后代进程是**推断**，没有据此修改启动脚本或宣称产品存在退出缺陷。
- E8 SDK、Provider、模板生态和独立运行时：建议，待确认，当前不实施；E7 收录不提供执行/隔离安全证明。核心继续单机运行，不共享跨项目运行时代码。
- 本项目交接已更新；OPEN 索引仅建议补记本次本地升级和真实 HTTP 证据，本任务未修改 OPEN。没有处理暂停项目，没有推送 GitHub。
