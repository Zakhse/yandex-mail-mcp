#!/usr/bin/env python3
"""Small public-repository guard, not a replacement for human review/Gitleaks.
Reports file and rule only, never the matching private value. Uses git's tracked
and unignored file lists, so local secrets and dependencies are never opened.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
try:
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                            capture_output=True, check=True)
    paths = {Path(p.decode()) for p in result.stdout.split(b'\0') if p}
except (subprocess.CalledProcessError, FileNotFoundError):
    paths = {p.relative_to(root) for p in root.rglob('*') if p.is_file()
             and not any(x in p.parts for x in ['.git', '.private', '__pycache__', 'node_modules'])}
failures = []
allowed_hosts = {'github.com', 'raw.githubusercontent.com', 'api.github.com', 'ghcr.io',
                 'northflank.com', 'api.northflank.com', 'developers.cloudflare.com',
                 'www.cloudflare.com', 'developers.openai.com', 'chatgpt.com',
                 'yandex.com', 'yandex.ru', 'registry.npmjs.org'}
for name in sorted(paths):
    p = root / name
    if not p.is_file():
        continue
    if any(x in name.parts for x in ['.private', 'attachments']) or (name.name.startswith('.env') and name.name != '.env.example'):
        failures.append((str(name), 'private-file'))
        continue
    try:
        s = p.read_text()
    except UnicodeDecodeError:
        failures.append((str(name), 'unexpected-binary'))
        continue
    rules = {
        'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'cloudflare-id': r'\b[0-9a-fA-F]{32}\b|\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b',
        'access-token': r'\b(?:ghp_|github_pat_|eyJ)[A-Za-z0-9_./+-]{20,}',
        'local-owner-path': r'/(?:Users|home)/[A-Za-z0-9_-]+/',
        'instance-hostname': r'\b[\w.-]+\.(?:code\.run|cloudflareaccess\.com|trycloudflare\.com|workers\.dev)\b',
    }
    for rule, pattern in rules.items():
        if re.search(pattern, s):
            failures.append((str(name), rule))
    for address in re.findall(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', s):
        if address.rsplit('@', 1)[1] not in {'example.invalid', 'example.com'}:
            failures.append((str(name), 'non-example-email'))
    for ip in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', s):
        if ip not in {'127.0.0.1', '0.0.0.0'}:
            failures.append((str(name), 'fixed-ip'))
    for value in re.findall(r'https?://[^\s<>"\x27`\\)]+', s):
        host = urlsplit(value).hostname
        if host and host not in allowed_hosts and host not in {'127.0.0.1', 'localhost', 'your_mcp_hostname'} and not host.endswith(('.example', '.invalid')):
            failures.append((str(name), 'unreviewed-hostname'))
lock = json.loads((root / 'deploy/versions.json').read_text())
for key in ['mail_mcp', 'cloudflared', 'base_image']:
    if lock[key]['image'] not in (root / 'Dockerfile').read_text():
        failures.append(('Dockerfile', 'image-pin-mismatch'))
body = json.loads((root / 'deploy/northflank/combined-service.example.json').read_text())
if body['ports'] or body['deployment']['instances'] != 0 or body['runtimeEnvironment'] or body['buildArguments']:
    failures.append(('deploy/northflank/combined-service.example.json', 'unsafe-defaults'))
for name, rule in sorted(set(failures)):
    print(f'{name}: {rule}', file=sys.stderr)
if failures:
    sys.exit(1)
print(f'Public-file guard passed for {len(paths)} files. Review before publishing.')
