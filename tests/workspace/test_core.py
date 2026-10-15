import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import connections as c
import server
import setup

BASE_UUID = 'a77ce14a-0aa0-41a8-92c7-ccdc8a78be0a'


class IntegrationTests(unittest.TestCase):
    def test_dav_unicode_and_children(self):
        data = b'''<multistatus xmlns="DAV:">
          <response><href>/seafdav/</href><propstat><status>HTTP/1.1 200 OK</status><prop><resourcetype><collection/></resourcetype></prop></propstat></response>
          <response><href>/seafdav/%E8%B5%84%E6%96%99/</href><propstat><status>HTTP/1.1 200 OK</status><prop><resourcetype><collection/></resourcetype></prop></propstat></response>
          <response><href>/seafdav/a.txt</href><propstat><status>HTTP/1.1 200 OK</status><prop><getcontentlength>12</getcontentlength><getetag>v1</getetag></prop></propstat></response>
          <response><href>https://evil.example/seafdav/injected</href><propstat><status>HTTP/1.1 200 OK</status><prop/></propstat></response>
          <response><href>/seafdav/nested/deep</href><propstat><status>HTTP/1.1 200 OK</status><prop/></propstat></response>
        </multistatus>'''
        with patch.object(c, 'request', return_value=(207,data,{})):
            result = c.Box('test-user','test-password').list('/',limit=1)
            self.assertEqual(result['total'],2)
            self.assertEqual(result['items'][0]['path'],'/资料/')
            self.assertTrue(result['has_more'])

    def test_dav_path_and_upload_scope(self):
        for path in ('https://example.org/', '/a/../b', '/a\\b', '/a\r\n'):
            with self.assertRaises(ValueError):
                c.box_url(path)
        with tempfile.TemporaryDirectory() as tmp, patch.object(server,'ROOT',Path(tmp)):
            outside = Path(tmp)/'private.txt'
            outside.write_text('test')
            with self.assertRaises(ValueError):
                server.box_upload(str(outside),'/x.txt')

    def test_dav_create_precondition(self):
        with patch.object(c,'request',return_value=(201,b'',{})) as request:
            c.Box('test','test').put('/a.txt',b'abc')
            self.assertEqual(request.call_args.kwargs['headers'], {'If-None-Match':'*'})

    def test_redirect_never_forwards_credentials(self):
        seen = []
        def handler(req):
            seen.append(req.url.host)
            return httpx.Response(302, headers={'location':'https://evil.example/'})
        client = httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=False)
        with patch.object(c.httpx,'Client',return_value=client):
            with self.assertRaisesRegex(ValueError,'HTTP 302'):
                c.request('GET',c.BOX_URL,auth=httpx.BasicAuth('test','test'))
        self.assertEqual(seen,['box.nju.edu.cn'])

    def test_response_limit(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'123456')))
        with patch.object(c.httpx,'Client',return_value=client):
            with self.assertRaises(ValueError):
                c.request('GET',c.TABLE_URL,max_bytes=5)

    def test_table_gateway_write_and_validation(self):
        calls = []
        def api(method,url,**kwargs):
            calls.append((method,url,kwargs))
            if 'app-access-token' in url:
                return {'dtable_uuid':BASE_UUID,'access_token':'synthetic','use_api_gateway':True}
            if url.endswith('/metadata/'):
                return {'metadata':{'tables':[{'name':'Sheet','columns':[{'name':'Name','type':'text'},{'name':'Total','type':'formula'}]}]}}
            if method=='GET':
                return {'rows':[{'_id':'a'},{'_id':'b'}]}
            return {'success':True}
        with patch.object(c,'json_request',side_effect=api):
            table = c.Table('test',token='synthetic')
            result = table.rows('Sheet',limit=1)
            self.assertTrue(result['has_more'])
            self.assertEqual(result['next_offset'],1)
            for column in ('Unknown','Total'):
                with self.assertRaises(ValueError):
                    table.append('Sheet',{column:1})
            self.assertFalse(any(method=='POST' for method,_,_ in calls))
            table.update('Sheet','row123',{'Name':'updated'})
            method,url,kwargs = calls[-1]
            self.assertEqual(method,'PUT')
            self.assertEqual(kwargs['json']['updates'],[{'row_id':'row123','row':{'Name':'updated'}}])

    def test_table_legacy_host_guard(self):
        with patch.object(c,'json_request',return_value={'dtable_uuid':BASE_UUID,'access_token':'synthetic','dtable_server':'https://evil.example/dtable-server/'}):
            with self.assertRaises(ValueError):
                c.Table('test',token='synthetic')

    def test_account_directory_shared_dedup_and_paging(self):
        directory = {'workspace_list':[
            {'id':'', 'type':'starred', 'table_list':[{'workspace_id':20,'name':'Shared'}]},
            {'id':'', 'type':'shared', 'shared_table_list':[{'workspace_id':20,'name':'Shared','permission':'r'}], 'shared_view_list':[{'view_id':'view'}]},
            {'id':10, 'name':'personal','table_list':[{'name':'研究 / A?#'}]},
            {'id':30, 'name':'group','group_shared_dtables':[{'workspace_id':40,'name':'Team Base'}]}
        ]}
        with patch.object(c,'json_request',return_value=directory) as api:
            result = c.TableAccount('account-synthetic').list_bases(limit=1)
            self.assertEqual(result['total'],3)
            self.assertEqual(result['bases'][0]['base_name'],'研究 / A?#')
            self.assertEqual(result['bases'][0]['workspace_id'],10)
            self.assertEqual(result['next_offset'],1)
            self.assertEqual(result['view_only_shares'],1)
            self.assertNotIn('account-synthetic',json.dumps(result))
            self.assertEqual(api.call_args.kwargs['headers']['Authorization'],'Bearer account-synthetic')

    def test_account_base_selection_and_permission_denied(self):
        calls = []
        def api(method,url,**kwargs):
            calls.append((method,url,kwargs))
            if url.endswith('/temp-api-token/'):
                return {'api_token':'temporary-synthetic'}
            if url.endswith('/app-access-token/'):
                return {'dtable_uuid':BASE_UUID,'access_token':'base-synthetic','use_api_gateway':True}
            if url.endswith('/metadata/'):
                return {'metadata':{'tables':[{'name':'Sheet','columns':[{'name':'Name','type':'text'}]}]}}
            raise ValueError('HTTP 403：没有权限')
        with patch.object(c,'config',return_value={'table_account':{'configured':True}}), patch.object(c,'secret',return_value='account-synthetic') as credential, patch.object(c,'json_request',side_effect=api):
            table = c.Table(workspace_id=10,base_name='研究 / A?#')
            self.assertIn('/10/dtable/%E7%A0%94%E7%A9%B6%20%2F%20A%3F%23/temp-api-token/',calls[0][1])
            self.assertEqual(calls[1][2]['headers']['Authorization'],'Bearer temporary-synthetic')
            self.assertEqual(table.headers['Authorization'],'Bearer base-synthetic')
            with self.assertRaisesRegex(ValueError,'403'):
                table.update('Sheet','row1',{'Name':'test'})
            self.assertEqual(sum(method=='PUT' for method,_,_ in calls),1)
            self.assertEqual(credential.call_args.args,('table-account',))
            calls.clear()
            with patch.object(c,'json_request',side_effect=ValueError('HTTP 403')) as denied:
                with self.assertRaisesRegex(ValueError,'403'):
                    c.Table(workspace_id=10,base_name='Other')
                self.assertEqual(denied.call_count,1)

    def test_account_invalid_target_and_unconfigured(self):
        with patch.object(c,'config',return_value={}):
            with self.assertRaisesRegex(ValueError,'table-account'):
                c.TableAccount()
        with patch.object(c,'json_request') as api:
            account = c.TableAccount('synthetic')
            for wid,name in [(0,'Base'),(-1,'Base'),(1,''),(1,'..'),(True,'Base')]:
                with self.assertRaises(ValueError):
                    account.base_token(wid,name)
            api.assert_not_called()

    def test_account_setup_preserves_bases_and_saves_only_token(self):
        cfg = {'table_bases':{'existing':{'name':'Original'}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(setup,'ROOT',Path(tmp)), patch.object(setup,'config',return_value=cfg), patch.object(setup.keyring,'get_keyring',return_value=setup.WinVaultKeyring()), patch.object(setup.keyring,'set_password') as save, patch('sys.argv',['setup.py','table-account']), patch('builtins.input',side_effect=['2']), patch.object(setup.getpass,'getpass',return_value='account-synthetic'), patch.object(c.TableAccount,'list_bases',return_value={'total':2}):
            setup.main()
            persisted = (Path(tmp)/'config.json').read_text(encoding='utf-8')
            self.assertNotIn('account-synthetic',persisted)
            self.assertEqual(json.loads(persisted)['table_bases'],cfg['table_bases'])
            save.assert_called_once_with(c.SERVICE,'table-account','account-synthetic')
        with patch.object(setup,'config',return_value=cfg), patch.object(setup.keyring,'get_keyring',return_value=setup.WinVaultKeyring()), patch.object(setup.keyring,'set_password') as save, patch('sys.argv',['setup.py','table-account']), patch('builtins.input',return_value='2'), patch.object(setup.getpass,'getpass',return_value='wrong-synthetic'), patch.object(c.TableAccount,'list_bases',side_effect=ValueError('HTTP 401')):
            with self.assertRaisesRegex(ValueError,'401'):
                setup.main()
            save.assert_not_called()
