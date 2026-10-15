# NJU MCP Suite · 南大个人服务工具集

将南大邮箱、Box、Table、Git、TeX 和自己的 SSH 电脑接入支持 MCP 的 AI 客户端。一个项目维护六个独立插件，按需安装。

本项目由社区维护，与南京大学及相关服务提供方无隶属关系。当前安装与凭据管理面向 **Windows 10/11**。

| 服务 | 功能 | 授权方式 |
|---|---|---|
| 南大邮箱 | 搜索邮件、读取正文、保存草稿、发送纯文本邮件 | 邮箱客户端专用密码 |
| NJU Box | 目录浏览、文本读取、文件上传和下载 | WebDAV 用户名和专用密码 |
| NJU Table | 列出可访问 Base、查结构、读行、新增及修改行 | 账户级 Token，兼容单 Base Token |
| NJU Git | 列出加入的仓库、读文件、提交单文件修改 | GitLab 个人访问 Token |
| NJU TeX | 读取、修改及推送任意有权限且开启同步的项目源码 | Git 同步令牌，兼容旧版密码认证 |
| Cloud SSH | 执行命令、浏览目录、读文本、SFTP 上传下载 | SSH 密码及固定主机密钥 |

## 1. 安装运行环境

准备 Python **3.11 或更高版本**、Git，以及一个支持本机 MCP 的客户端。开发与本地验证使用 Python 3.13。TeX 同步还要求 Git 命令已加入 PATH：

```powershell
python --version
git --version
git clone https://github.com/genlier/nju-mcp-suite.git
cd nju-mcp-suite
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

若机器有多套 Python，可以选择解释器：

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Python 'python3.13'
```

安装脚本创建 `.venv`、安装依赖，并在 `.local/marketplace` 生成适合**当前安装位置**的插件清单。下文命令均在项目根目录执行。

`requirements.txt` 固定直接依赖；需要复现完整 Windows/Python 3.13 环境时，可安装 `requirements-lock.txt` 中的依赖快照。

本机配置、缓存和文件保存在 `.local/`，密码及 Token 保存在当前 Windows 用户的凭据库，首次配置一次即可。公开源码不含账户、SSH 目标或项目地址，六个服务均从未配置状态开始。

## 2. 配置需要的服务

### 南大邮箱

先在邮箱网页设置中启用 IMAP/SMTP，并获取客户端专用密码：

```powershell
.\.venv\Scripts\python.exe manage.py setup mail
.\.venv\Scripts\python.exe manage.py check mail
```

填写完整的 `@smail.nju.edu.cn` 或 `@nju.edu.cn` 地址，随后隐藏输入客户端专用密码。服务器默认是 `imap.exmail.qq.com:993` 和 `smtp.exmail.qq.com:465`，可在配置时修改主机名；以本人邮箱网页帮助提供的信息为准。配置会验证 IMAP/SMTP 登录，不发送邮件。

客户端先搜索并读取邮件，读取时使用搜索结果返回的 `uid` 与 `uidvalidity`。发送流程是**拟稿 → 展示收件人和全文 → 用户授权 → 发送草稿**。每个草稿只尝试发送一次；`accepted` 表示 SMTP 已接受，最终投递由邮件系统决定。

当前支持纯文本发信及读取附件名称，未提供附件收发。正文读取上限 5 MiB；中文主题搜索每页最多扫描 200 封标题，可继续分页。

### NJU Box

登录 [Box 个人设置](https://box.nju.edu.cn/profile/)，在 WebDAV 设置中复制显示的用户名，并设置 WebDAV 专用密码：

```powershell
.\.venv\Scripts\python.exe manage.py setup box
.\.venv\Scripts\python.exe manage.py check box
```

接口地址为 `https://box.nju.edu.cn/seafdav`。客户端从 `/` 列出资料库，继续使用工具返回的 `path`。资料库名称因人而异。WebDAV 是云端访问方式，SeaDrive 本机盘符无需写入配置。

上传前将文件放入允许的本机暂存目录：

```powershell
.\.venv\Scripts\python.exe manage.py paths box
```

命令显示实际 `uploads`、`downloads` 路径。将源文件复制到 `uploads`，再让客户端上传至完整的远端路径。默认拒绝覆盖。文本读取上限 1 MiB，单文件传输上限 20 MiB。

### NJU Table：账户级授权

推荐账户模式，可列出本人、群组和共享的 Base，按原有权限读写：

```powershell
.\.venv\Scripts\python.exe manage.py setup table-account
.\.venv\Scripts\python.exe manage.py check table-account
```

选择其中一种方式：

- **账户密码登录**：输入本校 Table 接受的登录账户与密码，程序调用账户认证接口获取 Token；若启用双重认证，填写动态口令。
- **导入 Account-Token**：已有账户级 Token 时隐藏输入。南大官方说明网页没有账户级 Token 的生成入口，需要通过 API 认证获取。

SSO 账户能否直接使用密码接口取决于部署配置。若认证失败，向服务管理员确认可用于 API 的账户凭据或账户 Token。这里的 Account-Token 与单个 Base 的 API Token 用途不同。

客户端操作顺序：`nju_table_list_bases` → 选择真实 `workspace_id` 和 `base_name` → `nju_table_metadata` → 读取或修改记录。每次操作按账户权限获取临时授权，无需逐个注册 Base；新增或撤销的共享权限由服务器控制。

仅共享某个**视图**的项目会在目录结果中单独统计，当前工具提供完整 Base 接口。只读共享只能读取。

### NJU Table：单个 Base 授权

在 Table 首页目标 Base 的「⋯ → 高级 → API Tokens」创建 Token，再执行：

```powershell
.\.venv\Scripts\python.exe manage.py setup table
.\.venv\Scripts\python.exe manage.py check table
```

为 Base 设置别名并隐藏输入 Token，之后通过 `alias` 访问。只读 Token 支持读取，读写 Token 支持新增和修改。写入字段使用元数据中的**列名称**；修改记录使用真实 `_id`。公式、系统列等只读字段由插件和服务器校验。

### NJU Git

在 [NJU Git](https://git.nju.edu.cn) 登录后，点击头像 → 编辑个人资料/偏好设置 → Access Tokens。创建个人令牌，填写名称、到期日与权限：

- 只读：`read_api`。
- 需要通过本插件提交修改：`api`。

复制创建后显示的 Token，再执行：

```powershell
.\.venv\Scripts\python.exe manage.py setup git
.\.venv\Scripts\python.exe manage.py check git
```

客户端按名称搜索已加入仓库，使用真实项目 ID 或 `namespace/project`。修改已有文件前先读取并传回 `last_commit_id`；新建文件使用 `create=true`，同时指定分支和提交说明。当前插件提交单个 UTF-8 文件，读取上限 1 MiB。仓库为空或未加入任何项目时，项目列表可以为空。

### NJU TeX

TeX 的 Git 服务 `git.tex.nju.edu.cn` 与代码托管 `git.nju.edu.cn` 分别认证。

1. 用 SSO 登录 [NJU TeX](https://tex.nju.edu.cn)，进入「我的账号」绑定邮箱。
2. 若「我的账号 → Git 同步设置」有令牌入口，创建 **Git 同步令牌**。旧版南大文档使用绑定邮箱时设置的邮箱登录密码，以当前页面提示为准。
3. 打开一个具体项目的源码编辑页，点击**顶部「同步 → Git」**并开启同步，复制生成的 HTTPS Git 地址。支持 `https://git@git.tex.nju.edu.cn/项目标识.git`，其中 `git@` 是固定用户名。
4. 配置本机凭据：

```powershell
.\.venv\Scripts\python.exe manage.py setup tex
.\.venv\Scripts\python.exe manage.py check tex
```

输入账户主邮箱，在隐藏输入栏填 Git 同步令牌或部署支持的旧版密码。具体项目地址可先跳过；之后把有权限项目的同步地址交给客户端，由 `nju_tex_open_project` 打开。已访问列表仅包含打开过的项目。

修改前读取源码，提交时传回 `expected_commit`。远端变更会阻止基于旧版本提交，推送使用普通快进检查。**提交会修改该项目的默认分支**，请明确要操作的项目与文件。当前提供 Git 源码同步，未提供网页编译或 PDF 导出接口。

TeX Git 默认直连，避免校内服务受继承代理影响。如网络必须经过代理，可在 `.local/dev/config.json` 顶层加入 `"tex_direct": false`，由运行进程的代理环境变量决定路由。系统代理和全局 Git 配置不会被修改。

### Cloud SSH

SSH 插件使用你自己有权限的服务器，首次运行交互填写目标：

```powershell
.\.venv\Scripts\python.exe manage.py setup ssh
.\.venv\Scripts\python.exe manage.py check ssh
```

填写主机、用户名和端口。程序显示主机密钥指纹，与可信来源核对后输入 `yes`，再隐藏输入登录密码。后续主机密钥变化会拒绝连接。

远端命令面向 POSIX shell；SFTP 文件接口用于传输。当前版本使用密码认证。上传前运行 `manage.py paths ssh` 查看本机暂存目录，默认排他创建、不覆盖；单文件上限 20 MiB。命令单次最长 120 秒，超时后远端进程状态需另行核对。

## 3. 在 Codex 桌面端安装插件

重新生成清单：

```powershell
.\.venv\Scripts\python.exe manage.py plugins
codex plugin marketplace add .\.local\marketplace
```

按需安装：

```powershell
codex plugin add nju-mail@nju-mcp-suite
codex plugin add nju-box@nju-mcp-suite
codex plugin add nju-table@nju-mcp-suite
codex plugin add nju-git@nju-mcp-suite
codex plugin add nju-tex@nju-mcp-suite
codex plugin add cloud-ssh@nju-mcp-suite
```

在桌面端刷新插件，并在新对话中选择对应插件。stdio 服务由客户端自动启动，通常无需手动开窗口。CLI 子命令以安装版本支持情况为准；插件格式参考 [OpenAI 官方文档](https://developers.openai.com/plugins/build/plugins)。

生成器使用当前 Python 和项目绝对路径。移动项目或重建虚拟环境后，重新生成清单并更新本机插件。旧版私人插件与本项目配置分开；同一对话选择一套即可。

其他 MCP 客户端可从 `.local/client/mcp.json` 复制所需服务器条目，并按该客户端要求合并配置。这份文件含本机路径，仅供本机使用。

可以这样发出指令：

```text
列出我的南大云盘资料库。
列出我有权限的南大 Table，查看其中一个 Base 的结构。
查找我加入的 Git 仓库并读取 README。
打开这个 TeX Git 同步地址，列出源文件。
在已配置的 SSH 服务器执行 pwd。
查找最近的未读邮件，先帮我拟回复草稿。
```

## 4. ChatGPT 网页端与远程接入

网页版需要能访问到 MCP 服务。本机插件清单中的 stdio 命令由你的电脑执行，仅上传源码 ZIP 不会启动这些服务。

以 Table 为例，先在本机终端运行：

```powershell
.\.venv\Scripts\python.exe manage.py serve table --http
```

| 服务 | 本机 HTTP 端点 |
|---|---|
| 邮箱 | `http://127.0.0.1:9785/mcp` |
| Box | `http://127.0.0.1:9787/mcp` |
| Table | `http://127.0.0.1:9788/mcp` |
| SSH | `http://127.0.0.1:9789/mcp` |
| Git | `http://127.0.0.1:9790/mcp` |
| TeX | `http://127.0.0.1:9791/mcp` |

其他服务将命令中的 `table` 换成相应名称，每个 HTTP 服务使用单独终端保持运行。

接入方式：

- 有 Secure MCP Tunnel 权限时，按 [OpenAI 官方隧道文档](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)创建隧道，将 MCP server URL 指向对应本机端点，保持隧道客户端运行。
- 自行部署时，使用具备 HTTPS 和身份验证的 MCP 网关，并让运行服务的系统具有自己的凭据配置。

在 ChatGPT 插件/应用设置里通过 **Add custom MCP server** 添加远程连接；入口和可用性取决于账户与管理员策略。[官方接入说明](https://developers.openai.com/plugins/quickstart)

本项目不包含托管云服务、OpenAI 密钥或隧道账户，也不自动下载第三方隧道二进制。回环 HTTP 端点未实现公网身份验证，请通过受保护的连接接入。

## 5. 测试、排错与开发

运行离线测试和公开文件扫描：

```powershell
.\.venv\Scripts\python.exe tests/run.py
.\.venv\Scripts\python.exe scripts/audit_public.py
```

测试使用临时目录、模拟 HTTP 和本机 SSH 测试服务器，检查邮件防重复发送、路径范围、重定向、Table 授权和字段校验、Git 版本冲突、SSH 主机密钥与超时，以及六个 MCP 服务的工具发现。它们不访问私人账户，也不执行真实远端写入。

`docs/ci-windows.yml` 提供 GitHub Actions 测试模板。需要启用 CI 时，将它复制为 `.github/workflows/test.yml` 后提交；所用 GitHub 令牌须有上传工作流的权限。模板尚未作为在线 Actions 工作流启用，本地测试可独立运行。

原型曾完成 Box 上传、Table 新增和更新、Git 分支提交、TeX 推送及回读验证。整理后的公开版本以离线测试和干净环境协议检查为验证基础；使用者仍需运行本人服务的 `check`。公开测试不附带私人数据或远端测试项目。

常见问题：

| 现象 | 处理 |
|---|---|
| 配置成功后换个 Windows 账户无法登录 | 在当前账户重新配置；凭据库按系统用户隔离 |
| Table 返回 401/403 | 核对账户 Token 与单 Base Token 的用途、有效性和读写权限 |
| Git 项目列表为空 | 确认 Token 对应账号确有已加入的项目 |
| TeX 返回 401 | 核对当前部署要求的是 Git 同步令牌还是旧版密码，以及项目权限 |
| TeX 地址含 `git@` | 可以直接粘贴官方地址；密码和令牌留在隐藏输入栏 |
| TeX 首次认证通过但读取卡住 | 检查网络和代理；代码已隔离 Git 子进程与 MCP 标准输入 |
| 上传提示不在允许范围 | 先把文件放入 `manage.py paths box/ssh` 显示的 uploads 目录 |
| HTTP 端口被占用 | 关闭同一套服务的重复 HTTP 实例，或先使用 stdio |
| 插件没有出现新工具 | 重新生成并更新插件，刷新客户端后新建对话 |

项目结构：

```text
manage.py              统一配置、检查和启动入口
suite_common.py        数据目录、端口及凭据库辅助函数
services/mail/         IMAP/SMTP 与本机草稿
services/workspace/    Box WebDAV 与 Table API
services/dev/          GitLab API 与 TeX Git
services/ssh/          SSH/SFTP
scripts/              本机插件生成与公开文件扫描
tests/                离线单元、协议和本机 SSH 测试
.local/               运行时数据，Git 忽略
```

可通过 `NJU_MCP_DATA_DIR` 环境变量改变运行数据根目录；改变后须为新的数据目录配置账户。该设置不改变服务源码，也不导出凭据库密码。

## 参考与许可证

- [南大 Box WebDAV/API](https://doc.nju.edu.cn/books/17e62/page/webdav-api)
- [南大 Table 账户 Token 说明](https://doc.nju.edu.cn/books/18d80/page/6f3ef)
- [SeaTable API 认证](https://api.seatable.com/reference/authentication)
- [GitLab 个人访问令牌](https://docs.gitlab.com/user/profile/personal_access_tokens/)
- [南大 TeX Git 同步](https://doc.nju.edu.cn/books/latex/page/git)
- [TeXPage Git 同步令牌](https://www.texpage.com/docs/zh/features/texpage-git/)

采用 [MIT License](LICENSE)。服务访问权限及第三方服务条款由各自提供方管理。隐私与发布注意事项见 [SECURITY.md](SECURITY.md)。
