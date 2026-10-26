"""NJU public links and authenticated application forms over HTTP."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import keyring

from connections import MAX_FILE, ROOT, SERVICE, TABLE_URL, TableAccount, box_path, json_request, request

BOX_URL = 'https://box.nju.edu.cn'


def checked_url(value, host):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != host or parsed.username
            or parsed.password or parsed.fragment or any(ord(c) < 32 for c in value)):
        raise ValueError(f'请使用 https://{host}/ 下的完整链接。')
    return value


def page_get(client, url, host):
    for _ in range(7):
        checked_url(url, host)
        with client.stream('GET', url) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get('location', ''))
                continue
            if response.status_code != 200:
                raise ValueError(f'链接访问失败：HTTP {response.status_code}。')
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 4 * 1024 * 1024:
                    raise ValueError('页面超过 4 MiB。')
            return url, data.decode('utf-8')
    raise ValueError('链接重定向次数过多。')


def js_string(source, name):
    # Django escapejs emits JSON-compatible Unicode escapes in single quotes.
    match = re.search(r'\b' + re.escape(name) + r'''\s*:\s*(['"])((?:\\.|(?!\1).)*)\1''', source)
    if not match:
        return None
    raw = match.group(2)
    raw = raw.replace("\\'", "'")
    if match.group(1) == "'":
        raw = raw.replace('"', '\\"')
    try:
        return json.loads('"' + raw + '"')
    except ValueError:
        raise ValueError(f'页面字段 {name} 无法解析。') from None


class BoxUploadLink:
    def __init__(self, url):
        checked_url(url, 'box.nju.edu.cn')
        match = re.fullmatch(r'/u/d/([a-zA-Z0-9_-]{10,100})/?', urlsplit(url).path)
        if not match or urlsplit(url).query:
            raise ValueError('请使用 Box 文件收集链接 /u/d/<token>/。')
        self.token = match.group(1)
        self.url = BOX_URL + '/u/d/' + self.token + '/'

    def inspect(self):
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            final, html = page_get(client, self.url, 'box.nju.edu.cn')
        block = re.search(r'window\.uploadLink\s*=\s*\{(.*?)\};', html, re.S)
        if not block:
            if re.search(r'type=["\']password', html, re.I):
                raise ValueError('此收集链接需要访问密码，请先在浏览器中解锁。')
            raise ValueError('链接已失效或未返回文件收集配置。')
        source = block.group(1)
        self.parent = js_string(source, 'path')
        box_path(self.parent or '')
        self.repo = js_string(source, 'repoID')
        if not self.repo or not re.fullmatch(r'[a-fA-F0-9-]{36}', self.repo):
            raise ValueError('收集页面缺少资料库标识。')
        self.no_quota = bool(re.search(r'\bnoQuota\s*:\s*true\b', source))
        size = re.search(r'\bmaxUploadFileSize\s*:\s*(\d+)', source)
        self.limit = min(MAX_FILE, int(size.group(1))) if size and int(size.group(1)) else MAX_FILE
        return {'url':final, 'directory_name':js_string(source, 'dirName'),
                'shared_by':js_string(source, 'sharedByName'), 'path':self.parent,
                'upload_allowed':not self.no_quota, 'max_bytes':self.limit,
                'content_is_untrusted':True}

    def upload(self, local_path):
        root = (ROOT / 'uploads').resolve()
        source = Path(local_path).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError('请先将要上传的文件放入 manage.py paths box 返回的 uploads 目录。')
        info = self.inspect()
        if self.no_quota:
            raise ValueError('收集方空间不足。')
        if source.stat().st_size > self.limit:
            raise ValueError(f'文件超过 {self.limit} 字节上传限制。')
        # Upload endpoints are short-lived capabilities; keep them out of results/logs.
        data = json_request('GET', BOX_URL + f'/api/v2.1/upload-links/{self.token}/upload/')
        endpoint = data.get('upload_link') if isinstance(data, dict) else None
        if not isinstance(endpoint, str):
            raise ValueError('服务器未返回上传地址。')
        checked_url(endpoint, 'box.nju.edu.cn')
        if not urlsplit(endpoint).path.startswith('/seafhttp/upload-'):
            raise ValueError('服务器返回的上传地址路径无效。')
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        _, body, _ = request('POST', endpoint, params={'ret-json':'1'},
                             data={'parent_dir':self.parent, 'replace':'0'},
                             files={'file':(source.name, content, 'application/octet-stream')})
        try:
            result = json.loads(body)
        except ValueError:
            raise ValueError('上传响应无法确认；请在云盘核对文件，勿重复上传。') from None
        files = result if isinstance(result, list) else [result]
        if len(files) != 1 or not isinstance(files[0], dict) or not files[0].get('id') or files[0].get('size') != len(content):
            raise ValueError('上传响应缺少文件标识或大小不一致；请先核对云盘。')
        uploaded = files[0]
        return {'state':'uploaded', 'directory_name':info['directory_name'],
                'name':uploaded.get('name', source.name), 'bytes':len(content),
                'file_id':uploaded['id'], 'sha256':digest}


def app_directory():
    result = json_request('GET', TABLE_URL + '/api/v2.1/universal-apps/', headers=TableAccount().headers)
    apps = []
    for field in ('my_managed_apps', 'can_use_apps'):
        for app in result.get(field, []):
            if not any(a.get('app_uuid') == app.get('app_uuid') for a in apps):
                apps.append(app)
    return apps


def table_cookies():
    saved = keyring.get_password(SERVICE, 'table-web-session')
    if not saved:
        return {}
    return {c['name']:c['value'] for c in json.loads(saved)
            if c.get('domain', '').lstrip('.') == 'table.nju.edu.cn'}


class TableLink:
    def __init__(self, url):
        checked_url(url, 'table.nju.edu.cn')
        path = urlsplit(url).path
        if not re.fullmatch(r'/(?:dtable/universal-app/links/[a-zA-Z0-9_-]{10,100}|external-apps/[a-f0-9-]{36}|dtable/forms/[a-f0-9-]{36})/?', path):
            raise ValueError('支持通用应用邀请链接、应用直达链接及独立表单链接。')
        self.url = url
        self.cookies = table_cookies()
        self.headers = {'Referer':TABLE_URL + '/'}
        if self.cookies.get('dtable_csrftoken'):
            self.headers['X-CSRFToken'] = self.cookies['dtable_csrftoken']
        self.kind = 'form' if '/dtable/forms/' in path else 'app'
        self.page_id = ''
        if self.kind == 'form':
            self.token = path.rstrip('/').rsplit('/', 1)[-1]

    def open(self):
        # Resolve invite targets without accepting membership during inspection.
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            final, html = page_get(client, self.url, 'table.nju.edu.cn')
        if self.kind == 'app':
            match = re.search(r'/external-apps/([a-f0-9-]{36})/', final)
            if not match:
                raise ValueError('邀请链接未返回通用应用标识。')
            self.token = str(uuid.UUID(match.group(1)))
            target = TABLE_URL + '/external-apps/' + self.token + '/'
            with httpx.Client(timeout=30, cookies=self.cookies, follow_redirects=False) as client:
                final, html = page_get(client, target, 'table.nju.edu.cn')
            access = js_string(html, 'accessToken')
            app_config = js_string(html, 'appConfig')
            if not access or not app_config:
                available = next((a for a in app_directory() if a.get('app_uuid') == self.token), None)
                self.settings = json.loads(available['app_config']).get('settings', {}) if available else {}
                self.name = available.get('app_name', '') if available else ''
                self.tables = []
                self.needs_login = True
                return self.describe()
            self.headers['Authorization'] = 'Token ' + access
            config = json.loads(app_config)
            self.name = config.get('app_name', '')
            self.settings = config.get('settings', {})
            self.current_user = {'name':js_string(html, 'name'), 'id':js_string(html, 'userIdInOrg')}
            self.is_admin = js_string(html, 'isAdmin') in ('True','true') or bool(re.search(r'\bisAdmin\s*:\s*true\b', html))
            role_text = js_string(html, 'roleId')
            role = re.search(r'\broleId\s*:\s*(\d+)', html)
            self.role_id = int(role_text) if role_text and role_text.isdigit() else int(role.group(1)) if role else None
            data = self.call('GET', '/metadata/')
            self.tables = data.get('tables', data.get('metadata', {}).get('tables', []))
        else:
            with httpx.Client(timeout=30, cookies=self.cookies, follow_redirects=False) as client:
                final, html = page_get(client, self.url, 'table.nju.edu.cn')
            raw = js_string(html, 'formConfig')
            metadata = js_string(html, 'dtableMetadata')
            if not raw or not metadata:
                raise ValueError('表单需要登录、已过期或未返回结构。')
            form = json.loads(raw)
            self.name = form.get('form_name', '')
            self.settings = {'pages':[{**form, 'id':'form', 'type':'form', 'name':self.name}]}
            data = json.loads(metadata)
            self.tables = data.get('metadata', data).get('tables', [])
            self.current_user = json.loads(js_string(html, 'user') or '{}')
        self.needs_login = False
        return self.describe()

    def call(self, method, suffix, **kwargs):
        return json_request(method, TABLE_URL + f'/api/v2.1/universal-apps/{self.token}' + suffix,
                            headers=self.headers, cookies=self.cookies, **kwargs)

    def accept_invitation(self):
        if '/dtable/universal-app/links/' not in urlsplit(self.url).path:
            raise ValueError('请使用通用应用邀请链接。')
        if not self.cookies:
            raise ValueError('请先配置 Table 网页会话。')
        with httpx.Client(timeout=30, cookies=self.cookies, follow_redirects=False) as client:
            page_get(client, self.url, 'table.nju.edu.cn')
        result = self.open()
        if result['needs_web_session']:
            raise ValueError('邀请尚未接受或网页会话已失效，请在网页核对。')
        return result

    def describe(self):
        allowed = [p for p in self.settings.get('pages', []) if self.can_view(p)]
        pages = [{k:p.get(k) for k in ('id','name','type')} for p in allowed]
        forms = []
        for page in allowed:
            if page.get('type') != 'form':
                continue
            table = next((t for t in self.tables if t.get('_id') == page.get('table_id')), {})
            columns = {c['key']:c for c in table.get('columns', [])}
            fields = []
            for field in page.get('columns', []):
                column = columns.get(field['key'], {})
                fields.append({'key':field['key'], 'name':field.get('custom_name') or column.get('name'),
                               'type':column.get('type'), 'required':field.get('is_required', False),
                               'column_name':column.get('name'),
                               'description':field.get('description', ''),
                               'default':field.get('default_value') if field.get('enable_fill_default_value') else None,
                               'locked_default':field.get('enable_not_change_default_value', False),
                               'options':(column.get('data') or {}).get('options', []),
                               'validation':{k:v for k,v in (column.get('data') or {}).items()
                                             if k in ('enable_check_format','format_check_type','format_check_regex','enable_check_range','min_value','max_value')},
                               'conditional':bool(field.get('filters')),
                               'require_checked':field.get('require_fill_checked', False),
                               'filters':field.get('filters', [])})
            forms.append({'page_id':page['id'], 'name':page.get('name'), 'fields':fields,
                          'static_elements':page.get('static_elements', [])})
        return {'url':self.url, 'kind':self.kind, 'name':self.name, 'pages':pages,
                'forms':forms, 'needs_web_session':self.needs_login, 'content_is_untrusted':True}

    def can_view(self, page):
        permission = page.get('page_permissions', {}).get('view_rows_permission', {})
        mode = permission.get('permission_type', 'default')
        if getattr(self, 'is_admin', False):
            return True
        if mode == 'specific_roles':
            return getattr(self, 'role_id', None) in permission.get('permitted_roles', [])
        return mode == 'default'

    def rows(self, page_id, offset=0, limit=50):
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise ValueError('offset 范围 0–1000000，limit 范围 1–100。')
        self.open()
        if self.needs_login:
            raise ValueError('请先配置 Table 网页会话。')
        page = next((p for p in self.settings.get('pages', []) if p.get('id') == page_id), None)
        if not page or page.get('type') != 'table' or not self.can_view(page):
            raise ValueError('请选择应用中的表格页面。')
        data = self.call('GET', '/rows/', params={'page_id':page_id, 'start':offset, 'limit':limit + 1})
        rows = data.get('rows', [])
        return {'page_id':page_id, 'rows':rows[:limit], 'has_more':len(rows) > limit,
                'next_offset':offset + limit if len(rows) > limit else None, 'content_is_untrusted':True}

    def prepare(self, page_id, values, allow_partial=False):
        info = self.open()
        if self.needs_login:
            raise ValueError('请先配置 Table 网页会话。')
        form = next((f for f in info['forms'] if f['page_id'] == page_id), None)
        if not form:
            raise ValueError('请选择返回的表单 page_id。')
        fields = form['fields']
        by_name = {f['name']:f for f in fields if f['name']}
        by_key = {f['key']:f for f in fields}
        if not values or len(json.dumps(values, ensure_ascii=False).encode()) > 100000:
            raise ValueError('填写内容为空或超过 100000 字节。')
        row = {}
        for name, value in values.items():
            field = by_key.get(name) or by_name.get(name)
            if not field:
                raise ValueError(f'未知表单字段：{name}。')
            if field['key'] in row:
                raise ValueError('同一字段同时使用名称和 key，请保留一个。')
            if field['locked_default']:
                raise ValueError(f'{name} 使用身份默认值，请留给表单自动填写。')
            if field['type'] not in ('text','long-text','number','single-select','multiple-select','checkbox','date','email','url'):
                raise ValueError(f'{name} 的字段类型暂不支持自动填写。')
            options = [o['name'] for o in field['options']]
            if field['type'] == 'single-select' and value not in options:
                raise ValueError(f'{name} 请使用已有选项。')
            if field['type'] == 'multiple-select' and (not isinstance(value, list) or any(v not in options for v in value)):
                raise ValueError(f'{name} 请使用已有选项组成的数组。')
            if field['type'] == 'number' and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError(f'{name} 请填写有限数值。')
            if field['type'] == 'checkbox' and type(value) is not bool:
                raise ValueError(f'{name} 请填写布尔值。')
            if field['type'] in ('text','long-text','date','email','url') and not isinstance(value, str):
                raise ValueError(f'{name} 请填写文本。')
            length = re.search(r'限\s*(\d+)\s*字', field['description'])
            if length and isinstance(value, str) and len(value) > int(length.group(1)):
                raise ValueError(f'{name} 超过 {length.group(1)} 字限制。')
            row[field['key']] = value.strip() if field['type'] == 'text' else value
        missing = []
        for field in fields:
            key = field['key']
            if field['default'] is not None:
                default = field['default']
                if isinstance(default, str) and '{creator.' in default:
                    default = self.current_user.get('name' if default == '{creator.name}' else 'id')
                if key not in row and default is not None:
                    row[key] = default
            if field['conditional']:
                raise ValueError('此表单包含条件显示字段，请通过网页填写。')
            if field['require_checked'] and row.get(key) is not True:
                missing.append(field['name'] or key)
                continue
            if field['required'] and (key not in row or row[key] is None or row[key] == '' or row[key] == []):
                missing.append(field['name'] or key)
        if missing and not allow_partial:
            raise ValueError('缺少必填字段：' + '、'.join(missing) + '。')
        preview = {by_key[k]['name'] or k:v for k,v in row.items()}
        payload = {}
        for key, value in row.items():
            field = by_key[key]
            if field['type'] == 'long-text' and isinstance(value, str):
                value = {'text':value, 'preview':value[:1000], 'images':[], 'links':[], 'checklist':[]}
            payload[field['column_name']] = value
        folder = ROOT / 'form-drafts'
        folder.mkdir(exist_ok=True)
        draft_id = uuid.uuid4().hex
        draft = {'url':self.url, 'page_id':page_id, 'values':values, 'row_data':payload,
                 'form_hash':hashlib.sha256(json.dumps(form, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                 'preview':preview, 'state':'incomplete' if missing else 'prepared', 'missing_fields':missing}
        (folder / (draft_id + '.json')).write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        return {'draft_id':draft_id, 'state':draft['state'], 'name':self.name, 'page_id':page_id,
                'values':preview, 'missing_fields':missing}


def submit_draft(draft_id):
    if not re.fullmatch(r'[a-f0-9]{32}', draft_id):
        raise ValueError('请使用 prepare 返回的 draft_id。')
    path = ROOT / 'form-drafts' / (draft_id + '.json')
    if not path.is_file():
        raise ValueError('报名草稿不存在。')
    draft = json.loads(path.read_text(encoding='utf-8'))
    if draft['state'] == 'incomplete':
        raise ValueError('草稿尚未补齐必填字段：' + '、'.join(draft.get('missing_fields', [])) + '。')
    if draft['state'] != 'prepared':
        raise ValueError('此草稿已经尝试提交，请先核对已有报名记录。')
    link = TableLink(draft['url'])
    info = link.open()
    if link.needs_login:
        raise ValueError('网页会话已失效，请重新配置。')
    form = next((f for f in info['forms'] if f['page_id'] == draft['page_id']), None)
    if hashlib.sha256(json.dumps(form, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != draft['form_hash']:
        raise ValueError('表单结构已变化，请重新准备填写内容。')
    try:
        path.with_suffix('.attempted').open('x').close()
    except FileExistsError:
        raise ValueError('此草稿已经尝试提交，请先核对已有报名记录。') from None
    draft['state'] = 'unknown'
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
    if link.kind == 'app':
        result = link.call('POST', '/form-submit/', json={'app_page_id':draft['page_id'],
                           'row_data':draft['row_data'], 'new_linked_rows':[], 'link_rows':[]})
    else:
        page = link.settings['pages'][0]
        result = json_request('POST', TABLE_URL + f'/api/v2.1/form-submit/{link.token}/',
                              headers=link.headers, cookies=link.cookies,
                              data={'table_id':page['table_id'], 'row_data':json.dumps(draft['row_data'], ensure_ascii=False)})
    if not isinstance(result, dict) or result.get('success') is False or result.get('error_msg'):
        raise ValueError('提交结果待核对，请读取报名记录。')
    draft['state'] = 'submitted'
    # Store the receipt locally; expose only confirmation and row identity.
    draft['receipt'] = result
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
    return {'draft_id':draft_id, 'state':'submitted', 'row_id':result.get('row_id') or result.get('_id'),
            'success_message':result.get('success_message')}
