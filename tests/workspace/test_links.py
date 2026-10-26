import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import links


URL = 'https://table.nju.edu.cn/external-apps/12345678-1234-1234-1234-123456789abc/'
BOX = 'https://box.nju.edu.cn/u/d/0123456789abcdef0123/'


class LinkTests(unittest.TestCase):
    def test_host_and_redirect_guards(self):
        for url in ('http://box.nju.edu.cn/u/d/0123456789abcdef0123/',
                    'https://box.nju.edu.cn.evil.example/u/d/0123456789abcdef0123/',
                    'https://me@box.nju.edu.cn/u/d/0123456789abcdef0123/',
                    BOX + '?url=https://evil.example'):
            with self.assertRaises(ValueError):
                links.BoxUploadLink(url)
        seen = []
        def handler(req):
            seen.append(req.url.host)
            return httpx.Response(302, headers={'location':'https://evil.example/'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ValueError):
                links.page_get(client, BOX, 'box.nju.edu.cn')
        self.assertEqual(seen, ['box.nju.edu.cn'])

    def test_django_bootstrap_strings(self):
        self.assertEqual(links.js_string(r"appConfig: '{\u0022name\u0022:\u0022报名\u0022}'", 'appConfig'), '{"name":"报名"}')
        self.assertEqual(links.js_string('dirName: "a\\\"b"', 'dirName'), 'a"b')

    def fixture(self):
        link = links.TableLink(URL)
        link.needs_login = False
        link.name = 'Test'
        link.current_user = {'name':'Test User', 'id':'12345'}
        link.settings = {'pages':[{'id':'form','type':'form','table_id':'0000','columns':[
            {'key':'id','is_required':True,'enable_fill_default_value':True,'default_value':'{creator.id}','enable_not_change_default_value':True},
            {'key':'text','custom_name':'显示名','is_required':True},
            {'key':'select','is_required':True}, {'key':'long'}, {'key':'number'}]}]}
        link.tables = [{'_id':'0000','columns':[
            {'key':'id','name':'学号','type':'text'},
            {'key':'text','name':'原始列名','type':'text'},
            {'key':'select','name':'选择','type':'single-select','data':{'options':[{'id':'s','name':'A'}]}},
            {'key':'long','name':'经历','type':'long-text'},
            {'key':'number','name':'数值','type':'number'}]}]
        return link

    def test_form_validation_and_wire_payload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(links,'ROOT',Path(tmp)), patch.object(links,'table_cookies',return_value={}):
            link = self.fixture()
            with patch.object(link,'open',side_effect=lambda:link.describe()):
                for values in ({'显示名':'  ','选择':'A'}, {'显示名':'x','选择':'unknown'},
                               {'显示名':'x','选择':'A','学号':'forged'},
                               {'显示名':'x','选择':'A','数值':float('inf')}):
                    with self.assertRaises(ValueError):
                        link.prepare('form',values)
                prepared = link.prepare('form',{'显示名':' x ','选择':'A','经历':'经历文字'})
                draft = json.loads((Path(tmp)/'form-drafts'/(prepared['draft_id']+'.json')).read_text(encoding='utf-8'))
                self.assertEqual(draft['row_data']['原始列名'],'x')
                self.assertNotIn('显示名',draft['row_data'])
                self.assertEqual(draft['row_data']['学号'],'12345')
                self.assertEqual(draft['row_data']['经历']['text'],'经历文字')
                self.assertEqual(draft['row_data']['选择'],'A')

    def test_submit_timeout_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(links,'ROOT',Path(tmp)), patch.object(links,'table_cookies',return_value={}):
            link = self.fixture()
            with patch.object(link,'open',side_effect=lambda:link.describe()):
                draft = link.prepare('form',{'显示名':'x','选择':'A'})
                with patch.object(links,'TableLink',return_value=link), patch.object(link,'call',side_effect=ValueError('timeout')) as api:
                    with self.assertRaises(ValueError):
                        links.submit_draft(draft['draft_id'])
                    with self.assertRaises(ValueError):
                        links.submit_draft(draft['draft_id'])
                    self.assertEqual(api.call_count,1)

    def test_partial_draft_cannot_be_submitted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(links,'ROOT',Path(tmp)), patch.object(links,'table_cookies',return_value={}):
            link = self.fixture()
            with patch.object(link,'open',side_effect=lambda:link.describe()):
                draft = link.prepare('form',{'显示名':'x'},allow_partial=True)
            self.assertEqual(draft['state'],'incomplete')
            self.assertEqual(draft['missing_fields'],['选择'])
            with patch.object(links,'TableLink') as factory:
                with self.assertRaisesRegex(ValueError,'尚未补齐'):
                    links.submit_draft(draft['draft_id'])
                factory.assert_not_called()

    def test_stale_schema_and_file_scope(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(links,'ROOT',Path(tmp)), patch.object(links,'table_cookies',return_value={}):
            link = self.fixture()
            with patch.object(link,'open',side_effect=lambda:link.describe()):
                draft = link.prepare('form',{'显示名':'x','选择':'A'})
                link.settings['pages'][0]['columns'][1]['is_required'] = False
                with patch.object(links,'TableLink',return_value=link), patch.object(link,'call') as api:
                    with self.assertRaises(ValueError):
                        links.submit_draft(draft['draft_id'])
                    api.assert_not_called()
            outside = Path(tmp)/'outside.txt'
            outside.write_text('test')
            with self.assertRaises(ValueError):
                links.BoxUploadLink(BOX).upload(str(outside))


if __name__ == '__main__':
    unittest.main()
