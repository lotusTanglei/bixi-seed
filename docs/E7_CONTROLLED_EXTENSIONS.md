# E7 受控扩展草稿目录

本轮范围是 E5 → E6 门禁完成之后的 E7 最小闭环。**有证据**：实现入口为 `extensions/models.py`、`extensions/services.py`、`extensions/views.py` 和 `frontend/src/views/ExtensionsView.vue`。目录按当前登录组织隔离，管理接口与菜单沿用 `feature.manage`。

## 草稿与校验

草稿保存在现有 `ExtensionDraft` 数据表中，包含相对路径到文本的文件清单、依赖要求和 `permission_manifest` 权限编码数组。文件不会写入源码目录，也不会被导入、执行或安装依赖。

- **有证据**：静态检查拒绝绝对路径、Windows 路径、路径穿越、空路径段、非法 UTF-8、非文本、超过 50 个文件和总计超过 100 KiB 的文件；支持 Python、JSON、Markdown 和 TXT。
- **有证据**：Python 使用 `ast.parse` 校验语法，检查危险名称、属性和导入（包括别名和反射）；JSON 检查语法。静态检查有明确支持边界，不能证明任意代码安全。
- **有证据**：依赖使用显式依赖 `packaging` 解析名称和版本约束，核验当前已安装版本；拒绝缺失依赖、版本冲突、URL、extras、环境 marker 和重复名称。仅检查元数据，不下载、安装或导入草稿依赖。
- **有证据**：权限编码必须在当前 Permission 目录中，且属于操作者在当前组织实际持有的权限。清单只用于审查，不创建角色授权、不扩大数据范围，也不能指定其他组织。

## 确认收录

`GET/POST /api/extensions/drafts/` 列出和创建当前组织草稿；`POST /api/extensions/drafts/{id}/validate/` 重新检查当前文件、依赖与权限。校验通过后保存 `validated_hash`，其 SHA-256 内容包括组织、编码、名称、说明、文件、依赖和权限清单。

`POST /api/extensions/drafts/{id}/enable/` 仅接受字面布尔值 `confirmed: true` 和与当前已校验内容一致的 `content_hash`。服务端锁定该组织草稿、核验哈希，再次检查依赖、语法和当前权限；内容变化、权限撤销或环境依赖变化都会阻止收录。成功时保存确认人、时间、`enabled_hash` 并写入审计；拒绝确认和校验失败也有失败审计。前端先提供文件、依赖、权限和校验结果预览，再显示明确确认提示。

**文档声明**：`status=enabled` 的含义仅为“用户确认收录到受控目录”。`execution_status=not_loaded_or_executed`、`isolation_status=not_executed` 表明草稿代码未加载或执行；不存在独立进程隔离验收证据。静态报告不把单元测试、前端构建或隔离标记为通过。

迁移 `extensions/0002_controlled_catalog_review` 为旧草稿增加权限、内容哈希和确认字段，并使旧校验记录失效，需要按新规则重新检查。逆向迁移不会恢复旧的校验通过状态。

**有证据**：本轮没有对用户实际本地实例执行 `manage.py migrate`，仅用测试数据库验证迁移路径。部署时应先停止实例并备份原数据库，再使用项目虚拟环境执行 `python manage.py migrate`；隔离迁移测试不代表真实实例部署验收。

## 验证与后续边界

**有证据**：本轮项目真实单元测试、Django 检查、迁移漂移检查、vue-tsc 和 Vite 构建的命令、退出码及原始日志单列于 `test-evidence/maintenance-20261111/e7/`。项目测试验证目录与授权实现，不执行草稿自带测试，也不宣称任意草稿已通过运行验收。

**推断**：在不加载草稿代码的边界内，静态检查与确认审计足以形成当前 E7 目录闭环；未来若引入执行能力，仍需另外评审权限执行、资源限制、测试与运行隔离。

**建议，待确认，当前不实施**：E8 SDK、Provider、模板生态和独立扩展运行时。核心继续保持单机运行；本轮不创建 Windows 验收 job，也不重复尝试缺失的 Windows 环境。
