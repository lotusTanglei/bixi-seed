# Bixi Seed

Bixi Seed 是一个面向小团队和个人开发者的轻量应用基座，支持 Windows、macOS 和 Linux 单机运行。

稳定核心负责认证、组织、成员、角色、权限、审计和大模型配置。组织支持顶级组织和多级子组织，创建子组织必须拥有上级组织的管理权限。账号使用用户名登录，邮箱不是必填项；成员资料要求姓名和联系方式，联系方式可以填写手机号、微信号或其他便于联系的信息。业务功能以隔离的声明式 Feature 定义保存，AI 可以在不修改核心启动代码的前提下，帮助用户创建常见的增删改查功能。

## 技术栈

- Python 3.12 及以上
- Django 5.2 LTS + Django REST Framework
- Uvicorn，负责运行 Django ASGI 服务
- Vue 3 + TypeScript + Vite + Element Plus
- SQLite
- OpenAI Python SDK，默认使用 DeepSeek，也支持 OpenAI-compatible 接口
- openpyxl，提供受限的 `.xlsx` / `.xlsm` 解析能力

## 本地初始化

运行环境要求：

- Python 3.12 或更高版本
- Node.js LTS
- Windows：PowerShell 5.1 或更高版本
- macOS/Linux：Bash 和 `curl`

首次使用时，Windows 运行 `setup.bat`，macOS/Linux 运行 `./setup.sh`。脚本会创建 Python 虚拟环境、安装依赖、构建前端、执行迁移，并在交互终端中询问是否创建第一个管理员。

Windows 操作：

- `start.bat`：后台启动核心服务
- `stop.bat`：停止核心服务
- `restart.bat`：重启核心服务
- `status.bat`：查看进程和健康状态
- `logs.bat`：查看服务日志
- `backup.bat`：创建一致性的 SQLite 备份
- `restore.bat <备份文件>`：恢复 SQLite 数据、执行迁移并启动服务
- `install-autostart.bat`：设置 Windows 登录后自动启动
- `remove-autostart.bat`：移除 Windows 登录后自动启动
- `dev.bat`：启动 Django 和 Vite 开发服务

macOS/Linux 操作：

- `./start.sh`：后台启动核心服务
- `./stop.sh`：停止核心服务
- `./restart.sh`：重启核心服务
- `./status.sh`：查看进程和健康状态
- `./logs.sh`：查看服务日志
- `./backup.sh`：创建一致性的 SQLite 备份
- `./restore.sh <备份文件>`：恢复 SQLite 数据、执行迁移并启动服务
- `./install-autostart.sh`：设置登录后自动启动
- `./remove-autostart.sh`：移除登录后自动启动
- `./dev.sh`：启动 Django 和 Vite 开发服务

默认访问地址是 `http://127.0.0.1:8000`。

## 配置 AI

登录后进入“AI 助手”，推荐使用 DeepSeek。新组织默认使用 `https://api.deepseek.com` 和 `deepseek-v4-flash`，通常只需要填写 DeepSeek API Key 并保存；API Key 只会在服务端加密保存，不会返回到浏览器。高级配置可以调整兼容接口地址和模型名称。

Shell 脚本通过 `nohup` 在后台运行 `run-core.sh`，并使用 PID 文件、日志文件和 `/api/health/` 管理服务状态。Linux 使用用户级 systemd 自启动，macOS 使用 LaunchAgent，Windows 使用 PowerShell 进程管理和任务计划程序。

恢复前必须先停止核心服务。恢复命令会校验 SQLite 备份文件，恢复数据，执行核心迁移，启动服务并检查 `/api/health/`。数据库、日志和备份默认保存在 `data/`；如需修改位置，请在初始化前于 `.env` 中设置 `BIXI_DATA_DIR`。

## 不使用初始化提示创建管理员

完成迁移后可以运行：

```text
    .venv\\Scripts\\python.exe manage.py bootstrap_admin --username admin --contact 13800000000 --password change-this-password --organization "我的组织"
```

密码至少需要 10 个字符。不要提交 `.env` 或真实 API Key。

## 核心边界

- 核心代码位于 `config`、`core`、`accounts`、`organizations` 和 `ai`。
- 菜单显示、路由进入和后端接口都会按当前组织角色的权限判断；权限目录按组织权限、AI 助手和业务功能菜单分组。
- `features` 保存数据驱动的功能定义，核心启动时不会导入生成代码。
- API Key 在服务端加密保存，不会由 API 返回。
- AI 助手默认以 DeepSeek 作为首选示例，底层使用 OpenAI-compatible Chat Completions 协议。
- 所有组织 API 都从已认证 Session 的当前组织解析数据范围，不信任浏览器提交的组织编号。
- Feature Manifest 只接受有限的字段和页面配置，AI 生成的任意代码不会在核心进程执行。
- AI 生成方案后，必须经过功能管理员确认才会创建草稿 Feature；发布仍是独立操作。
- `core/filekit` 只提供安全文件保存和 Excel 解析复用能力，不预置业务导入页面；详细约定见 [`docs/filekit.md`](docs/filekit.md)。
- 站点设置可以编辑 Logo、登录页欢迎语/描述和首页标题/描述，不会创建业务模块。
- AI 创建业务功能提供按功能形态划分的填空式模板，包括台账类、图表类、表单类、流程类和自定义功能；用户只需填写当前类型的关键内容，状态、筛选条件和补充要求可以按需填写。

## 成员生命周期、审计与版本

管理员可以使用“邀请成员”生成一次性令牌和接受链接。被邀请人打开链接后设置至少 10 位密码，账号和组织成员关系会同时激活并直接建立登录态；邀请可以在有效期内撤销。成员支持停用、恢复、移除和重新邀请，移除只解除组织成员关系，账号可以再次复用。所有者不能自我移除，转移所有权后原所有者降为管理员。

组织审计记录包含操作者、对象、结果、时间和非敏感 metadata，支持按操作、对象、操作者、结果、日期和分页筛选。登录失败等系统级记录只有超级管理员可见，审计日志没有修改或删除接口。

Feature 发布会追加不可变版本快照。版本列表和详情只读，回滚会从历史快照生成新的版本并重新发布，不迁移已有记录；读取时忽略已从当前 manifest 移除的字段，写入仍按当前字段定义校验。损坏或停用的 Feature 不会阻塞核心启动，也不会出现在公开列表。

## 当前维护与验证边界

2026-11-11 本轮只按 E5 剩余 → E6 → E7 推进。有证据的提交、命令、退出码、跳过项和阻塞见[维护执行记录](test-evidence/verify-20261111/README.md)，历史计划与旧测试计数不能替代当前验收。

E6 固定三个 Feature 记录工具，模型只生成提案；用户审查字段、权限、数据差异后确认执行。已执行变更仅在当前权限和数据版本允许时补偿撤销，失败写入会回滚并留审计。本地没有模型配置，真实供应商调用仍阻塞；mock 回归不代表真实模型通过。

E7 仅维护受控草稿目录、依赖/静态/权限检查与内容指纹确认收录；收录不加载或执行草稿代码，不提供运行时隔离证据。SDK、Provider、模板生态及独立运行时均为“建议，待确认，当前不实施”。Windows 验收因无环境继续暂缓，不增加 Windows job。核心继续单机可运行，三项目仅统一证据字段，不共享运行时代码。

## 许可证

Bixi Seed 以 MIT License 发布，详见根目录 [`LICENSE`](LICENSE)。

## 开发说明

生产式运行时，前端构建到 `frontend/dist`，由 Django 提供页面。开发时，`dev.bat` 或 `dev.sh` 会启动 Django（8000 端口）和 Vite（5173 端口），Vite 将 `/api` 转发到 Django。

核心默认只监听 `127.0.0.1`。如需局域网访问，请同时显式设置 `BIXI_BIND_HOST` 和 `BIXI_ALLOWED_HOSTS`。
