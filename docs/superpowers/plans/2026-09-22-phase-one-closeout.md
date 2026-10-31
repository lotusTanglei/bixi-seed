# 第一阶段收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持现有 API 和安全边界兼容的情况下，完成成员生命周期、审计增强、Feature 版本、负向测试、前端和文档收口。

**Architecture:** 采用现有 Django 应用的增量扩展。组织状态和邀请逻辑集中在 organizations 服务层，审计由统一 `write_audit` 写入；Feature 版本是追加式快照，当前 manifest 仍由 Feature 持有。前端只调用当前 API，不保存敏感凭据或令牌。

**Tech Stack:** Django 5.2、Django REST Framework、SQLite、pytest/pytest-django、Vue 3、TypeScript、Element Plus。

---

### Task 1: 数据模型和迁移

**Files:**
- Modify: `organizations/models.py`
- Modify: `features/models.py`
- Create: generated migrations under `organizations/migrations/` and `features/migrations/`
- Test: model/API tests added in later tasks

- [x] 在 Membership 增加 status、invited_at、accepted_at、invited_by，并提供兼容 is_active 映射；新增 MemberInvitation 的组织、用户、角色、token digest、过期时间、创建者、接受时间和状态字段。
- [x] 将 AuditLog.organization 改为 nullable，增加 scope 和系统级索引，保留组织查询索引。
- [x] 在 Feature 增加 current_version，在 features 中增加不可变 FeatureVersion 与 `(feature, version)` 唯一约束。
- [x] 运行 `python manage.py makemigrations organizations features`，审阅迁移默认值和历史数据转换；运行 `python manage.py makemigrations --check --dry-run`。

### Task 2: 状态、邀请和所有者规则服务

**Files:**
- Modify: `organizations/services.py`
- Test: `organizations/tests/test_management_api.py`

- [x] 统一 active membership 查询只接受 status=active，并让旧 is_active 数据在迁移后保持正确状态。
- [x] 实现随机 token 哈希、过期/撤销/接受状态检查、复用 User 和 Membership 的邀请服务。
- [x] 实现最后 owner、owner 自我移除、owner 降级、跨组织对象和角色权限上限校验。
- [x] 确保所有服务方法在事务内更新状态并调用 write_audit，metadata 只包含非敏感标识。

### Task 3: 组织和认证 API

**Files:**
- Modify: `organizations/views.py`
- Modify: `organizations/urls.py`
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Test: `accounts/tests/test_auth.py`, `organizations/tests/test_management_api.py`, new negative tests

- [x] 增加邀请创建/列表/撤销端点；邀请创建只允许 member.manage，返回一次性 token 和接受链接，列表不返回 token。
- [x] 增加匿名邀请接受端点，校验密码至少 10 位，激活用户和 membership，写审计并建立登录态。
- [x] 扩展成员 PATCH/DELETE 支持 disabled/active、移除后重新加入、资料/角色审计，并拒绝修改 owner。
- [x] 增加 transfer-owner 和 leave 端点，执行 owner 保护和二次确认。
- [x] 为登录成功/失败、登出、切换组织和无成员访问补齐系统/组织审计。
- [x] 将组织名称、角色、跨组织和无权限错误响应稳定为 400/403/404。

### Task 4: 审计查询与 AI 审计

**Files:**
- Modify: `organizations/views.py`
- Modify: `organizations/services.py`
- Modify: `ai/views.py`
- Test: `organizations/tests/test_management_api.py`, `ai/tests/test_api.py`, `ai/tests/test_feature_planning.py`

- [x] 审计查询实现 action、object_type、actor、success、date_from/date_to、page/page_size，默认 20 最大 100，按 `-created_at`。
- [x] 组织成员只能查当前组织且需 audit.read；系统日志只对超级管理员开放；不提供写/删接口。
- [x] 为 AI 配置、会话、对话完成、方案提议/确认/拒绝、非法 Provider 记录审计，排除 API Key 和密码。
- [x] 确保 proposal 只能确认或拒绝一次，未确认不能创建 Feature，重复操作返回 400。

### Task 5: Feature 版本与回滚

**Files:**
- Modify: `features/services.py`
- Modify: `features/views.py`
- Modify: `features/urls.py`
- Modify: `features/models.py`
- Test: `features/tests/test_feature_api.py`, new version/negative tests

- [x] 发布前校验 manifest，创建递增 FeatureVersion 快照、更新 current_version/status，并写带 version 的审计。
- [x] 增加版本列表和详情端点，按组织范围只读返回历史快照。
- [x] 增加 rollback 端点，校验 feature.manage、version/confirm，从历史快照复制工作定义并创建新版本，写 from/to 审计。
- [x] 记录读取按当前 manifest 忽略历史多余字段，记录写入继续调用 validate_record_data；未发布/停用和损坏 manifest 保持不可公开访问。

### Task 6: 负向测试和 filekit 边界

**Files:**
- Create/Modify: `accounts/tests/test_negative_api.py`, `organizations/tests/test_negative_api.py`, `features/tests/test_negative_api.py`, `ai/tests/test_negative_api.py`, `core/tests/test_filekit.py`

- [x] 覆盖未登录、错误密码、停用登录、登出 session、无成员用户和当前组织隔离。
- [x] 覆盖 role.manage/audit.read/feature CRUD/ai.use/ai.configure 逐项 403，角色越权授予和 owner 分配保护。
- [x] 覆盖非法 manifest 类型、重复 key、min/max、长度、未知字段、停用/未发布记录、损坏 manifest。
- [x] 覆盖 AI 未确认、重复 confirm/reject、非法 Provider。
- [x] 覆盖 filekit 扩展名、大小、分类、Excel 行列上限和边界值。
- [x] 先逐文件运行 pytest，修复接口状态码/数据泄漏，再运行完整 `pytest -q`。

### Task 7: 前端管理体验

**Files:**
- Modify: `frontend/src/views/OrganizationsView.vue`
- Modify: `frontend/src/views/FeatureView.vue`
- Modify: `frontend/src/stores/session.ts`
- Test/verify: `frontend` typecheck and build

- [x] 增加邀请弹窗、待接受邀请列表、撤销、成员状态和重新邀请操作。
- [x] 增加 owner 转移和退出组织二次确认，处理 owner 保护错误。
- [x] 审计区增加 action/object/success/date/page/page_size 筛选和分页，同时兼容旧数组响应。
- [x] Feature 页面增加版本列表、版本详情、字段级 diff 和回滚确认；不把 token/API Key 写入 store。
- [x] 运行 `npx vue-tsc --noEmit && npm run build`。

### Task 8: 许可证、文档和最终验证

**Files:**
- Create: `LICENSE`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_PLAN.md`
- Modify: `docs/architecture.md`
- Inspect: `.env.example`

- [x] 添加 MIT LICENSE，README 说明许可证、邀请接受、成员生命周期、审计筛选和 Feature 版本/回滚行为。
- [x] 更新第一阶段状态与第二阶段已收口能力，补充回滚不迁移记录数据的兼容说明。
- [x] 确认 `.env.example` 无需新增配置；若实现需要新增项，补充安全默认值。
- [x] 执行 `python manage.py check`、`python manage.py makemigrations --check --dry-run`、`pytest -q`、前端检查/构建。
- [x] 执行 `./start.sh && curl -s http://127.0.0.1:8000/api/health/ && ./stop.sh`；Windows/Linux 未在本机实测的脚本明确标注人工验收。
