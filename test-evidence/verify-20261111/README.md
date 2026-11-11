# Bixi Seed 验证记录（2026-11-11）

## 提交

- `f9589a2`：E5 角色扩展、E6 受控工具确认/撤销、E7 扩展草稿静态检查与文档口径对齐。

## 门禁结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.venv/bin/pytest -q` | 0 | 通过，62 passed |
| `.venv/bin/python manage.py check` | 0 | 通过 |
| `.venv/bin/python manage.py makemigrations --check --dry-run` | 0 | 通过，无待生成迁移 |
| `npx vue-tsc --noEmit`（`frontend/`） | 0 | 通过 |
| `npm run build`（`frontend/`） | 0 | 通过；仅有 chunk size 提示 |

## 覆盖范围

- E5：角色复制 `POST /api/organizations/roles/<id>/copy/`、组织范围批量授权、`all/own` 数据范围并应用于 Feature 记录读写边界。
- E6：受控 Feature 记录工具目录、方案预览/差异、确认执行、撤销和组织审计；工具不执行任意代码。
- E7：扩展草稿目录、依赖和静态检查、危险调用拒绝、隔离就绪状态；当前仅做准备，不启动扩展进程。
- Windows 验收：按项目决定继续暂缓；`.github/workflows/acceptance.yml` 保持仅 Linux job，未在无环境条件下尝试。

