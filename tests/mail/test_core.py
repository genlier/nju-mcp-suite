import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mail_bridge as bridge
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class MailTests(unittest.TestCase):
    def test_header_injection(self):
        with self.assertRaises(ValueError):
            bridge.create_draft(['a@example.com'], 'hello\r\nBcc: b@example.com', 'body')
        with self.assertRaises(ValueError):
            bridge.addresses(['a@example.com\nBcc:b@example.com'])

    def test_duplicate_send_blocked(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, 'ROOT', Path(tmp)), patch.object(bridge, 'config', return_value={'email':'me@smail.nju.edu.cn'}), patch.object(bridge, 'account', return_value=({'email':'me@smail.nju.edu.cn','smtp_host':'smtp.example.com','smtp_port':465},'fake')), patch.object(bridge.smtplib, 'SMTP_SSL') as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            draft = bridge.create_draft(['a@example.com'], '测试', '正文')
            result = bridge.send_draft(draft['draft_id'])
            self.assertEqual(result['state'], 'accepted')
            with self.assertRaises(ValueError):
                bridge.send_draft(draft['draft_id'])
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 1)

    def test_ambiguous_send_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, 'ROOT', Path(tmp)), patch.object(bridge, 'config', return_value={'email':'me@smail.nju.edu.cn'}), patch.object(bridge, 'account', return_value=({'email':'me@smail.nju.edu.cn','smtp_host':'smtp.example.com','smtp_port':465},'fake')), patch.object(bridge.smtplib, 'SMTP_SSL', side_effect=TimeoutError):
            draft = bridge.create_draft(['a@example.com'], 'test', 'body')
            with self.assertRaises(ValueError):
                bridge.send_draft(draft['draft_id'])
            with bridge.database() as db:
                self.assertEqual(db.execute('SELECT state FROM drafts').fetchone()[0], 'unknown')
            with self.assertRaises(ValueError):
                bridge.send_draft(draft['draft_id'])
