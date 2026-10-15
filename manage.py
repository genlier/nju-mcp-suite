import argparse
import json
import runpy
import sys

from suite_common import COMPONENTS, PORTS, REPO_ROOT, state_dir


def launch(service, action, http=False):
    if service == 'all':
        from combined import make_server
        make_server().run(transport='streamable-http' if http else 'stdio')
        return
    component = COMPONENTS[service]
    folder = REPO_ROOT/'services'/component
    sys.path.insert(0, str(folder))
    if service == 'mail':
        file = folder/'mail_bridge.py'
        arguments = ['--setup'] if action=='setup' else ['--check'] if action=='check' else ['--http'] if http else []
    elif action == 'setup':
        file = folder/'setup.py'
        arguments = [service] if component in ('workspace','dev') else []
    elif action == 'check':
        if component == 'workspace':
            file, arguments = folder/'setup.py', [service,'--check']
        elif component == 'ssh':
            file, arguments = folder/'setup.py', ['--check']
        else:
            import backend
            if service=='git':
                user,_ = backend.gitlab('GET','/user')
                print(json.dumps({'authenticated':True,'username':user['username']},ensure_ascii=False))
            else:
                cfg = backend.config()
                if not cfg.get('tex_account'):
                    raise ValueError('请先运行 python manage.py setup tex。')
                projects = cfg.get('tex_projects',{})
                if not projects:
                    print('账户凭据已配置；请在聊天中提供项目 Git 同步地址以验证实际访问。')
                for alias in projects:
                    print(json.dumps({'alias':alias,**backend.tex_remote(alias)},ensure_ascii=False))
            return
    else:
        if service == 'table-account':
            raise ValueError('table-account 为配置方式；启动服务请使用 table。')
        file = folder/'server.py'
        arguments = [service] if component in ('workspace','dev') else []
        if http:
            arguments.append('--http')
    sys.argv = [str(file),*arguments]
    runpy.run_path(str(file),run_name='__main__')


def main():
    parser = argparse.ArgumentParser(description='南大个人 MCP 工具集')
    commands = parser.add_subparsers(dest='action',required=True)
    for action in ('setup','check','serve','paths'):
        cmd = commands.add_parser(action)
        cmd.add_argument('service',choices=[*COMPONENTS,*(['all'] if action=='serve' else [])])
        if action=='serve':
            cmd.add_argument('--http',action='store_true')
    commands.add_parser('plugins')
    args = parser.parse_args()
    if args.action=='plugins':
        from scripts.build_plugins import build
        build()
    elif args.action=='paths':
        data = state_dir(COMPONENTS[args.service])
        for name in ('uploads','downloads'):
            (data/name).mkdir(exist_ok=True)
        print(json.dumps({'data':str(data),'uploads':str(data/'uploads'),'downloads':str(data/'downloads'),
                          'http_endpoint':f'http://127.0.0.1:{PORTS.get(args.service,9788)}/mcp'},ensure_ascii=False,indent=2))
    else:
        launch(args.service,args.action,getattr(args,'http',False))


if __name__=='__main__':
    try:
        main()
    except (ValueError,EOFError,KeyboardInterrupt) as exc:
        raise SystemExit(str(exc))
