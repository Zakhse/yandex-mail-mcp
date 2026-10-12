#!/usr/bin/env python3
"""Integration tests for a supplied upstream binary, synthetic loopback IMAP only.
Run: python3 tests/test_upstream.py --binary /absolute/path/to/mail-mcp
No operator environment, .env or real mailbox credentials are inherited.
"""
import argparse
import base64
from email.message import EmailMessage
from email.policy import SMTP
import json
from pathlib import Path
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

ATTACHMENT = b'Synthetic attachment; no real mail or personal data.\n'
msg = EmailMessage()
msg['From'] = 'sender@example.invalid'
msg['To'] = 'reader@example.invalid'
msg['Subject'] = 'Synthetic fixture'
msg['Date'] = 'Mon, 12 Oct 2026 10:00:00 +0000'
msg['Message-ID'] = '<fixture@example.invalid>'
msg.set_content('Synthetic message body.')
msg.add_attachment(ATTACHMENT, maintype='application', subtype='octet-stream', filename='fixture.bin')
RAW = msg.as_bytes(policy=SMTP)


class FakeIMAP(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), IMAPHandler)
        self.commands = []
        self.failures = []


class IMAPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        def send(data):
            self.wfile.write(data)
            self.wfile.flush()
        send(b'* OK [CAPABILITY IMAP4rev1] Synthetic server\r\n')
        while line := self.rfile.readline():
            tag, _, command = line.strip().partition(b' ')
            upper = command.upper()
            self.server.commands.append(upper)
            ok = tag + b' OK completed\r\n'
            if upper.startswith(b'LOGIN '):
                send(ok)
            elif upper == b'CAPABILITY':
                send(b'* CAPABILITY IMAP4rev1\r\n' + ok)
            elif upper.startswith(b'LIST '):
                send(b'* LIST (\\HasNoChildren) "/" "INBOX"\r\n' + ok)
            elif upper.startswith(b'EXAMINE '):
                send(b'* FLAGS (\\Seen)\r\n* 1 EXISTS\r\n* 0 RECENT\r\n'
                     b'* OK [UIDVALIDITY 1]\r\n' + tag + b' OK [READ-ONLY] examined\r\n')
            elif upper.startswith(b'UID SEARCH '):
                send(b'* SEARCH 1\r\n' + ok)
            elif upper.startswith(b'UID FETCH ') and b'BODY' in upper:
                if b'HEADER.FIELDS' in upper:
                    body = RAW.split(b'\r\n\r\n')[0] + b'\r\n\r\n'
                    key = b'BODY[HEADER.FIELDS (DATE FROM TO CC SUBJECT)]'
                else:
                    body, key = RAW, b'BODY[]'
                send(b'* 1 FETCH (UID 1 FLAGS () ' + key + b' {' + str(len(body)).encode() +
                     b'}\r\n' + body + b')\r\n' + ok)
            elif upper.startswith(b'UID FETCH '):
                send(b'* 1 FETCH (UID 1 FLAGS ())\r\n' + ok)
            elif upper == b'LOGOUT':
                send(b'* BYE\r\n' + ok)
                break
            elif upper == b'NOOP':
                send(ok)
            else:
                self.server.failures.append(upper)
                send(tag + b' BAD unsupported synthetic command\r\n')


def spare_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class UpstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mail-mcp-synthetic-')
        cls.imap = FakeIMAP()
        threading.Thread(target=cls.imap.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{spare_port()}/mcp'
        port = cls.url.split(':')[-1].split('/')[0]
        env = {
            'PATH': '/usr/bin:/bin', 'RUST_LOG': 'error',
            'MAIL_MCP_TRANSPORT': 'http', 'MAIL_MCP_HTTP_HOST': '127.0.0.1',
            'MAIL_MCP_HTTP_PORT': port, 'MAIL_MCP_HTTP_PATH': '/mcp',
            'MAIL_IMAP_DEFAULT_HOST': '127.0.0.1',
            'MAIL_IMAP_DEFAULT_PORT': str(cls.imap.server_address[1]),
            'MAIL_IMAP_DEFAULT_SECURE': 'false',  # Synthetic loopback only.
            'MAIL_IMAP_DEFAULT_USER': 'fixture', 'MAIL_IMAP_DEFAULT_PASS': 'synthetic',
            'MAIL_IMAP_WRITE_ENABLED': 'false', 'MAIL_SMTP_WRITE_ENABLED': 'false',
            'MAIL_ATTACHMENT_DOWNLOAD_DIR': cls.temp.name + '/attachments',
            'MAIL_IMAP_CONNECT_TIMEOUT_MS': '1000', 'MAIL_IMAP_SOCKET_TIMEOUT_MS': '1000',
        }
        cls.process = subprocess.Popen([BINARY], cwd=cls.temp.name, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                cls.info = cls.rpc('initialize', {
                    'protocolVersion': '2025-03-26', 'capabilities': {},
                    'clientInfo': {'name': 'synthetic-test', 'version': '1'},
                })['result']
                return
            except (OSError, ValueError):
                time.sleep(.1)
        cls.tearDownClass()
        raise RuntimeError('Upstream did not start within six seconds')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.imap.shutdown()
        cls.imap.server_close()
        cls.temp.cleanup()

    @classmethod
    def rpc(cls, method, params):
        request = urllib.request.Request(cls.url,
            data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode(),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
        with urllib.request.urlopen(request, timeout=5) as response:
            data = response.read().decode()
        if not data.lstrip().startswith('{'):
            data = '\n'.join(x[6:] for x in data.splitlines() if x.startswith('data: '))
        return json.loads(data)

    @classmethod
    def tool(cls, name, arguments):
        r = cls.rpc('tools/call', {'name': name, 'arguments': arguments})
        if 'error' in r:
            return r
        return r['result']

    @staticmethod
    def payload(r):
        if 'structuredContent' in r:
            p = r['structuredContent']
        else:
            p = json.loads(next(x['text'] for x in r['content'] if x['type'] == 'text'))
        return p.get('data', p)

    def test_http_initialization_and_discovery(self):
        self.assertEqual(self.info['serverInfo']['version'], '0.4.16')
        tools = self.rpc('tools/list', {})['result']['tools']
        names = {x['name'] for x in tools}
        self.assertTrue({'imap_search_messages', 'imap_get_message', 'imap_get_attachment'} <= names)
        # Upstream write gates do not hide tools from discovery.
        self.assertIn('smtp_send_message', names)

    def test_folder_listing(self):
        p = self.payload(self.tool('imap_list_mailboxes', {}))
        self.assertIn('INBOX', json.dumps(p))

    def test_search_and_read_do_not_select_readwrite(self):
        p = self.payload(self.tool('imap_search_messages', {'mailbox': 'INBOX', 'limit': 1}))
        self.assertIn('imap:default:INBOX:1:1', json.dumps(p))
        p = self.payload(self.tool('imap_get_message', {'message_id': 'imap:default:INBOX:1:1'}))
        self.assertIn('Synthetic message body.', json.dumps(p))
        self.assertTrue(any(x.startswith(b'EXAMINE ') for x in self.imap.commands))
        self.assertTrue(any(b'BODY.PEEK[]' in x for x in self.imap.commands))
        self.assertFalse(any(x.startswith(b'SELECT ') or b'STORE' in x for x in self.imap.commands))
        self.assertEqual(self.imap.failures, [])

    def test_attachment_base64_and_file_match(self):
        p = self.payload(self.tool('imap_get_attachment', {
            'message_id': 'imap:default:INBOX:1:1', 'filename': 'fixture.bin', 'include_base64': True,
        }))
        self.assertEqual(p['status'], 'ok')
        self.assertEqual(base64.b64decode(p['content_base64']), ATTACHMENT)
        self.assertEqual(Path(p['file_path']).read_bytes(), ATTACHMENT)
        self.assertTrue(Path(p['file_path']).is_relative_to(Path(self.temp.name)))

    def test_attachment_size_limit_is_explicit(self):
        p = self.payload(self.tool('imap_get_attachment', {
            'message_id': 'imap:default:INBOX:1:1', 'filename': 'fixture.bin',
            'include_base64': True, 'max_inline_bytes': 1,
        }))
        self.assertIsNone(p['content_base64'])
        self.assertIn('exceeds', p['base64_omitted_reason'])

    def test_readonly_rejects_imap_and_smtp_before_network(self):
        names = {x['name']: x for x in self.rpc('tools/list', {})['result']['tools']}
        self.assertIn('imap_delete_message', names)
        count = len(self.imap.commands)
        r = self.tool('imap_delete_message', {'message_id': 'imap:default:INBOX:1:1', 'confirm': True})
        self.assertIn('disabled', json.dumps(r).lower())
        r = self.tool('smtp_send_message', {
            'to': ['recipient@example.invalid'], 'subject': 'Synthetic', 'body_text': 'Synthetic',
        })
        self.assertIn('disabled', json.dumps(r).lower())
        self.assertEqual(len(self.imap.commands), count)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True, help='Checksum-verified upstream executable')
    args, remaining = parser.parse_known_args()
    BINARY = str(Path(args.binary).resolve(strict=True))
    unittest.main(argv=[__file__, *remaining])
