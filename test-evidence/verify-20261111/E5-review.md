# E5 验收映射复核（2026-11-11，Asia/Shanghai）

代码基线：`d3ab624`；本次仅修复 E5 既有角色数据范围越权，并增加负向验收。

## 有证据

- 角色复制：`organizations/views.py` 的 `RoleCopyView`，保留权限与数据范围，仅在当前组织查找源角色；`organizations/tests/test_role_extensions.py` 的 `test_copy_preserves_permissions_and_scope` 和跨组织拒绝测试。
- 批量授权：`MemberBatchRoleView` 在原子事务内先校验所有当前组织成员，再批量改角色；负向测试证明混入外组织成员时不修改任何成员、不写成功审计。
- 数据范围：`all`/`own` 两种策略，Feature 列表、详情、更新和删除通过 `scoped_records`；个人范围角色管理员不能通过创建、修改、复制或分配角色扩权到全部数据。损坏策略按个人范围处理。
- 越权/组织隔离：当前切片新增 3 个测试，覆盖上述范围扩权、跨组织复制/批量授权原子拒绝、个人范围详情/修改/删除拒绝。

| 验证命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.venv/bin/pytest -q organizations/tests/test_role_extensions.py organizations/tests/test_negative_boundaries.py organizations/tests/test_management_api.py` | 0 | 20 passed |
| `.venv/bin/pytest -q` | 0 | 65 passed |
| `.venv/bin/python manage.py makemigrations --check --dry-run` | 0 | No changes detected |
| `.venv/bin/python manage.py check` | 0 | No issues |
| `npm exec vue-tsc -- --noEmit`（frontend） | 0 | 通过 |
| `npm run build`（frontend） | 0 | 通过，仅 chunk size 提示 |

跳过项：无。上述门禁通过后才进入 E6；Windows 验收按用户决定暂缓，未运行。

## 文档声明与限制

- 本轮数据范围契约仅 `all`/`own`，不宣称部门、下级组织或自定义表达式策略。
- E6、E7 另行复核，不因 E5 或历史 62 个测试通过就宣称它们完整完成。
- 未来扩展建议，待确认，当前不实施：E8 SDK/Provider/模板生态、独立扩展运行时；不共享跨项目运行时代码。
