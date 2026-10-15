# NJU MCP Suite · 南大个人服务工具集

将南大邮箱、Box、Table、Git、TeX 和自己的 SSH 电脑接入支持 MCP 的 AI 客户端。安装一个合集插件，即可使用全部六项服务。

运行环境：**Windows 10/11**。

| 服务 | 功能 | 授权方式 |
|---|---|---|
| 南大邮箱 | 搜索邮件、读取正文、保存草稿、发送纯文本邮件 | 邮箱客户端专用密码 |
| NJU Box | 目录浏览、文本读取、文件上传和下载 | WebDAV 用户名和专用密码 |
| NJU Table | 列出可访问 Base、查结构、读行、新增及修改行 | 账户级 Token，兼容单 Base Token |
| NJU Git | 列出加入的仓库、读文件、提交单文件修改 | GitLab 个人访问 Token |
| NJU TeX | 读取、修改及推送任意有权限且开启同步的项目源码 | Git 同步令牌，兼容旧版密码认证 |
| Cloud SSH | 执行命令、浏览目录、读文本、SFTP 上传下载 | SSH 密码及固定主机密钥 |

## 1. 安装运行环境

安装 Python **3.11 或更高版本**、Git，以及一个支持本机 MCP 的客户端。确认 Python 和 Git 已加入 PATH：

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

首次使用时配置需要的服务，之后即可重复调用。配置和文件保存在 `.local/`，密码及 Token 保存在当前 Windows 用户的凭据库。

## 2. 配置需要的服务

### 南大邮箱

先在邮箱网页设置中启用 IMAP/SMTP，并获取客户端专用密码：

```powershell
.\.venv\Scripts\python.exe manage.py setup mail
.\.venv\Scripts\python.exe manage.py check mail
```

填写完整的 `@smail.nju.edu.cn` 或 `@nju.edu.cn` 地址，随后隐藏输入客户端专用密码。服务器默认是 `imap.exmail.qq.com:993` 和 `smtp.exmail.qq.com:465`；若邮箱帮助中给出了其他服务器，在配置时填写对应主机名。

客户端先搜索并读取邮件，读取时使用搜索结果返回的 `uid` 与 `uidvalidity`。发送流程是**拟稿 → 展示收件人和全文 → 用户授权 → 发送草稿**。每个草稿只尝试发送一次；`accepted` 表示 SMTP 已接受，最终投递由邮件系统决定。

邮件工具可发送纯文本邮件、读取正文和查看附件名称。正文读取上限 5 MiB；中文主题搜索每页最多扫描 200 封标题，使用返回的 `next_offset` 继续查询。

### NJU Box

登录 [Box 个人设置](https://box.nju.edu.cn/profile/)，在 WebDAV 设置中复制显示的用户名，并设置 WebDAV 专用密码：

```powershell
.\.venv\Scripts\python.exe manage.py setup box
.\.venv\Scripts\python.exe manage.py check box
```

接口地址为 `https://box.nju.edu.cn/seafdav`。客户端从 `/` 列出资料库，再使用工具返回的 `path` 打开目录或文件。

上传前将文件放入允许的本机暂存目录：

```powershell
.\.venv\Scripts\python.exe manage.py paths box
```

命令显示实际 `uploads`、`downloads` 路径。将源文件复制到 `uploads`，再让客户端上传至完整的远端路径。覆盖已有文件时指定 `overwrite=true`。文本读取上限 1 MiB，单文件传输上限 20 MiB。

### NJU Table：账户级授权

推荐账户模式，可列出本人、群组和共享的 Base，按原有权限读写：

```powershell
.\.venv\Scripts\python.exe manage.py setup table-account
.\.venv\Scripts\python.exe manage.py check table-account
```

选择其中一种方式：

- **账户密码登录**：输入本校 Table 接受的登录账户与密码，程序调用账户认证接口获取 Token；若启用双重认证，填写动态口令。
- **导入 Account-Token**：已有账户级 Token 时隐藏输入。南大官方说明网页没有账户级 Token 的生成入口，需要通过 API 认证获取。

若 SSO 账户通过密码方式认证失败，向服务管理员获取可用于 API 的账户凭据或 Account-Token，再运行配置命令。

客户端操作顺序：`nju_table_list_bases` → 选择返回的 `workspace_id` 和 `base_name` → `nju_table_metadata` → 读取或修改记录。

从目录中选择具有 Base 访问权限的项目；仅共享某个视图的项目单独统计。只读共享用于查询，读写共享可新增和修改记录。

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

客户端按名称搜索已加入仓库，使用返回的项目 ID 或 `namespace/project`。修改已有文件前先读取并传回 `last_commit_id`；新建文件使用 `create=true`，同时指定分支和提交说明。每次提交一个 UTF-8 文件，读取上限 1 MiB。

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

输入账户主邮箱，在隐藏输入栏填 Git 同步令牌或旧版密码。具体项目地址可先跳过；之后把项目的同步地址交给客户端，由 `nju_tex_open_project` 打开，后续使用返回的项目别名。

修改前读取源码，提交时传回 `expected_commit`。若远端已有新提交，重新读取后再修改。提交写入项目的默认分支；同步完成后，在 TeX 网页中编译和查看 PDF。

TeX Git 默认直连。如需使用代理，在 `.local/dev/config.json` 顶层加入 `"tex_direct": false`，再为运行进程设置代理环境变量。

### Cloud SSH

首次使用时配置 SSH 连接：

```powershell
.\.venv\Scripts\python.exe manage.py setup ssh
.\.venv\Scripts\python.exe manage.py check ssh
```

填写主机、用户名和端口。程序显示主机密钥指纹，与可信来源核对后输入 `yes`，再隐藏输入登录密码。后续主机密钥变化会拒绝连接。

远端命令面向 POSIX shell；SFTP 文件接口用于传输。当前版本使用密码认证。上传前运行 `manage.py paths ssh` 查看本机暂存目录，默认排他创建、不覆盖；单文件上限 20 MiB。命令单次最长 120 秒，超时后远端进程状态需另行核对。

## 3. 在 Codex 桌面端安装合集插件

重新生成清单：

```powershell
.\.venv\Scripts\python.exe manage.py plugins
codex plugin marketplace add .\.local\marketplace
```

安装合集：

```powershell
codex plugin add nju-suite@nju-mcp-suite
```

合集插件自动启动一个 MCP 进程，提供六项服务的全部 33 个工具。服务凭据按第 2 节分别配置，客户端通过同一连接调用。

如只需单项服务，也可以选择独立插件：

```powershell
codex plugin add nju-mail@nju-mcp-suite
codex plugin add nju-box@nju-mcp-suite
codex plugin add nju-table@nju-mcp-suite
codex plugin add nju-git@nju-mcp-suite
codex plugin add nju-tex@nju-mcp-suite
codex plugin add cloud-ssh@nju-mcp-suite
```

在桌面端刷新插件，并在新对话中选择对应插件。客户端会自动启动 stdio 服务。

移动项目或重建虚拟环境后，重新生成清单并更新本机插件。

其他 MCP 客户端可将 `.local/client/mcp.json` 中的 `njuSuite` 条目合并到客户端配置中。单项服务配置位于 `.local/client/mcp-separate.json`。同一客户端选择合集或独立插件中的一种方式。

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

网页端通过远程 MCP 地址或隧道连接本机服务。

在本机终端运行以下命令，即可启动全部服务：

```powershell
.\.venv\Scripts\python.exe manage.py serve all --http
```

统一 MCP 地址为 **`http://127.0.0.1:9780/mcp`**。将隧道或 MCP 网关指向这个地址，即可通过一个连接使用全部服务。

需要单独启动某项服务时，将 `all` 换成服务名称，例如 `table`。各项服务的独立端点如下：

| 服务 | 本机 HTTP 端点 |
|---|---|
| 邮箱 | `http://127.0.0.1:9785/mcp` |
| Box | `http://127.0.0.1:9787/mcp` |
| Table | `http://127.0.0.1:9788/mcp` |
| SSH | `http://127.0.0.1:9789/mcp` |
| Git | `http://127.0.0.1:9790/mcp` |
| TeX | `http://127.0.0.1:9791/mcp` |

接入方式：

- 有 Secure MCP Tunnel 权限时，按 [OpenAI 官方隧道文档](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)创建隧道，将 MCP server URL 指向对应本机端点，保持隧道客户端运行。
- 自行部署时，使用具备 HTTPS 和身份验证的 MCP 网关，并让运行服务的系统具有自己的凭据配置。

在 ChatGPT 插件/应用设置里点击 **Add custom MCP server**，填写远程 MCP 地址或选择已连接的隧道。[官方接入说明](https://developers.openai.com/plugins/quickstart)

## 5. 常见问题

| 现象 | 处理 |
|---|---|
| 配置成功后换个 Windows 账户无法登录 | 在当前账户重新配置；凭据库按系统用户隔离 |
| Table 返回 401/403 | 核对账户 Token 与单 Base Token 的用途、有效性和读写权限 |
| Git 项目列表为空 | 确认 Token 对应账号确有已加入的项目 |
| TeX 返回 401 | 核对当前部署要求的是 Git 同步令牌还是旧版密码，以及项目权限 |
| TeX 地址含 `git@` | 可以直接粘贴官方地址；密码和令牌留在隐藏输入栏 |
| TeX 首次认证通过但读取卡住 | 检查网络；需要代理时设置 `tex_direct=false` 和进程代理环境变量 |
| 上传提示不在允许范围 | 先把文件放入 `manage.py paths box/ssh` 显示的 uploads 目录 |
| HTTP 端口被占用 | 关闭同一套服务的重复 HTTP 实例，或先使用 stdio |
| 插件没有出现新工具 | 重新生成并更新插件，刷新客户端后新建对话 |

需要更改配置和文件的保存位置时，设置 `NJU_MCP_DATA_DIR` 环境变量，再为新目录配置服务。

开发与测试方法见 [开发说明](docs/development.md)。

## 参考与许可证

- [南大 Box WebDAV/API](https://doc.nju.edu.cn/books/17e62/page/webdav-api)
- [南大 Table 账户 Token 说明](https://doc.nju.edu.cn/books/18d80/page/6f3ef)
- [SeaTable API 认证](https://api.seatable.com/reference/authentication)
- [GitLab 个人访问令牌](https://docs.gitlab.com/user/profile/personal_access_tokens/)
- [南大 TeX Git 同步](https://doc.nju.edu.cn/books/latex/page/git)
- [TeXPage Git 同步令牌](https://www.texpage.com/docs/zh/features/texpage-git/)

采用 [MIT License](LICENSE)。安全说明见 [SECURITY.md](SECURITY.md)。
