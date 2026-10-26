import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import collection_forms as c

UUID = '12345678-1234-1234-1234-123456789abc'
FIELDS = [{'name':'称呼','type':'text'}, {'name':'组别','type':'single-select','required':True,'options':['A','B']}]


class CollectionTests(unittest.TestCase):
    def test_invalid_fields_fail_before_writes(self):
        with patch.object(c,'json_request') as api:
            for fields in ([], [{'name':'x','type':'file'}], [{'name':'x','type':'number'}],
                           [{'name':'x'},{'name':'x'}], [{'name':'x'},{'name':'y','type':'single-select','options':['A','A']}],
                           [{'name':'x','required':'yes'}], [{'name':'x','type':[]}], [{'name':'_id'}]):
                with self.assertRaises(ValueError):
                    c.create_collection('Test',fields,'request')
            api.assert_not_called()

    def test_publish_and_repeat_returns_same_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c,'ROOT',Path(tmp)), \
                patch.object(c,'TableAccount') as account, patch.object(c,'Table') as factory, \
                patch.object(c,'json_request') as api, patch.object(c,'page_get') as page:
            account.return_value.headers = {'Authorization':'synthetic'}
            account.return_value.list_bases.return_value = {'bases':[],'has_more':False}
            before = {'_id':'0000','name':'Table1','columns':[{'name':'Name','key':'0000'}]}
            after = {'_id':'0000','name':'Table1','columns':[{'name':'称呼','key':'0000'},{'name':'组别','key':'select'}]}
            table = factory.return_value
            table.metadata.side_effect = [{'tables':[before]},{'tables':[after]}]
            table.rows.return_value = {'rows':[{'_id':'blank','Name':None}]}
            api.side_effect = [{'table':{'workspace_id':1,'uuid':UUID}}, {'form':{'token':UUID}}, {'success':True}]
            page.return_value = ('https://table.nju.edu.cn/', 'formConfig: \'' + json.dumps({'table_id':'0000','columns':[{},{}]}) + "'")
            result = c.create_collection('Test',FIELDS,'same-id')
            self.assertEqual(result['state'],'published')
            self.assertTrue(result['anonymous_access_verified'])
            self.assertNotIn('synthetic',json.dumps(result))
            first_calls = api.call_count
            self.assertEqual(c.create_collection('Test',FIELDS,'same-id'),result)
            self.assertEqual(api.call_count,first_calls)
            with self.assertRaises(ValueError):
                c.create_collection('Different',FIELDS,'same-id')
            self.assertEqual(api.call_count,first_calls)
            calls = table.call.call_args_list
            self.assertEqual(calls[0].args,('DELETE','/rows/'))
            self.assertEqual(calls[-1].kwargs['json']['column_data']['options'][0]['name'],'A')
            self.assertEqual(api.call_args.kwargs['json']['share_type'],'anonymous')

    def test_interruption_retains_resource_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c,'ROOT',Path(tmp)), \
                patch.object(c,'TableAccount') as account, patch.object(c,'Table',side_effect=ValueError('interrupted')), \
                patch.object(c,'json_request',return_value={'table':{'workspace_id':1,'uuid':UUID}}) as api:
            account.return_value.list_bases.return_value = {'bases':[],'has_more':False}
            with self.assertRaisesRegex(ValueError,'request_id=interrupted'):
                c.create_collection('Test',FIELDS,'interrupted')
            saved = c.collection_status('interrupted')
            self.assertEqual(saved['base_uuid'],UUID)
            self.assertEqual(saved['state'],'needs_check')
            self.assertEqual(saved['failed_stage'],'configuring_fields')
            self.assertEqual(c.create_collection('Test',FIELDS,'interrupted'),saved)
            self.assertEqual(api.call_count,1)


if __name__ == '__main__':
    unittest.main()
