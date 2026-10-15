# 开发与测试

在项目根目录运行测试和文件扫描：

```powershell
.\.venv\Scripts\python.exe tests/run.py
.\.venv\Scripts\python.exe scripts/audit_public.py
```

测试覆盖邮件防重复发送、上传路径、HTTP 重定向、Table 授权及字段校验、Git 版本冲突、SSH 主机密钥和超时，以及六个 MCP 服务的工具发现。测试数据使用临时目录、模拟 HTTP 和本机 SSH 测试服务器。

复现 Windows/Python 3.13 依赖环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

启用 GitHub Actions 时，将 `docs/ci-windows.yml` 复制到 `.github/workflows/test.yml` 后提交。上传工作流使用的 GitHub 令牌需包含 `workflow` 权限。

## 代码目录

| 路径 | 内容 |
|---|---|
| `manage.py` | 配置、检查和启动入口 |
| `suite_common.py` | 数据目录、端口和凭据库辅助函数 |
| `services/mail/` | IMAP/SMTP 与草稿 |
| `services/workspace/` | Box WebDAV 与 Table API |
| `services/dev/` | GitLab API 与 TeX Git |
| `services/ssh/` | SSH/SFTP |
| `scripts/` | 插件生成与文件扫描 |
| `tests/` | 单元与协议测试 |

修改插件生成器后，运行 `manage.py plugins` 重新生成本机清单，再更新客户端中的插件。
