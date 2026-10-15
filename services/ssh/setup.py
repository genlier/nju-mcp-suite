import argparse
import getpass
import json
import socket

import keyring
import paramiko
from keyring.backends.Windows import WinVaultKeyring

from ssh_backend import ROOT, SERVICE, config, connect, credential_name, execute, fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    cfg=config()
    if args.check:
        with connect() as client:
            result=execute(client,'id -un; hostname; pwd')
        print(json.dumps(result,ensure_ascii=False))
        return
    if not isinstance(keyring.get_keyring(),WinVaultKeyring):
        raise ValueError('此配置入口需要 Windows 凭据库。')
    host_value=input('SSH 主机名或 IP：').strip()
    username=input('SSH 用户名：').strip()
    port=int(input('SSH 端口（回车为 22）：').strip() or '22')
    if not host_value or not username or not 1<=port<=65535 or any(ord(c)<32 for c in host_value+username):
        raise ValueError('主机名、用户名或端口无效。')
    cfg={'host':host_value,'username':username,'port':port,'auth_mode':'password'}
    print(f'SSH 服务器：{credential_name(cfg)}')
    with socket.create_connection((cfg['host'],cfg['port']),timeout=10) as sock:
        transport=paramiko.Transport(sock)
        try:
            transport.start_client(timeout=15)
            key=transport.get_remote_server_key()
        finally:
            transport.close()
    host=cfg['host'] if cfg['port']==22 else f'[{cfg["host"]}]:{cfg["port"]}'
    hosts=paramiko.HostKeys()
    known=ROOT/'known_hosts'
    if known.exists():
        hosts.load(str(known))
    existing=hosts.lookup(host)
    if existing and not hosts.check(host,key):
        raise ValueError('主机密钥与已保存记录不符，请先核对服务器身份。')
    if not existing:
        print('服务器主机密钥：',key.get_name(),fingerprint(key))
        if input('与服务器管理方提供的指纹核对后，输入 yes 保存：').strip().lower()!='yes':
            raise ValueError('未保存主机密钥。')
    password=getpass.getpass('SSH 登录密码（隐藏输入）：')
    if not password:
        raise ValueError('密码为空，未保存。')
    with connect(cfg,password,trusted_key=key) as client:
        result=execute(client,'id -un; hostname; pwd')
        if result['exit_code']!=0 or result['timed_out']:
            raise ValueError('登录后的只读验证未通过，未保存密码。')
    keyring.set_password(SERVICE,credential_name(cfg),password)
    hosts.add(host,key.get_name(),key)
    hosts.save(str(known))
    cfg['configured']=True
    (ROOT/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SSH 登录成功，密码已保存到 Windows 凭据库。')
    print(result['stdout'].strip())


if __name__=='__main__':
    try:
        main()
    except (ValueError,paramiko.SSHException,OSError,keyring.errors.KeyringError) as exc:
        raise SystemExit(str(exc))
    except (KeyboardInterrupt,EOFError):
        raise SystemExit(130)
