# 第一阶段收口设计

## 目标

在不改变现有认证、组织隔离和 Feature 工作定义语义的前提下，补齐成员邀请与生命周期、系统/组织审计、Feature 不可变版本快照、负向测试、前端管理入口和许可证文档。

## 兼容边界

- `Membership.status` 是成员状态唯一事实来源，取值为 `invited`、`active`、`disabled`。现有 `is_active` 字段保留数据库兼容性，但服务层通过 status 映射，响应继续输出 `is_active`，PATCH 继续接受它。
- 邀请复用已有 `User`，新用户密码不可用；令牌只在创建响应和接受链接中出现，数据库保存令牌哈希/唯一标识，不写入审计。
- 旧成员 POST 继续支持管理员直接创建已激活成员；新邀请 API 是不依赖邮件的推荐流程。
- `Feature.manifest` 仍是当前工作/发布定义；`FeatureVersion` 只追加快照。回滚复制历史快照生成新版本，记录数据不迁移，读取忽略已移除字段，写入仍按当前 manifest 校验。
- 审计日志的 organization 可为空，`scope` 区分 `organization` 和 `system`。组织查询永远按当前 Session 组织；系统级日志仅超级管理员可查。

## 后端组件

- `organizations/models.py`：扩展 Membership、AuditLog，新增 MemberInvitation。
- `organizations/services.py`：统一状态/邀请、owner 保护、审计和权限辅助函数。
- `organizations/views.py` 与 `organizations/urls.py`：邀请、接受、生命周期、owner 转移、退出、分页筛选审计端点。
- `accounts/views.py`：登录成功/失败、登出和邀请接受登录态；失败审计不记录密码。
- `features/models.py`、`features/views.py`、`features/urls.py`：FeatureVersion、版本查询、发布快照、回滚。
- `ai/views.py`：方案确认状态、Provider 校验和 AI 审计。
- 迁移只由核心应用生成并维护；不导入生成代码，不要求重启。

## 数据流与安全

每个组织端点先解析 Session 当前组织，再查询组织限定的对象；浏览器提交的 organization id 只用于切换且必须存在 Membership。所有写操作在事务中执行并在成功/失败边界写审计。敏感值（密码、API Key、邀请明文 token）不进入 metadata、响应之外的普通日志或前端状态。

## 前端

在现有 `OrganizationsView.vue` 增加邀请、待接受邀请、撤销、owner 转移和退出流程，成员状态显示兼容 `is_active`。审计区增加筛选和分页。在 `FeatureView.vue` 增加版本列表、字段级 diff 和确认回滚。

## 验收

新增正/负测试覆盖认证、跨组织、无成员、细粒度权限、owner 保护、manifest/记录边界、AI 状态机和 filekit 边界；执行 Django check、迁移检查、完整 pytest、前端类型检查/构建和本机启动健康检查。
