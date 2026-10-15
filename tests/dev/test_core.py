import asyncio
import base64
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

import backend as b


def git(*args,cwd=None):
    return subprocess.run(['git',*args],cwd=cwd,check=True,capture_output=True).stdout.decode().strip()


class ConnectionTests(unittest.TestCase):
    def test_url_and_path_validation(self):
        official='https://git@git.tex.nju.edu.cn/project.git'
        self.assertEqual(b.tex_url(official),official)
        for url in ('https://evil.example/x.git','http://git.tex.nju.edu.cn/a.git','https://name:secret@git.tex.nju.edu.cn/a.git','https://git.tex.nju.edu.cn:444/a.git','https://git:secret@git.tex.nju.edu.cn/a.git','https://git:@git.tex.nju.edu.cn/a.git','https://other@git.tex.nju.edu.cn/a.git'):
            with self.assertRaises(ValueError):
                b.tex_url(url)
        for path in ('../x','/tmp/x','.git/config','a/../b','a\\b','a\nx'):
            with self.assertRaises(ValueError):
                b.valid_path(path)

    def test_gitlab_requires_last_commit(self):
        with patch.object(b,'gitlab') as request:
            with self.assertRaises(ValueError):
                b.gitlab_commit('group/project','main','a.txt','text','message')
            request.assert_not_called()

    def test_gitlab_unicode_and_revision(self):
        data={'size':6,'content':base64.b64encode('中文'.encode()).decode(),'last_commit_id':'a'*40,'commit_id':'b'*40}
        with patch.object(b,'gitlab',return_value=(data,{})):
            result=b.gitlab_file('group/project','文档.tex')
            self.assertEqual(result['content'],'中文')
            self.assertEqual(result['last_commit_id'],'a'*40)

    def test_gitlab_redirect_rejected(self):
        seen=[]
        def handler(request):
            seen.append(request.url.host)
            return httpx.Response(302,headers={'location':'https://evil.example/'})
        client=httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=False)
        with patch.object(b.httpx,'Client',return_value=client):
            with self.assertRaisesRegex(ValueError,'302'):
                b.gitlab('GET','/user',token='synthetic')
        self.assertEqual(seen,['git.nju.edu.cn'])

    def test_account_credentials_open_arbitrary_projects(self):
        cfg={'tex_account':{'username':'user@example.org'}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(b,'ROOT',Path(tmp)),patch.object(b,'config',return_value=cfg),patch.object(b,'credential',return_value='synthetic'),patch.object(b,'tex_remote',return_value={'branch':'main','commit_id':'a'*40}) as check:
            first=b.open_tex_project('https://git.tex.nju.edu.cn/one.git')
            second=b.open_tex_project('https://git.tex.nju.edu.cn/two.git')
            self.assertNotEqual(first['alias'],second['alias'])
            self.assertEqual(len(cfg['tex_projects']),2)
            self.assertEqual(check.call_args.kwargs['temporary']['username'],'user@example.org')
            self.assertNotIn('synthetic',(Path(tmp)/'config.json').read_text())
            official=b.open_tex_project('https://git@git.tex.nju.edu.cn/official.git')
            self.assertEqual(check.call_args.kwargs['temporary']['username'],'git')
            self.assertEqual(cfg['tex_projects'][official['alias']]['username'],'git')

    def test_native_git_askpass(self):
        value='synthetic-!&-credential'
        output=b.run_git(['credential','fill'],'test',input_bytes=b'protocol=https\nhost=git.tex.nju.edu.cn\n\n',temporary={'username':'test@example.org','password':value}).decode()
        self.assertIn('username=test@example.org',output)
        self.assertIn('password='+value,output)

    def test_bare_repo_commit_and_conflict(self):
        original_env=b.git_env
        def file_env(alias,temporary=None):
            env=original_env(alias,temporary)
            env['GIT_ALLOW_PROTOCOL']='file:https'
            return env
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            work=root/'work'
            work.mkdir()
            git('init','-b','main',cwd=work)
            git('config','user.name','Test',cwd=work)
            git('config','user.email','test@example.org',cwd=work)
            (work/'main.tex').write_text('original',encoding='utf-8')
            git('add','main.tex',cwd=work)
            git('commit','-m','initial',cwd=work)
            remote=root/'remote.git'
            git('clone','--bare',str(work),str(remote))
            (root/'cache').mkdir()
            cache=root/'cache/demo.git'
            git('clone','--bare',str(remote),str(cache))
            cfg={'tex_projects':{'demo':{'git_url':'https://git.tex.nju.edu.cn/demo.git','username':'test@example.org'}}}
            def info(*args,**kwargs):
                return {'branch':'main','commit_id':git('--git-dir',str(remote),'rev-parse','HEAD')}
            with patch.object(b,'ROOT',root),patch.object(b,'config',return_value=cfg),patch.object(b,'git_env',side_effect=file_env),patch.object(b.TexProject,'sync',side_effect=info):
                project=b.TexProject('demo')
                old=git('--git-dir',str(remote),'rev-parse','HEAD')
                result=project.update('main.tex','修改后','update main',old)
                self.assertEqual(result['state'],'pushed')
                self.assertEqual(git('--git-dir',str(remote),'show','main:main.tex'),'修改后')
                with self.assertRaisesRegex(ValueError,'新提交'):
                    project.update('main.tex','stale','stale write',old)
                self.assertFalse(list((root/'cache').glob('index-*')))
