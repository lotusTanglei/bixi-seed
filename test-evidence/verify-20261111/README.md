# Bixi Seed 验证记录（2026-11-11）

## 提交

- `f9589a2`：E5 角色扩展、E6 受控工具确认/撤销、E7 扩展草稿静态检查与文档口径对齐；`41a6aaf`：拒绝无效工具记录编号。
- `3df6794`：补充工具记录编号校验的验证口径。

## 本次维护执行记录

- 范围：仅推进 E5 剩余 → E6 → E7；不实现 E8 SDK、Provider、模板生态或独立扩展运行时。
- 变更文件：`organizations/` 的角色复制、批量授权和数据范围边界；`ai/` 的受控工具提案/确认/撤销/审计；`extensions/` 的草稿、依赖和静态检查；对应测试、迁移、文档和前端视图。
- 代码基线：`3df6794`；本次文档记录随本地 `main` 的维护提交保存，未推送。
- 证据分类：以下命令输出为有证据；阶段范围和暂缓项来自项目文档声明；“切片已完成”仅指本记录列出的代码与门禁，不代表 E8 或完整路线图完成。

## 门禁结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.venv/bin/pytest -q` | 0 | 通过，62 passed |
| `.venv/bin/python manage.py check` | 0 | 通过 |
| `.venv/bin/python manage.py makemigrations --check --dry-run` | 0 | 通过，无待生成迁移 |
| `npx vue-tsc --noEmit`（`frontend/`） | 0 | 通过 |
| `npm run build`（`frontend/`） | 0 | 通过；仅有 chunk size 提示 |

跳过项：无验证命令因失败而跳过；Windows 验收因没有 Windows 环境暂缓，未修改 `.github/workflows/acceptance.yml`，也未反复尝试。

## 覆盖范围

- E5：角色复制 `POST /api/organizations/roles/<id>/copy/`、组织范围批量授权、`all/own` 数据范围并应用于 Feature 记录读写边界。
- E6：受控 Feature 记录工具目录、方案预览/差异、确认执行、撤销和组织审计；工具不执行任意代码。
- E7：扩展草稿目录、依赖和静态检查、危险调用拒绝、隔离就绪状态；当前仅做准备，不启动扩展进程。
- Windows 验收：按项目决定继续暂缓；`.github/workflows/acceptance.yml` 保持仅 Linux job，未在无环境条件下尝试。

## 未完成项与后续建议

- 未完成/阻塞：Windows 初始化与脚本验收，解除条件是可用的 Windows 验收环境。
- 建议，待确认，当前不实施：E8 Feature SDK、Provider、模板生态，以及独立扩展进程/运行时；继续保持核心单机可运行和扩展仅在草稿校验后启用。
- 建议，待确认，当前不实施：将本记录的证据字段（提交、命令、退出码、跳过项、阻塞原因）作为其他项目维护记录的统一记录规范；不共享运行时代码。

