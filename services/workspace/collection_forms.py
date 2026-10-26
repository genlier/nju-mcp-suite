"""Create a new collection base and publish its anonymous form."""
import hashlib
import json
import re
import uuid

import httpx

from connections import ROOT, TABLE_URL, Table, TableAccount, json_request
from links import js_string, page_get

TYPES = {'text','long-text','number','date','email','url','checkbox','single-select','multiple-select'}


def receipt_path(request_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
        raise ValueError('request_id 须为 1–64 个字母、数字、横线或下划线。')
    folder = ROOT / 'collections'
    folder.mkdir(exist_ok=True)
    return folder / (request_id + '.json')


def collection_status(request_id):
    path = receipt_path(request_id)
    if not path.is_file():
        raise ValueError('此 request_id 尚无创建记录。')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    return {k:v for k,v in receipt.items() if k != 'spec_hash'}


def validate_fields(name, fields, workspace_id):
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c)<32 for c in name):
        raise ValueError('收集表名称须为 1–100 个可见字符。')
    if type(workspace_id) is not int or workspace_id < 0:
        raise ValueError('workspace_id 须为正整数，0 表示个人空间。')
    if not isinstance(fields,list) or not 1 <= len(fields) <= 50:
        raise ValueError('fields 须包含 1–50 个字段。')
    if len(json.dumps(fields,ensure_ascii=False).encode()) > 100000:
        raise ValueError('字段配置超过 100000 字节。')
    normalized, names = [], set()
    for field in fields:
        if not isinstance(field,dict) or set(field) - {'name','type','required','description','options'}:
            raise ValueError('字段使用 name、type、required、description、options。')
        title = field.get('name')
        kind = field.get('type','text')
        if (not isinstance(title,str) or not title.strip() or len(title)>100
                or re.search(r'[.}{`\x00-\x1f]', title) or title.startswith('_') or title in names):
            raise ValueError('字段名须唯一，使用 1–100 字符，避开系统字段及 . } { `。')
        if not isinstance(kind,str) or kind not in TYPES or type(field.get('required',False)) is not bool:
            raise ValueError('字段类型不支持，或 required 未使用布尔值。')
        description = field.get('description','')
        if not isinstance(description,str) or len(description)>4000:
            raise ValueError('字段说明须为 4000 字以内的文本。')
        options = field.get('options',[])
        if kind in ('single-select','multiple-select'):
            if (not isinstance(options,list) or not 1<=len(options)<=100
                    or any(not isinstance(o,str) or not o.strip() or len(o)>100 for o in options)
                    or len(set(options)) != len(options)):
                raise ValueError('选择字段须提供 1–100 个互不重复的文本选项。')
        elif options:
            raise ValueError('仅单选和多选字段使用 options。')
        names.add(title)
        normalized.append({'name':title,'type':kind,'required':field.get('required',False),
                           'description':description,'options':options})
    if normalized[0]['type'] != 'text':
        raise ValueError('首个字段请使用 text 类型。')
    return normalized


def create_collection(name, fields, request_id, workspace_id=0, description='', success_message='提交成功。'):
    fields = validate_fields(name,fields,workspace_id)
    if not isinstance(description,str) or len(description)>10000 or not isinstance(success_message,str) or len(success_message)>2000:
        raise ValueError('说明限 10000 字，提交成功提示限 2000 字。')
    spec = {'name':name,'fields':fields,'workspace_id':workspace_id,'description':description,'success_message':success_message}
    digest = hashlib.sha256(json.dumps(spec,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path = receipt_path(request_id)
    receipt = {'request_id':request_id,'base_name':name,'state':'starting','spec_hash':digest}
    try:
        with path.open('x',encoding='utf-8') as file:
            json.dump(receipt,file,ensure_ascii=False)
    except FileExistsError:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('spec_hash') != digest:
            raise ValueError('此 request_id 已用于另一份配置，请使用新的 request_id。') from None
        return collection_status(request_id)

    def save(stage):
        receipt['state'] = stage
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)

    try:
        account = TableAccount()
        offset = 0
        while True:
            directory = account.list_bases(offset,100)
            if any(b['base_name']==name and (not workspace_id or b['workspace_id']==workspace_id) for b in directory['bases']):
                raise ValueError('已有同名 Base，请选择新的收集表名称。')
            if not directory['has_more']:
                break
            offset = directory['next_offset']
        save('creating_base')
        payload = {'name':name}
        if workspace_id:
            payload['workspace_id'] = workspace_id
        base = json_request('POST',TABLE_URL+'/api/v2.1/dtables/',headers=account.headers,data=payload)['table']
        receipt.update(workspace_id=base['workspace_id'],base_uuid=base['uuid'])
        save('configuring_fields')
        table = Table(workspace_id=base['workspace_id'],base_name=name)
        metadata = table.metadata()['tables'][0]
        table_name = metadata['name']
        receipt.update(table_name=table_name,table_id=metadata['_id'])
        seed_rows = table.rows(table_name,limit=100)['rows']
        if seed_rows and all(not any(v for k,v in row.items() if not k.startswith('_')) for row in seed_rows):
            table.call('DELETE','/rows/',json={'table_name':table_name,'row_ids':[r['_id'] for r in seed_rows]})
        first = metadata['columns'][0]
        if first['name'] != fields[0]['name']:
            table.call('PUT','/columns/',json={'table_name':table_name,'op_type':'rename_column',
                       'column':first['key'],'new_column_name':fields[0]['name']})
        for field in fields[1:]:
            column = {'table_name':table_name,'column_name':field['name'],'column_type':field['type']}
            if field['options']:
                column['column_data'] = {'options':[{'id':uuid.uuid4().hex[:8],'name':option,
                                                     'color':'#46A1FD','textColor':'#FFFFFF'} for option in field['options']]}
            table.call('POST','/columns/',json=column)
        metadata = table.metadata()['tables'][0]
        columns = {c['name']:c for c in metadata['columns']}
        config = {'form_name':name,'table_id':metadata['_id'],
                  'columns':[{'key':columns[f['name']]['key'],'is_required':f['required'],
                              'description':f['description']} for f in fields],
                  'elements_order':[{'key':columns[f['name']]['key'],'type':'column'} for f in fields],
                  'top_remark_option':{'is_top_remark_content_show':bool(description),'top_remark_content':description},
                  'success_message_option':{'is_success_message_show':True,'success_message':success_message}}
        save('creating_form')
        form = json_request('POST',TABLE_URL+'/api/v2.1/forms/',headers=account.headers,
                            data={'workspace_id':base['workspace_id'],'name':name,
                                  'form_id':uuid.uuid4().hex[:4],'form_config':json.dumps(config,ensure_ascii=False)})['form']
        receipt.update(form_token=form['token'],form_url=TABLE_URL+'/dtable/forms/'+str(uuid.UUID(form['token']))+'/')
        save('publishing')
        json_request('POST',TABLE_URL+f'/api/v2.1/forms/{form["token"]}/share/',
                     headers=account.headers,json={'share_type':'anonymous','group_ids':[]})
        save('checking_public_access')
        with httpx.Client(timeout=30,follow_redirects=False) as client:
            _, html = page_get(client,receipt['form_url'],'table.nju.edu.cn')
        published = json.loads(js_string(html,'formConfig') or '{}')
        if published.get('table_id') != metadata['_id'] or len(published.get('columns',[])) != len(fields):
            raise ValueError('公开填写页面尚未返回完整字段。')
        receipt.update(anonymous_access_verified=True,fields=fields)
        save('published')
    except Exception as exc:
        receipt['failed_stage'] = receipt['state']
        if isinstance(exc,ValueError):
            receipt['error'] = str(exc)
        save('needs_check')
        raise ValueError(f'收集表操作待核对：request_id={request_id}，阶段={receipt["failed_stage"]}。'
                         '先调用 nju_table_collection_status 获取已创建的资源；同一 request_id 不会重复创建。') from None
    return collection_status(request_id)
