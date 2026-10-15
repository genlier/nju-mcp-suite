from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import hashlib
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
import keyring
from filelock import FileLock

from suite_common import state_dir

CODE_ROOT = Path(__file__).resolve().parent
ROOT = state_dir("dev")
SERVICE='nju-mcp-suite:dev'
GIT_URL='https://git.nju.edu.cn'
MAX_OUTPUT=4*1024*1024


def config():
    path=ROOT/'config.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def credential(name):
    secret=keyring.get_password(SERVICE,name)
    if not secret:
        raise ValueError('尚未配置凭据，请运行 python manage.py setup 对应服务。')
    return secret


def valid_path(path):
    if not path or len(path)>2000 or path.startswith('/') or '\\' in path or any(ord(c)<32 for c in path):
        raise ValueError('请使用仓库内相对文件路径。')
    if any(part in ('','.','..','.git') for part in path.split('/')):
        raise ValueError('文件路径包含无效目录。')
    return path


def gitlab(method,path,token=None,**kwargs):
    token=token if token is not None else credential('gitlab')
    try:
        with httpx.Client(timeout=30,follow_redirects=False) as client:
            with client.stream(method,GIT_URL+'/api/v4'+path,headers={'PRIVATE-TOKEN':token},**kwargs) as response:
                if not 200<=response.status_code<300:
                    raise ValueError(f'GitLab HTTP {response.status_code}：请检查 Token 权限、仓库、分支及文件版本。')
                content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>MAX_OUTPUT:
                        raise ValueError('响应超过 4 MiB，请缩小读取范围。')
                return json.loads(content),dict(response.headers)
    except httpx.RequestError:
        raise ValueError('GitLab 连接失败；若是提交操作，请先查询提交记录再决定是否重试。') from None


def project_prefix(project):
    if not project or len(project)>300 or any(ord(c)<32 for c in project):
        raise ValueError('项目 ID 或 namespace/project 无效。')
    return '/projects/'+quote(project,safe='')


def gitlab_projects(search='',page=1,limit=20):
    if not 1<=page<=10000 or not 1<=limit<=100:
        raise ValueError('page 范围 1–10000，limit 范围 1–100。')
    data,headers=gitlab('GET','/projects',params={'membership':'true','search':search,'page':page,'per_page':limit,'simple':'true','order_by':'last_activity_at'})
    return {'projects':[{k:item.get(k) for k in ('id','name','path_with_namespace','default_branch','web_url')} for item in data],'next_page':headers.get('x-next-page') or None}


def gitlab_tree(project,path='',ref='HEAD',page=1,limit=50):
    if path:
        valid_path(path)
    if not 1<=page<=10000 or not 1<=limit<=100:
        raise ValueError('分页参数无效。')
    data,headers=gitlab('GET',project_prefix(project)+'/repository/tree',params={'path':path,'ref':ref,'page':page,'per_page':limit})
    return {'items':data,'next_page':headers.get('x-next-page') or None}


def gitlab_file(project,path,ref='HEAD'):
    valid_path(path)
    data,_=gitlab('GET',project_prefix(project)+'/repository/files/'+quote(path,safe=''),params={'ref':ref})
    if data.get('size',0)>1024*1024:
        raise ValueError('文本读取上限 1 MiB。')
    content=base64.b64decode(data['content'],validate=True)
    if len(content)>1024*1024:
        raise ValueError('文本读取上限 1 MiB。')
    try:
        text=content.decode('utf-8')
    except UnicodeError:
        raise ValueError('该文件不是 UTF-8 文本。') from None
    return {'path':path,'content':text,'last_commit_id':data.get('last_commit_id'),'commit_id':data.get('commit_id'),'content_is_untrusted':True}


def gitlab_commit(project,branch,path,content,message,last_commit_id='',create=False):
    valid_path(path)
    if not branch or not message.strip() or len(message)>2000 or len(content.encode())>1024*1024:
        raise ValueError('分支/提交说明为空或内容超过大小限制。')
    action={'action':'create' if create else 'update','file_path':path,'content':content}
    if not create:
        if not re.fullmatch('[0-9a-f]{40,64}',last_commit_id):
            raise ValueError('修改前先读取文件，并传入返回的 last_commit_id。')
        action['last_commit_id']=last_commit_id
    data,_=gitlab('POST',project_prefix(project)+'/repository/commits',json={'branch':branch,'commit_message':message,'actions':[action]})
    return {k:data.get(k) for k in ('id','short_id','title','web_url')}


def tex_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('git.tex.nju.edu.cn','tex.nju.edu.cn') or parsed.port not in (None,443) or parsed.username not in (None,'git') or parsed.password is not None or parsed.query or parsed.fragment or parsed.path in ('','/') or any(ord(ch)<32 for ch in url) or '\\' in url:
        raise ValueError('请填写项目同步页面的 HTTPS Git 地址；支持 git@ 用户名，密码或令牌请在隐藏输入处填写。')
    return url


def alias_name(alias):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',alias):
        raise ValueError('项目别名须为 1–50 个英文字母、数字、横线或下划线。')
    return alias


def ensure_askpass():
    import sys
    if any(ch in sys.executable + str(CODE_ROOT) for ch in '\r\n%'):
        raise ValueError('Python 或项目路径包含不支持的批处理字符。')
    helper = ROOT/'askpass.cmd'
    script = '@echo off\nsetlocal DisableDelayedExpansion\nchcp 65001 >nul\n"' + sys.executable + '" "' + str(CODE_ROOT/'askpass.py') + '" %*\n'
    helper.write_text(script, encoding='utf-8')
    return helper


def git_env(alias,temporary=None):
    env=os.environ.copy()
    for name in list(env):
        if name.startswith('GIT_') or name.startswith('GCM_'):
            env.pop(name)
    env.update({'GIT_ASKPASS':str(ensure_askpass()),'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'Never','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_ALLOW_PROTOCOL':'https','GIT_NO_REPLACE_OBJECTS':'1','NJU_TEX_ALIAS':alias})
    if temporary:
        env.update({'NJU_TEX_USERNAME':temporary['username'],'NJU_TEX_SETUP_PASSWORD':temporary['password']})
    return env


def run_git(args,alias,repo=None,input_bytes=None,extra_env=None,temporary=None):
    binary=shutil.which('git')
    if not binary:
        raise ValueError('找不到本机 Git 客户端。')
    env=git_env(alias,temporary)
    if extra_env:
        env.update(extra_env)
    (ROOT/'cache/empty-hooks').mkdir(parents=True,exist_ok=True)
    command=[binary,'-c','credential.helper=','-c','http.followRedirects=false',
             '-c','http.lowSpeedLimit=1','-c','http.lowSpeedTime=30',
             '-c','core.hooksPath='+str(ROOT/'cache/empty-hooks')]
    if config().get('tex_direct',True):
        command.extend(['-c','http.proxy='])
    if repo:
        command.extend(['--git-dir',str(repo)])
    try:
        result=subprocess.run(command+args,input=input_bytes,
                              stdin=subprocess.DEVNULL if input_bytes is None else None,
                              capture_output=True,env=env,timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError('Git 操作超时；若正在推送，请先查询远端提交再决定是否重试。') from None
    if result.returncode:
        # Keep authentication output and provider messages out of tool errors.
        raise ValueError('Git 操作失败：请检查项目同步地址、Git 登录凭据、分支或远端更新冲突。')
    if len(result.stdout)>MAX_OUTPUT:
        raise ValueError('Git 输出超过 4 MiB，请缩小读取范围。')
    return result.stdout


def tex_remote(alias,project=None,temporary=None):
    alias_name(alias)
    project=project or config().get('tex_projects',{}).get(alias)
    if not project:
        raise ValueError('此 TeX 项目尚未配置，请运行 python manage.py setup tex。')
    url=tex_url(project['git_url'])
    output=run_git(['ls-remote','--symref',url,'HEAD'],alias,temporary=temporary).decode()
    branch=re.search(r'^ref: refs/heads/(.+)\tHEAD$',output,re.M)
    commit=re.search(r'^([0-9a-f]{40,64})\tHEAD$',output,re.M)
    if not branch or not commit:
        raise ValueError('远端项目未返回默认分支和 HEAD，请确认项目已初始化。')
    return {'branch':branch[1],'commit_id':commit[1]}


def open_tex_project(url,alias=''):
    tex_url(url)
    alias=alias_name(alias or ('project-'+hashlib.sha256(url.encode()).hexdigest()[:12]))
    cfg=config()
    account=cfg.get('tex_account')
    if not account:
        raise ValueError('尚未配置 TeX 账户，请运行 python manage.py setup tex。')
    old=cfg.get('tex_projects',{}).get(alias)
    if old and old['git_url']!=url:
        raise ValueError('此别名已用于另一个项目，请使用其他别名。')
    project={'git_url':url,'username':urlsplit(url).username or account['username']}
    info=tex_remote(alias,project,temporary={'username':project['username'],'password':credential('tex-account')})
    cfg.setdefault('tex_projects',{})[alias]=project
    (ROOT/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'alias':alias,**info}


class TexProject:
    def __init__(self,alias):
        self.alias=alias_name(alias)
        self.cfg=config().get('tex_projects',{}).get(alias)
        if not self.cfg:
            raise ValueError('此 TeX 项目尚未配置，请运行 python manage.py setup tex。')
        tex_url(self.cfg['git_url'])
        self.repo=ROOT/'cache'/(alias+'.git')
        self.repo.parent.mkdir(exist_ok=True)
        self.lock=FileLock(str(self.repo)+'.lock',timeout=15)

    def git(self,args,**kwargs):
        return run_git(args,self.alias,self.repo,**kwargs)

    def sync(self):
        info=tex_remote(self.alias,self.cfg)
        if not self.repo.exists():
            run_git(['clone','--bare','--quiet','--',self.cfg['git_url'],str(self.repo)],self.alias)
        else:
            saved=self.git(['config','--get','remote.origin.url']).decode().strip()
            if saved!=self.cfg['git_url']:
                raise ValueError('本机缓存地址与项目配置不同，请使用新项目别名。')
            self.git(['fetch','--quiet','--prune','origin','+refs/heads/*:refs/heads/*'])
        return info

    def tree(self,offset=0,limit=100):
        if not 0<=offset<=100000 or not 1<=limit<=200:
            raise ValueError('offset 范围 0–100000，limit 范围 1–200。')
        with self.lock:
            info=self.sync()
            raw=self.git(['ls-tree','-r','-z',info['commit_id']])
        rows=[]
        for record in raw.split(b'\x00'):
            if record:
                header,path=record.split(b'\t',1)
                mode,kind,oid=header.decode().split()
                rows.append({'path':path.decode('utf-8',errors='replace'),'type':kind,'mode':mode,'object_id':oid})
        return {**info,'items':rows[offset:offset+limit],'total':len(rows),'next_offset':offset+limit if offset+limit<len(rows) else None}

    def file(self,path):
        valid_path(path)
        with self.lock:
            info=self.sync()
            obj=info['commit_id']+':'+path
            if int(self.git(['cat-file','-s',obj]))>1024*1024:
                raise ValueError('文本文件读取上限 1 MiB。')
            data=self.git(['cat-file','blob',obj])
        try:
            text=data.decode('utf-8')
        except UnicodeError:
            raise ValueError('目标不是 UTF-8 文本文件。') from None
        return {**info,'path':path,'content':text,'content_is_untrusted':True}

    def update(self,path,content,message,expected_commit):
        valid_path(path)
        if not message.strip() or len(message)>2000 or len(content.encode())>1024*1024 or not re.fullmatch('[0-9a-f]{40,64}',expected_commit):
            raise ValueError('提交说明、内容大小或 expected_commit 无效。')
        with self.lock:
            info=self.sync()
            if info['commit_id']!=expected_commit:
                raise ValueError('远端项目已有新提交，请先重新读取并合并修改。')
            previous=self.git(['ls-tree','-z',expected_commit,'--',path])
            mode='100644'
            if previous:
                mode=previous.split(b' ',1)[0].decode()
                if mode not in ('100644','100755'):
                    raise ValueError('只支持修改普通文件。')
            index=ROOT/'cache'/('index-'+uuid4().hex)
            env={'GIT_INDEX_FILE':str(index),'GIT_AUTHOR_NAME':'NJU TeX user','GIT_COMMITTER_NAME':'NJU TeX user','GIT_AUTHOR_EMAIL':config().get('tex_account',{}).get('username',self.cfg['username']),'GIT_COMMITTER_EMAIL':config().get('tex_account',{}).get('username',self.cfg['username'])}
            try:
                self.git(['read-tree',expected_commit],extra_env=env)
                oid=self.git(['hash-object','-w','--stdin'],input_bytes=content.encode()).decode().strip()
                self.git(['update-index','--add','--cacheinfo',f'{mode},{oid},{path}'],extra_env=env)
                tree=self.git(['write-tree'],extra_env=env).decode().strip()
                commit=self.git(['commit-tree',tree,'-p',expected_commit],extra_env=env,input_bytes=(message+'\n').encode()).decode().strip()
                self.git(['push','--porcelain','origin',commit+':refs/heads/'+info['branch']])
            finally:
                index.unlink(missing_ok=True)
            return {'state':'pushed','branch':info['branch'],'commit_id':commit,'path':path}
