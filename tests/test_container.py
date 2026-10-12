#!/usr/bin/env python3
"""Exercise the actual one-container image with networking disabled.
Uses invented credentials. HTTP tests replace the connector with a sleeping
process; actual upstream binaries are checked separately. No real mail server
is contacted. Requires a built image and a local Docker daemon.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid


class ContainerTests(unittest.TestCase):
    @classmethod
    def docker(cls, *args):
        return subprocess.run([*DOCKER, *args], capture_output=True, text=True, timeout=15)

    @classmethod
    def setUpClass(cls):
        cls.name = 'mail-mcp-offline-' + uuid.uuid4().hex[:12]
        work = Path('work').resolve()
        work.mkdir(exist_ok=True, mode=0o700)
        cls.temp = tempfile.TemporaryDirectory(prefix='mail-container-synthetic-', dir=work)
        fixture = Path(cls.temp.name) / 'tunnel-double.sh'
        fixture.write_text('#!/bin/sh\nexec sleep 300\n')
        fixture.chmod(0o555)
        token = base64.b64encode(json.dumps({
            'a': '0' * 32, 't': str(uuid.UUID(int=0)),
            's': base64.b64encode(bytes(32)).decode(),
        }).encode()).decode()
        r = cls.docker('run', '-d', '--name', cls.name, '--network', 'none',
                       '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777',
                       '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                       '--memory', '256m', '-e', 'MAIL_IMAP_DEFAULT_USER=fixture',
                       '-e', 'MAIL_IMAP_DEFAULT_PASS=synthetic', '-e', 'TUNNEL_TOKEN=' + token,
                       '-e', 'MAIL_IMAP_WRITE_ENABLED=true', '-e', 'MAIL_SMTP_WRITE_ENABLED=true',
                       '--mount', f'type=bind,src={fixture},dst=/test-cloudflared,readonly',
                       IMAGE, '/mail-mcp', '/test-cloudflared')
        if r.returncode:
            cls.docker('rm', '-f', cls.name)
            cls.temp.cleanup()
            raise RuntimeError('Could not start offline test container; private Docker output withheld')
        for _ in range(60):
            try:
                cls.info = cls.rpc('initialize', {
                    'protocolVersion': '2025-03-26', 'capabilities': {},
                    'clientInfo': {'name': 'offline-image-test', 'version': '1'},
                })['result']
                return
            except (ValueError, KeyError, RuntimeError):
                time.sleep(.1)
        logs = cls.docker('logs', cls.name)
        Path('work/offline-container.log').write_text(logs.stdout + logs.stderr)
        cls.tearDownClass()
        raise RuntimeError('MCP did not start in offline container; synthetic diagnostics saved to work/')

    @classmethod
    def tearDownClass(cls):
        cls.docker('rm', '-f', cls.name)
        cls.temp.cleanup()

    @classmethod
    def rpc(cls, method, params):
        payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        r = cls.docker('exec', cls.name, 'wget', '-q', '-O', '-',
                       '--header=Content-Type: application/json',
                       '--header=Accept: application/json, text/event-stream',
                       '--post-data=' + payload, 'http://127.0.0.1:8000/mcp')
        if r.returncode:
            raise RuntimeError('Offline MCP HTTP request failed')
        text = r.stdout
        if not text.lstrip().startswith('{'):
            text = '\n'.join(x[6:] for x in text.splitlines() if x.startswith('data: '))
        return json.loads(text)

    def test_mail_and_cloudflared_binaries_and_version(self):
        self.assertEqual(self.info['serverInfo']['version'], '0.4.16')
        r = self.docker('exec', self.name, 'sh', '-c', 'pidof mail-mcp >/dev/null && /usr/local/bin/cloudflared version')
        self.assertEqual(r.returncode, 0)
        self.assertIn('2026.10.0', r.stdout)

    def test_isolation_and_defaults(self):
        r = self.docker('inspect', '--format', '{{json .HostConfig}}', self.name)
        cfg = json.loads(r.stdout)
        self.assertTrue(cfg['ReadonlyRootfs'])
        self.assertEqual(cfg['NetworkMode'], 'none')
        self.assertFalse(cfg['PortBindings'])
        self.assertEqual(cfg['Memory'], 256 * 1024 * 1024)
        r = self.docker('exec', self.name, 'id', '-u')
        self.assertEqual(r.stdout.strip(), '65532')

    def test_http_discovery_and_write_refusal(self):
        tools = self.rpc('tools/list', {})['result']['tools']
        self.assertIn('imap_get_attachment', {t['name'] for t in tools})
        for name, arguments in [
            ('imap_delete_message', {'message_id': 'imap:default:INBOX:1:1', 'confirm': True}),
            ('smtp_send_message', {'to': ['recipient@example.invalid'], 'subject': 'Synthetic', 'body_text': 'Synthetic'}),
        ]:
            r = self.rpc('tools/call', {'name': name, 'arguments': arguments})
            self.assertIn('disabled', json.dumps(r).lower())

    def test_disconnected_tunnel_fails_readiness(self):
        r = self.docker('exec', self.name, '/usr/local/bin/bash', '-c',
                        'exec 3<>/dev/tcp/127.0.0.1/8000 && wget -q -O /dev/null http://127.0.0.1:2000/ready')
        self.assertNotEqual(r.returncode, 0)

    def test_real_tunnel_failure_stops_container(self):
        token = base64.b64encode(json.dumps({
            'a': '0' * 32, 't': str(uuid.UUID(int=0)),
            's': base64.b64encode(bytes(32)).decode(),
        }).encode()).decode()
        name = self.name + '-failure'
        try:
            r = self.docker('run', '-d', '--name', name, '--network', 'none',
                            '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777',
                            '-e', 'MAIL_IMAP_DEFAULT_USER=fixture', '-e', 'MAIL_IMAP_DEFAULT_PASS=synthetic',
                            '-e', 'TUNNEL_TOKEN=' + token, IMAGE)
            self.assertEqual(r.returncode, 0)
            r = self.docker('wait', name)
            self.assertEqual(r.returncode, 0)
            self.assertNotEqual(r.stdout.strip(), '0')
        finally:
            self.docker('rm', '-f', name)

    def test_shutdown_stops_both(self):
        r = self.docker('stop', '--time', '10', self.name)
        self.assertEqual(r.returncode, 0)
        r = self.docker('inspect', '--format', '{{.State.ExitCode}}', self.name)
        self.assertEqual(r.stdout.strip(), '143')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--context', help='Optional explicit local Docker context')
    parser.add_argument('--image', default='yandex-mail-mcp:local-check')
    args, remaining = parser.parse_known_args()
    DOCKER = ['docker', *(['--context', args.context] if args.context else [])]
    IMAGE = args.image
    unittest.main(argv=[__file__, *remaining])
