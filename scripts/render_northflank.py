#!/usr/bin/env python3
"""Generate one Northflank combined-service body locally; performs no API calls."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo-url', required=True)
parser.add_argument('--branch', default='main')
parser.add_argument('--deployment-plan', required=True, help='Plan confirmed free for your account')
parser.add_argument('--out', type=Path, default=Path('.private/combined-service.json'))
args = parser.parse_args()
url = urlparse(args.repo_url)
if url.scheme != 'https' or url.netloc != 'github.com' or url.username or url.password or url.query or url.fragment:
    parser.error('Use a plain HTTPS GitHub repository URL with no credentials or query')
if len(url.path.strip('/').split('/')) != 2:
    parser.error('Expected a GitHub owner/repository path')
if not re.fullmatch(r'[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*', args.deployment_plan):
    parser.error('Invalid plan ID')
root = Path(__file__).resolve().parents[1]
# Resolve traversal and symlinks before writing any operator-specific value.
private_root = root / '.private'
if private_root.is_symlink():
    parser.error('The private directory must not be a symlink')
out = (args.out if args.out.is_absolute() else root / args.out).resolve()
if not out.is_relative_to(private_root) or out == private_root:
    parser.error('Output must stay inside the repository .private directory')
body = json.loads((root / 'deploy/northflank/combined-service.example.json').read_text())
body['vcsData']['projectUrl'] = args.repo_url
body['vcsData']['projectBranch'] = args.branch
body['billing']['deploymentPlan'] = args.deployment_plan
out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
out.write_text(json.dumps(body, indent=2) + '\n')
out.chmod(0o600)
print('Prepared one paused combined service. No API calls made.')
