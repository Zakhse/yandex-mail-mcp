"""Test process failure, shutdown, forced defaults and credential separation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/start-services.sh'


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mail-supervisor-synthetic-')
        self.root = Path(self.temp.name)
        self.bash = shutil.which('bash')
        version = subprocess.check_output([self.bash, '-c', 'echo ${BASH_VERSINFO[0]}']).strip()
        if int(version) < 5:
            self.skipTest('Bash >=5.1 is required; the pinned container includes Bash 5.3')
        # Mock binaries report only synthetic values from a clean environment.
        for name in ['mail', 'tunnel']:
            p = self.root / name
            p.write_text('#!/usr/bin/env python3\nimport os,json,time,signal,sys\n'
                         f'open({str(self.root / (name + ".json"))!r},"w").write(json.dumps(dict(os.environ)))\n'
                         f'open({str(self.root / (name + ".pid"))!r},"w").write(str(os.getpid()))\n'
                         f'while not os.path.exists({str(self.root / (name + ".exit"))!r}): time.sleep(.03)\n'
                         'sys.exit(0)\n')
            p.chmod(0o755)
        # cloudflared's cleaned PATH deliberately uses the system Python.
        self.process = subprocess.Popen([self.bash, str(SCRIPT), str(self.root / 'mail'), str(self.root / 'tunnel')],
            cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={
                'PATH': '/usr/bin:/bin', 'MAIL_IMAP_DEFAULT_USER': 'fixture',
                'MAIL_IMAP_DEFAULT_PASS': 'synthetic-mail', 'TUNNEL_TOKEN': 'synthetic-tunnel',
                'MAIL_ATTACHMENT_DOWNLOAD_DIR': str(self.root / 'attachments'),
                'MAIL_IMAP_WRITE_ENABLED': 'true', 'MAIL_SMTP_WRITE_ENABLED': 'true',
                'MAIL_MCP_HTTP_HOST': '0.0.0.0', 'MAIL_IMAP_DEFAULT_SECURE': 'false',
                'MAIL_GRAPH_DEFAULT_CLIENT_SECRET': 'synthetic-extra-provider',
                'MAIL_SMTP_DEFAULT_PASS': 'synthetic-extra-smtp',
            })
        for _ in range(100):
            if all((self.root / (name + '.json')).exists() for name in ['mail', 'tunnel']):
                return
            time.sleep(.03)
        self.fail('Mock programs did not start')

    def tearDown(self):
        if hasattr(self, 'process'):
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=10)
        self.temp.cleanup()

    def assert_children_stopped(self):
        for name in ['mail', 'tunnel']:
            pid = int((self.root / (name + '.pid')).read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_credentials_and_defaults(self):
        mail = json.loads((self.root / 'mail.json').read_text())
        tunnel = json.loads((self.root / 'tunnel.json').read_text())
        self.assertNotIn('TUNNEL_TOKEN', mail)
        self.assertNotIn('MAIL_GRAPH_DEFAULT_CLIENT_SECRET', mail)
        self.assertNotIn('MAIL_SMTP_DEFAULT_PASS', mail)
        self.assertNotIn('MAIL_IMAP_DEFAULT_PASS', tunnel)
        self.assertEqual(mail['MAIL_IMAP_WRITE_ENABLED'], 'false')
        self.assertEqual(mail['MAIL_SMTP_WRITE_ENABLED'], 'false')
        self.assertEqual(mail['MAIL_IMAP_DEFAULT_SECURE'], 'true')
        self.assertEqual(mail['MAIL_MCP_HTTP_HOST'], '127.0.0.1')

    def test_mail_exit_stops_tunnel(self):
        (self.root / 'mail.exit').touch()
        self.assertNotEqual(self.process.wait(timeout=10), 0)
        self.assert_children_stopped()

    def test_tunnel_exit_stops_mail(self):
        (self.root / 'tunnel.exit').touch()
        self.assertNotEqual(self.process.wait(timeout=10), 0)
        self.assert_children_stopped()

    def test_sigterm_stops_both(self):
        self.process.terminate()
        self.assertEqual(self.process.wait(timeout=10), 143)
        self.assert_children_stopped()


if __name__ == '__main__':
    unittest.main()
