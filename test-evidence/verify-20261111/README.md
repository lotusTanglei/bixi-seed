# Bixi Seed 收敛维护执行记录（2026-11-11，Asia/Shanghai）

## 有证据：基线、提交与修改

开工执行 `git status --short --branch`、`git log -1 --oneline`、`git log --oneline origin/main..main`：`main@3df6794`，工作区干净，领先 `origin/main` 4 个提交。未 reset、rebase 或覆盖已有提交。

| 提交 | 本轮修改与文件 | 验收记录 |
| --- | --- | --- |
| `d3ab624` | 初步文档对齐；其“已完成”表述经后续复核发现过强，以下实际修复与证据替代该结论 | 历史 62 项测试不能证明完整 E6/E7 |
| `1b80f0a` | E5：`organizations/services.py`、`views.py`、`tests/test_role_extensions.py`，修复个人数据范围角色通过创建、修改、复制、批量分配扩权；补跨组织和原子拒绝验证 | [E5-review.md](E5-review.md) |
| `913569f` | E6：`ai/providers.py`、`views.py`、`urls.py`、工具测试、`organizations/services.py`、`frontend/src/views/AiView.vue`；固定三工具模型提案、风险/类型、字段权限数据预览、确认、补偿撤销、失败回滚与审计、当前权限及组织隔离 | [E6-review.md](E6-review.md) |
| `d4c9ced` | E7：`extensions/` 模型、迁移、服务、API、负向及迁移测试；前端目录/预览/确认；显式 `packaging` 依赖；不加载执行草稿 | [E7 执行记录](../maintenance-20261111/e7/README.md) |

本次最终交接提交只修改 README、开发计划、路线范围声明与执行记录；代码验证基线为 `d4c9ced`。当前最终提交由 `git log -1 --oneline` 复核，OPEN 总索引记录最终 hash。

## 有证据：按顺序完成的门禁

E5 五项门禁通过后才修改 E6；E6 五项门禁通过后才实施 E7。每个切片的命令、退出码、证据和覆盖范围见上述记录。最终 E7 使用当前代码完整重跑，未复用更早计数冒充当前证据。

| 切片 | focused / 全套 pytest | 迁移漂移 / Django check / vue-tsc / Vite build | 证据 |
| --- | --- | --- | --- |
| E5 | 20 / 65 passed，退出 0 | 四项均退出 0 | `E5-review.md` |
| E6 | 24 / 85 passed，退出 0 | 四项均退出 0 | `e6-focused.txt`、`e6-pytest.txt`、`e6-migrations.txt`、`e6-django-check.txt`、`e6-vue-tsc.txt`、`e6-vite-build.txt` |
| E7 最终 | 14 / 97 passed，退出 0 | 四项均退出 0 | `../maintenance-20261111/e7/commands-final.json` 与 `*-final.log` |

最终命令为 `.venv/bin/python -m pytest -q`、`.venv/bin/python manage.py makemigrations --check --dry-run`、`.venv/bin/python manage.py check`、`./node_modules/.bin/vue-tsc --noEmit`（frontend）、`./node_modules/.bin/vite build`（frontend）。全部退出 0；pytest 无 skipped/deselected，构建仅有 chunk 大小提示。未使用 skip 参数。最终交接只改文档，复用同一代码的上述通过结果；`git diff --check` 退出 0。

另有 E6 独立撤权/失效成员重验 2 项退出 0、E7 隔离迁移保留测试 1 项退出 0。E6 修复前一次临时测试失败及原日志未保留的限制在 `E6-review.md` 明确列出，修复后材料不冒充原始失败材料。

## 有证据：实际限制与阻塞

- **E6 真实模型调用 BLOCKED**：本地 `LLMProviderConfig` 数量为 0，见 `e6-model-availability.txt`。目前模型规划协议和受控执行只有 mock/本地回归证据；解除条件是配置现有 OpenAI-compatible 账号和模型后归档真实调用。未新增 Provider。
- **E7 收录不执行**：`enabled` 只表示用户确认收录到当前组织目录；草稿不写源码、不加载、不执行，不证明进程隔离，也不执行草稿自带测试。单元测试与构建是项目门禁，未硬编码进草稿静态报告。
- **E7 实例未升级**：迁移证明只使用隔离测试 DB，`0001 → 0002 → 0001 → 0002` 后源文件与原始字段仍保留；旧 PASS 失效。schema 回退不恢复旧审核。实际本地实例未执行迁移，升级步骤见 [E7 文档](../../docs/E7_CONTROLLED_EXTENSIONS.md)。
- **前端证据边界**：类型检查与构建通过，未宣称真实浏览器端到端矩阵通过。

## 文档声明：暂缓、未来方向与 OPEN 索引

- Windows 无环境继续暂缓，未反复尝试，未修改 `.github/workflows/acceptance.yml` 增加 Windows job。
- E8 SDK、Provider、模板生态与独立扩展运行时：**建议，待确认，当前不实施**。核心继续保持单机可运行。
- 本轮只推进 E5 剩余 → E6 → E7，没有处理 ActBox、WebDeck、OpsPilot，没有新增计划外业务功能。
- 三项目只统一证据字段：提交、文件、命令、退出码、通过/失败/跳过、证据、阻塞及解除条件、未来建议；不共享运行时代码。
- OPEN 索引应绑定最终维护提交、本记录及各切片证据，并保留真实模型、实例迁移、Windows 和运行时隔离边界；未推送 GitHub，推送前须用户确认。

## 推断

本地门禁可支持本轮三个切片的维护结论，不推出真实模型表现、任意草稿运行安全、实际实例升级或 Windows 验收通过，也不代表整个第二阶段路线图完成。
