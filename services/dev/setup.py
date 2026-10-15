import argparse
import getpass
import json
from urllib.parse import urlsplit

import keyring
from keyring.backends.Windows import WinVaultKeyring

from backend import ROOT,SERVICE,alias_name,config,gitlab,tex_remote,tex_url


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('service',choices=['git','tex'])
    args=parser.parse_args()
    if not isinstance(keyring.get_keyring(),WinVaultKeyring):
        raise ValueError('需要 Windows 凭据库。')
    cfg=config()
    if args.service=='git':
        print('打开 https://git.nju.edu.cn/-/user_settings/personal_access_tokens 创建 Token。读取用 read_api；提交 API 用 api。')
        token=getpass.getpass('NJU Git 个人访问 Token（隐藏输入）：').strip()
        if not token:
            raise ValueError('Token 为空，未保存。')
        user,_=gitlab('GET','/user',token=token)
        keyring.set_password(SERVICE,'gitlab',token)
        cfg['git']={'username':user['username']}
        print('Git 认证成功：',user['username'])
    else:
        username=input('TeX 账户主邮箱：').strip()
        if '@' not in username or any(ord(c)<32 for c in username):
            raise ValueError('请填写 TeX 账户主邮箱。')
        password=getpass.getpass('TeX Git 同步令牌（旧版为邮箱登录密码，隐藏输入）：')
        if not password:
            raise ValueError('密码为空，未保存。')
        url=input('可选：项目 Git 同步地址（回车跳过，以后可访问任意授权项目）：').strip()
        if url:
            tex_url(url)
            alias=alias_name(input('此项目的便捷别名（回车为 default）：').strip() or 'default')
            project={'git_url':url,'username':urlsplit(url).username or username}
            info=tex_remote(alias,project,temporary={'username':project['username'],'password':password})
            cfg.setdefault('tex_projects',{})[alias]=project
            print('TeX Git 认证成功，默认分支：',info['branch'])
        else:
            print('已配置账户级凭据；实际 Git 认证将在首次访问项目时验证。')
        keyring.set_password(SERVICE,'tex-account',password)
        cfg['tex_account']={'username':username}
    (ROOT/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    print('凭据已保存到 Windows 凭据库。')


if __name__=='__main__':
    try:
        main()
    except (ValueError,keyring.errors.KeyringError) as exc:
        raise SystemExit(str(exc))
    except (EOFError,KeyboardInterrupt):
        raise SystemExit(130)
