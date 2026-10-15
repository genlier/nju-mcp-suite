import argparse
import getpass
import json
import re

import keyring
from keyring.backends.Windows import WinVaultKeyring

from connections import ROOT, SERVICE, Box, Table, TableAccount, config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('service', choices=['box','table','table-account'])
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not isinstance(keyring.get_keyring(), WinVaultKeyring):
        raise ValueError('此配置入口需要 Windows 凭据库。')
    cfg = config()
    if args.service == 'box':
        if args.check:
            result = Box().list('/', limit=1)
            print('Box 登录成功，根目录项目数：', result['total'])
            return
        print('打开 https://box.nju.edu.cn/profile/ ，复制 WebDAV 访问中的用户名并设置专用密码。')
        username = input('WebDAV 用户名：').strip()
        password = getpass.getpass('WebDAV 密码（隐藏输入）：').strip()
        if not username or not password:
            raise ValueError('用户名或密码为空，未保存。')
        result = Box(username, password).list('/', limit=1)
        keyring.set_password(SERVICE, 'box:' + username, password)
        cfg['box'] = {'username':username}
        print('Box 登录成功，根目录项目数：', result['total'])
    elif args.service == 'table-account':
        if args.check:
            result = TableAccount().list_bases(limit=1)
            print('Table 账户授权成功，可访问 Base 数：', result['total'])
            return
        print('账户授权：1 = 账户密码登录获取 Token；2 = 导入已有 Account-Token。')
        mode = input('选择方式（回车为 1）：').strip() or '1'
        if mode == '1':
            print('使用 Table 接受的 API 登录账户及密码；统一登录账户兼容性以服务端验证为准。')
            username = input('Table 登录账户：').strip()
            password = getpass.getpass('登录密码（隐藏输入）：')
            otp = getpass.getpass('动态口令（未启用双重认证直接回车）：').strip()
            try:
                token = TableAccount.login(username, password, otp)
            except ValueError as exc:
                raise ValueError(str(exc) + ' 若仅支持统一登录，请按 README 的账户授权说明获取 Account-Token 后选择方式 2。') from None
        elif mode == '2':
            token = getpass.getpass('账户 Account-Token（隐藏输入，区别于单个 Base 的 API Token）：').strip()
            if not token:
                raise ValueError('Token 为空，未保存。')
        else:
            raise ValueError('请选择 1 或 2。')
        result = TableAccount(token).list_bases(limit=1)
        keyring.set_password(SERVICE, 'table-account', token)
        cfg['table_account'] = {'configured':True}
        print('Table 账户授权成功，可访问 Base 数：', result['total'])
    else:
        print('在 Table 首页目标 Base 的“…”→高级→API Tokens 中创建 Token。')
        alias = input('Base 别名（回车为 default）：').strip() or 'default'
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', alias):
            raise ValueError('别名仅支持英文字母、数字、横线和下划线。')
        if args.check:
            table = Table(alias)
            print('Table 登录成功，子表数：', len(table.metadata().get('tables',[])))
            return
        token = getpass.getpass('该 Base 的 API Token（隐藏输入）：').strip()
        if not token:
            raise ValueError('Token 为空，未保存。')
        table = Table(alias, token)
        metadata = table.metadata()
        keyring.set_password(SERVICE, 'table:' + alias, token)
        cfg.setdefault('table_bases', {})[alias] = {'name':table.name}
        print('Table 登录成功，子表数：', len(metadata.get('tables',[])))
    (ROOT/'config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    print('认证成功，凭据已保存到 Windows 凭据库。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, keyring.errors.KeyringError) as exc:
        raise SystemExit(str(exc))
