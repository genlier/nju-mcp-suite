from __future__ import annotations

import base64
import hashlib
import json
import shlex
import socket
import time
from contextlib import contextmanager
from pathlib import Path

import keyring
import paramiko

from suite_common import state_dir

ROOT = state_dir("ssh")
SERVICE = 'nju-mcp-suite:ssh'
MAX_FILE = 20 * 1024 * 1024


def config():
    path = ROOT/'config.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def credential_name(cfg):
    return f'{cfg["username"]}@{cfg["host"]}:{cfg["port"]}'


def fingerprint(key):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')


@contextmanager
def connect(cfg=None, password=None, trusted_key=None):
    cfg = cfg or config()
    if not cfg.get('host') or not cfg.get('username'):
        raise ValueError('请先运行 python manage.py setup ssh 配置 SSH 登录。')
    if password is None:
        password = keyring.get_password(SERVICE, credential_name(cfg))
    if not password:
        raise ValueError('Windows 凭据库中没有此服务器密码，请运行 python manage.py setup ssh。')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        known = ROOT/'known_hosts'
        if known.exists():
            client.load_host_keys(str(known))
        if trusted_key is not None:
            host = cfg['host'] if cfg['port']==22 else f'[{cfg["host"]}]:{cfg["port"]}'
            client.get_host_keys().add(host, trusted_key.get_name(), trusted_key)
        client.connect(cfg['host'], port=cfg['port'], username=cfg['username'], password=password,
                       allow_agent=False, look_for_keys=False, timeout=10, banner_timeout=15,
                       auth_timeout=20, channel_timeout=15)
        yield client
    except paramiko.BadHostKeyException:
        raise ValueError('服务器主机密钥与已保存记录不符，请先核对服务器身份。') from None
    except paramiko.AuthenticationException:
        raise ValueError('SSH 密码认证失败，请运行 python manage.py setup ssh 更新密码。') from None
    except (paramiko.SSHException, socket.timeout, ConnectionError, OSError) as exc:
        raise ValueError(f'SSH 连接或操作失败（{type(exc).__name__}）；写入或命令中断后请先核对远端状态。') from None
    finally:
        client.close()


def execute(client, command, cwd='', timeout_seconds=30, max_output_bytes=65536):
    if not command.strip() or len(command)>20000 or '\x00' in command:
        raise ValueError('命令为空、过长或包含空字符。')
    if not 1<=timeout_seconds<=120 or not 1024<=max_output_bytes<=200000:
        raise ValueError('超时范围 1–120 秒，输出上限范围 1024–200000 字节。')
    if '\x00' in cwd:
        raise ValueError('工作目录包含空字符。')
    if cwd:
        command = 'cd -- ' + shlex.quote(cwd) + ' && ' + command
    channel = client.get_transport().open_session(timeout=15)
    output = bytearray()
    errors = bytearray()
    truncated = False
    start = time.monotonic()
    try:
        channel.settimeout(min(timeout_seconds,15))
        channel.exec_command(command)
        channel.shutdown_write()
        while True:
            progressed = False
            for ready, receive, target in ((channel.recv_ready, channel.recv, output),(channel.recv_stderr_ready,channel.recv_stderr,errors)):
                if ready():
                    chunk = receive(32768)
                    room = max(0,max_output_bytes-len(output)-len(errors))
                    target.extend(chunk[:room])
                    truncated |= len(chunk)>room
                    progressed = True
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                return {'stdout':output.decode('utf-8',errors='replace'),'stderr':errors.decode('utf-8',errors='replace'),'exit_code':channel.recv_exit_status(),'timed_out':False,'truncated':truncated,'content_is_untrusted':True}
            if time.monotonic()-start>=timeout_seconds:
                return {'stdout':output.decode('utf-8',errors='replace'),'stderr':errors.decode('utf-8',errors='replace'),'exit_code':None,'timed_out':True,'truncated':truncated,'remote_process_state':'unknown; closing SSH channel does not guarantee process termination','content_is_untrusted':True}
            if not progressed:
                time.sleep(0.01)
    finally:
        channel.close()
