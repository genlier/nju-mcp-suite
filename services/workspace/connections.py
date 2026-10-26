from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import httpx
import keyring
from defusedxml import ElementTree as XML

from suite_common import state_dir

ROOT = state_dir("workspace")
BOX_URL = 'https://box.nju.edu.cn/seafdav'
TABLE_URL = 'https://table.nju.edu.cn'
SERVICE = 'nju-mcp-suite:workspace'
MAX_RESPONSE = 4 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024


def config() -> dict:
    path = ROOT / 'config.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def secret(name: str) -> str:
    value = keyring.get_password(SERVICE, name)
    if not value:
        raise ValueError('尚未配置凭据，请运行 python manage.py setup 对应服务。')
    return value


def request(method, url, *, max_bytes=MAX_RESPONSE, **kwargs):
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            with client.stream(method, url, **kwargs) as response:
                if response.status_code not in (200, 201, 204, 207):
                    status = response.status_code
                    message = {401:'认证失败，请核对专用密码或 API Token。',403:'没有权限，请核对账户、Token 及其读写权限。',404:'目标不存在或当前服务器不支持该接口。',412:'目标已存在或版本已变化，请重新查询。',429:'服务限流，请稍后重试。'}.get(status, '服务请求失败。')
                    raise ValueError(f'HTTP {status}：{message}')
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError(f'响应超过 {max_bytes} 字节限制，请缩小查询范围。')
                return response.status_code, bytes(data), dict(response.headers)
    except httpx.RequestError:
        if method not in ('GET', 'PROPFIND', 'OPTIONS'):
            raise ValueError('写入请求连接中断，结果待核对；先读取目标确认，避免重复写入。') from None
        raise ValueError('连接失败或超时，请检查网络及服务可用性。') from None


def json_request(method, url, **kwargs):
    _, data, _ = request(method, url, **kwargs)
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError):
        raise ValueError('服务器未返回 JSON，请检查接口地址和部署版本。') from None
    if isinstance(result, dict) and (result.get('success') is False or result.get('error_message') or result.get('error_msg')):
        raise ValueError('服务器返回操作失败，请核对表名、行 ID、字段类型及权限。')
    return result


def box_path(path: str) -> str:
    if not path.startswith('/') or '\\' in path or any(ord(c) < 32 for c in path):
        raise ValueError('云盘路径须以 / 开头，使用目录查询返回的 path。')
    if any(part in ('.', '..') for part in path.split('/')):
        raise ValueError('路径包含无效的相对目录。')
    return path


def box_url(path: str) -> str:
    return BOX_URL + quote(box_path(path), safe='/')


class Box:
    def __init__(self, username=None, password=None):
        cfg = config().get('box', {})
        self.username = username or cfg.get('username')
        if not self.username:
            raise ValueError('Box 尚未配置，请运行 python manage.py setup box。')
        self.auth = httpx.BasicAuth(self.username, password if password is not None else secret('box:' + self.username))

    def list(self, path='/', offset=0, limit=50):
        box_path(path)
        if not 0 <= offset <= 100000 or not 1 <= limit <= 100:
            raise ValueError('offset 范围 0–100000，limit 范围 1–100。')
        payload = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:resourcetype/><d:getcontentlength/><d:getlastmodified/><d:getetag/></d:prop></d:propfind>'
        _, data, _ = request('PROPFIND', box_url(path), auth=self.auth, headers={'Depth':'1','Content-Type':'application/xml; charset=utf-8'}, content=payload)
        try:
            root = XML.fromstring(data)
        except Exception:
            raise ValueError('云盘未返回有效的 WebDAV 目录。') from None
        items = []
        for row in root.findall('{DAV:}response'):
            href = urlsplit(row.findtext('{DAV:}href', default=''))
            if href.netloc and href.netloc != 'box.nju.edu.cn':
                continue
            remote = unquote(href.path)
            if not remote.startswith('/seafdav/'):
                continue
            remote = remote[len('/seafdav'):]
            try:
                box_path(remote)
            except ValueError:
                continue
            if remote.rstrip('/') == path.rstrip('/'):
                continue
            # Keep direct children only, even if a server ignores Depth.
            prefix = path.rstrip('/') + '/'
            if not remote.startswith(prefix) or '/' in remote[len(prefix):].rstrip('/'):
                continue
            prop = None
            for propstat in row.findall('{DAV:}propstat'):
                if ' 200 ' in propstat.findtext('{DAV:}status', default=''):
                    prop = propstat.find('{DAV:}prop')
                    break
            if prop is None:
                continue
            size = prop.findtext('{DAV:}getcontentlength', default='')
            items.append({'path':remote, 'name':prop.findtext('{DAV:}displayname') or remote.rstrip('/').rsplit('/',1)[-1], 'is_directory':prop.find('{DAV:}resourcetype/{DAV:}collection') is not None, 'bytes':int(size) if size.isdigit() else None, 'modified':prop.findtext('{DAV:}getlastmodified'), 'etag':prop.findtext('{DAV:}getetag')})
        items.sort(key=lambda row: (not row['is_directory'], row['name'].casefold()))
        end = offset + limit
        return {'path':path,'items':items[offset:end],'total':len(items),'has_more':end < len(items),'next_offset':end if end < len(items) else None}

    def read(self, path, max_bytes=1024*1024):
        return request('GET', box_url(path), auth=self.auth, max_bytes=max_bytes)[1]

    def put(self, path, content: bytes, overwrite=False):
        if path.endswith('/'):
            raise ValueError('上传目标必须是完整文件路径。')
        headers = {} if overwrite else {'If-None-Match':'*'}
        status, _, _ = request('PUT', box_url(path), auth=self.auth, content=content, headers=headers)
        return {'path':path,'bytes':len(content),'http_status':status,'state':'written'}


class TableAccount:
    def __init__(self, token=None):
        if token is None and not config().get('table_account'):
            raise ValueError('账户授权尚未配置，请运行 python manage.py setup table-account。')
        self.headers = {'Authorization':'Bearer ' + (token if token is not None else secret('table-account'))}

    @staticmethod
    def login(username, password, otp=''):
        if not username or not password:
            raise ValueError('账户或密码为空，未保存。')
        headers = {}
        if otp:
            if not re.fullmatch(r'\d{6}', otp):
                raise ValueError('动态口令须为 6 位数字。')
            headers['X-SEAFILE-OTP'] = otp
        result = json_request('POST', TABLE_URL + '/api2/auth-token/',
                              headers=headers, data={'username':username,'password':password})
        token = result.get('token') if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError('登录接口未返回账户 Token。统一登录账户请查阅 README 的账户授权说明。')
        return token

    def list_bases(self, offset=0, limit=50):
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise ValueError('offset 范围 0–1000000，limit 范围 1–100。')
        result = json_request('GET', TABLE_URL + '/api/v2.1/workspaces/',
                              headers=self.headers, params={'detail':'true'})
        if not isinstance(result, dict) or not isinstance(result.get('workspace_list'), list):
            raise ValueError('工作区接口未返回有效目录。')
        bases, seen, restricted = [], set(), 0
        for workspace in result['workspace_list']:
            restricted += len(workspace.get('shared_view_list', [])) + len(workspace.get('group_shared_views', []))
            for field in ('table_list', 'shared_table_list', 'group_shared_dtables'):
                for base in workspace.get(field, []):
                    workspace_id = base.get('workspace_id', workspace.get('id'))
                    name = base.get('name')
                    if not str(workspace_id).isdigit() or int(workspace_id) < 1 or not isinstance(name, str) or not name:
                        continue
                    identity = (int(workspace_id), name)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    bases.append({'workspace_id':identity[0], 'base_name':name,
                                  'uuid':base.get('uuid'), 'workspace_name':workspace.get('name'),
                                  'permission':base.get('permission')})
        bases.sort(key=lambda b:(b['workspace_id'], b['base_name'].casefold()))
        end = offset + limit
        return {'bases':bases[offset:end], 'total':len(bases), 'has_more':end < len(bases),
                'next_offset':end if end < len(bases) else None,
                'view_only_shares':restricted,
                'note':'目录包含有 Base 访问权限的项目；仅共享某个视图的项目需单独的视图接口。',
                'content_is_untrusted':True}

    def base_token(self, workspace_id, base_name):
        if type(workspace_id) is not int or workspace_id < 1:
            raise ValueError('workspace_id 须为目录返回的正整数。')
        if not isinstance(base_name, str) or not base_name or len(base_name) > 255 or base_name in ('.', '..') or any(ord(ch) < 32 for ch in base_name):
            raise ValueError('请使用目录返回的完整 Base 名称。')
        path = f'/api/v2.1/workspace/{workspace_id}/dtable/{quote(base_name, safe="")}/temp-api-token/'
        result = json_request('GET', TABLE_URL + path, headers=self.headers)
        token = result.get('api_token') if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError('服务器未返回此 Base 的临时 API Token。')
        return token


class Table:
    def __init__(self, alias='default', token=None, *, workspace_id=0, base_name=''):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', alias):
            raise ValueError('Base 别名须为 1–50 个英文字母、数字、横线或下划线。')
        if workspace_id or base_name:
            if token is not None:
                raise ValueError('账户模式与单个 Base Token 请分别使用。')
            token = TableAccount().base_token(workspace_id, base_name)
        elif token is None:
            if alias not in config().get('table_bases', {}):
                raise ValueError('此 Base 尚未配置，请运行 python manage.py setup table，或使用账户模式的 workspace_id 与 base_name。')
            token = secret('table:' + alias)
        data = json_request('GET', TABLE_URL + '/api/v2.1/dtable/app-access-token/', headers={'Authorization':'Bearer ' + token})
        try:
            self.uuid = str(uuid.UUID(data['dtable_uuid']))
            self.headers = {'Authorization':'Bearer ' + data['access_token']}
        except (ValueError, KeyError, TypeError):
            raise ValueError('获取 Base Token 失败，服务器响应缺少必要字段。') from None
        self.name = data.get('dtable_name', base_name or alias)
        self.alias = alias
        self.workspace_id = workspace_id
        self.gateway = bool(data.get('use_api_gateway'))
        if self.gateway:
            self.prefix = TABLE_URL + '/api-gateway/api/v2/dtables/' + self.uuid
        else:
            server = data.get('dtable_server', '').rstrip('/')
            parsed = urlsplit(server)
            if parsed.scheme != 'https' or parsed.netloc != 'table.nju.edu.cn' or parsed.query or parsed.fragment or not parsed.path.startswith('/dtable-server'):
                raise ValueError('旧版表格服务器地址未通过校验，请检查部署接口。')
            self.prefix = server + '/api/v1/dtables/' + self.uuid

    def call(self, method, path, **kwargs):
        return json_request(method, self.prefix + path, headers=self.headers, **kwargs)

    def metadata(self):
        result = self.call('GET', '/metadata/')
        return result.get('metadata', result)

    def rows(self, table_name, offset=0, limit=50, view_name=''):
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise ValueError('offset 范围 0–1000000，limit 范围 1–100。')
        params = {'table_name':table_name,'start':offset,'limit':limit+1,'convert_keys':'true'}
        if view_name:
            params['view_name'] = view_name
        result = self.call('GET', '/rows/', params=params)
        rows = result.get('rows', result.get('results', []))
        has_more = len(rows) > limit
        return {'alias':self.alias,'workspace_id':self.workspace_id,'base_name':self.name,'table_name':table_name,'rows':rows[:limit], 'has_more':has_more,'next_offset':offset+limit if has_more else None, 'content_is_untrusted':True}

    def validate_columns(self, table_name, values):
        table = next((t for t in self.metadata().get('tables',[]) if t.get('name') == table_name), None)
        if table is None:
            raise ValueError('子表不存在，请先查询结构获取准确名称。')
        columns = {c['name']:c for c in table.get('columns',[])}
        if not values or len(values) > 100 or len(json.dumps(values,ensure_ascii=False).encode()) > 100000:
            raise ValueError('写入内容为空或超过字段数量/大小限制。')
        for name in values:
            if name not in columns:
                raise ValueError('存在未知列名，请先查询结构，使用列名称。')
            if columns[name].get('type') in ('formula','link-formula','auto-number','ctime','mtime','creator','last-modifier'):
                raise ValueError('写入内容包含计算列或系统只读列。')

    def append(self, table_name, values):
        self.validate_columns(table_name, values)
        path = '/rows/' if self.gateway else '/batch-append-rows/'
        result = self.call('POST', path, json={'table_name':table_name,'rows':[values]})
        return {'state':'written','result':result}

    def update(self, table_name, row_id, values):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', row_id):
            raise ValueError('请使用查询返回的真实 row_id。')
        self.validate_columns(table_name, values)
        payload = {'table_name':table_name,'updates':[{'row_id':row_id,'row':values}]} if self.gateway else {'table_name':table_name,'row_id':row_id,'row':values}
        return {'state':'written','result':self.call('PUT', '/rows/', json=payload)}
