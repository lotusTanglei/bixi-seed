# Bixi Seed E7 执行记录

日期：2026-11-11，Asia/Shanghai。**有证据**：本切片在 E6 提交 `913569f` 后实施；验证时的 E7 文件 SHA-256 清单见 `source-sha256.txt`，本次提交号由 `git log -1 -- extensions/` 和项目最终交接记录绑定。

## 修改范围

- **有证据**：`extensions/models.py`、`migrations/0002_controlled_catalog_review.py` 增加权限清单、内容哈希、确认人/时间和目录收录状态，使旧静态校验结果失效。
- **有证据**：`extensions/services.py` 实施路径/UTF-8/大小、Python AST、JSON、已安装依赖与版本约束检查；`requirements.txt` 显式声明 `packaging>=24,<27`。
- **有证据**：`extensions/views.py`、`urls.py` 实施当前组织范围、权限清单授权检查、内容哈希绑定、字面布尔确认、启用前重验和成功/拒绝审计。
- **有证据**：`frontend/src/views/ExtensionsView.vue`、`router/index.ts`、`App.vue` 增加受 `feature.manage` 保护的目录、文件/依赖/权限预览和确认收录；组织切换清空旧视图，迟到异步响应按组织和操作代次丢弃。
- **有证据**：`extensions/tests/test_drafts.py`、`test_migrations.py` 提供 API 负向检查与隔离迁移证明；边界文档在 `docs/E7_CONTROLLED_EXTENSIONS.md`。

## 最终验证

所有命令的完整参数、工作目录、开始时间和退出码见 `commands-final.json`。未使用跳过参数，最终全套 pytest 无 skipped/deselected。

| 命令 | 退出码 | 结果 | 原始日志 |
| --- | ---: | --- | --- |
| `.venv/bin/python -m pytest -q extensions/tests` | 0 | 14 passed | `focused-final.log` |
| `.venv/bin/python -m pytest -q` | 0 | 97 passed | `pytest-final.log` |
| `.venv/bin/python manage.py makemigrations --check --dry-run` | 0 | No changes detected | `migrations-final.log` |
| `.venv/bin/python manage.py check` | 0 | 0 issues | `django-check-final.log` |
| `./node_modules/.bin/vue-tsc --noEmit`（frontend） | 0 | 类型检查通过 | `vue-tsc-final.log` |
| `./node_modules/.bin/vite build`（frontend） | 0 | 构建通过；保留 chunk 大小告警 | `vite-build-final.log` |
| `.venv/bin/python -m pytest -q extensions/tests/test_migrations.py` | 0 | 1 passed，隔离测试 DB | `migration-preservation.log` |

**有证据**：前一轮 focused 13 passed、全套 96 passed，其余四门禁均为 0，日志保留在无 `-final` 的文件中。随后补充组织切换迟到响应保护、非法 UTF-8 key 防护和迁移保留测试后执行上述最终轮；早期通过不替代最终证据。独立代码复核用于补充检查，未冒充项目 test suite 结果。

## 迁移与执行边界

- **有证据**：隔离测试执行 extensions `0001 → 0002 → 0001 → 0002`，验证 files、dependencies、key/name/description、组织、创建者和创建时间保持一致；旧 PASS 失效、新字段采用安全默认；再升级后可重新校验并绑定当前 hash。测试结束恢复叶迁移。
- **文档声明**：schema 回退会移除新增字段，不恢复旧审核或确认结果；草稿源内容保留。部署前停止实例并备份，再使用项目虚拟环境执行 `python manage.py migrate`。
- **有证据（本切片当时）**：未对用户实际本地实例执行迁移；隔离迁移测试不等于真实实例部署验收。后续已完成私有备份、恢复演练、实际本地迁移及真实 HTTP 验收，当前事实见[后续运行记录](../../runtime-20261111/README.md)。
- **有证据**：`status=enabled` 只表示用户确认收录；草稿未写入源码目录、未加载、未执行。静态报告不硬编码单元测试、前端构建或进程隔离 PASS。以上测试验证项目本身，不执行草稿自带测试。
- **推断**：当前证据可关闭受控草稿目录的 E7 切片，不能证明任何代码运行时安全或独立进程隔离。

## 未完成与未来路线

**文档声明**：核心继续单机运行；Windows 验收因环境缺失继续暂缓，未增加 Windows job。E8 SDK、Provider、模板生态、独立扩展运行时均为“建议，待确认，当前不实施”。没有新增跨项目运行时代码。OPEN 索引建议记录 E5 → E6 → E7 已按顺序完成本轮切片，绑定本次提交和上述最终门禁，并保留目录收录不执行及 Windows 暂缓边界；实际本地迁移状态以后续运行记录为准。
