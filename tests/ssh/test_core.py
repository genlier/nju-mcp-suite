import asyncio
import contextlib
import json
import logging
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import paramiko
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import ssh_backend as backend
import server

logging.getLogger('paramiko').setLevel(logging.CRITICAL)


class DemoSSH(paramiko.ServerInterface):
    def __init__(self,mode):
        self.mode=mode

    def check_auth_password(self,username,password):
        return paramiko.AUTH_SUCCESSFUL if (username,password)==('test','synthetic-password') else paramiko.AUTH_FAILED

    def get_allowed_auths(self,username):
        return 'password'

    def check_channel_request(self,kind,channel_id):
        return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self,channel,command):
        def output():
            try:
                time.sleep(0.05)
                if self.mode=='timeout':
                    time.sleep(1.5)
                channel.sendall(b'x'*300000 if self.mode=='large' else b'hello\n')
                channel.sendall_stderr(b'e'*300000 if self.mode=='large' else b'notice\n')
                channel.send_exit_status(7 if self.mode=='normal' else 0)
            except (OSError,EOFError):
                pass
            finally:
                channel.close()
        threading.Thread(target=output,daemon=True).start()
        return True


@contextlib.contextmanager
def fixture(mode='normal',wrong_key=False):
    listener=socket.socket()
    listener.bind(('127.0.0.1',0))
    listener.listen(1)
    listener.settimeout(5)
    port=listener.getsockname()[1]
    key=paramiko.RSAKey.generate(2048)
    running=threading.Event()
    def serve():
        transport=None
        try:
            conn,_=listener.accept()
            transport=paramiko.Transport(conn)
            transport.add_server_key(key)
            transport.start_server(server=DemoSSH(mode))
            running.wait(5)
        except (OSError,paramiko.SSHException,EOFError):
            pass
        finally:
            if transport:
                transport.close()
    thread=threading.Thread(target=serve,daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory() as tmp:
        hosts=paramiko.HostKeys()
        pin=paramiko.RSAKey.generate(2048) if wrong_key else key
        hosts.add(f'[127.0.0.1]:{port}',pin.get_name(),pin)
        hosts.save(str(Path(tmp)/'known_hosts'))
        cfg={'host':'127.0.0.1','port':port,'username':'test'}
        try:
            with patch.object(backend,'ROOT',Path(tmp)):
                yield cfg
        finally:
            running.set()
            listener.close()
            thread.join(timeout=3)


class SSHTests(unittest.TestCase):
    def test_password_and_output(self):
        with fixture() as cfg, backend.connect(cfg,'synthetic-password') as client:
            result=backend.execute(client,'sample')
            self.assertEqual(result['exit_code'],7)
            self.assertEqual(result['stdout'],'hello\n')
            self.assertEqual(result['stderr'],'notice\n')

    def test_large_output_drains_both_streams(self):
        with fixture('large') as cfg, backend.connect(cfg,'synthetic-password') as client:
            result=backend.execute(client,'sample',max_output_bytes=4096)
            self.assertTrue(result['truncated'])
            self.assertLessEqual(len(result['stdout'])+len(result['stderr']),4096)
            self.assertEqual(result['exit_code'],0)

    def test_timeout_reports_unknown_remote_state(self):
        with fixture('timeout') as cfg, backend.connect(cfg,'synthetic-password') as client:
            result=backend.execute(client,'sample',timeout_seconds=1)
            self.assertTrue(result['timed_out'])
            self.assertIsNone(result['exit_code'])
            self.assertIn('unknown',result['remote_process_state'])

    def test_host_key_mismatch_rejected(self):
        with fixture(wrong_key=True) as cfg:
            with self.assertRaisesRegex(ValueError,'主机密钥'):
                with backend.connect(cfg,'synthetic-password'):
                    pass

    def test_authentication_failure(self):
        with fixture() as cfg:
            with self.assertRaisesRegex(ValueError,'认证失败'):
                with backend.connect(cfg,'wrong-synthetic-password'):
                    pass

    def test_local_upload_scope(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server,'ROOT',Path(tmp)):
            outside=Path(tmp)/'private.txt'
            outside.write_text('test')
            with self.assertRaises(ValueError):
                server.cloud_ssh_upload(str(outside),'/tmp/output.txt')
