"""Audit publication candidates without printing matched secrets."""
import argparse
import ipaddress
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {'.venv','.local','__pycache__','cache','downloads','uploads','test-results'}
BLOCKED_NAMES = {'config.json','known_hosts','.env'}
PATTERNS = {
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'provider-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_-]{15,}|sk-(?:proj-)?[A-Za-z0-9_-]{25,})'),
    'jwt': re.compile(r'\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{15,}'),
    'tunnel-id': re.compile(r'\btunnel_[a-z0-9]{32}\b'),
    'local-user-path': re.compile(r'[A-Za-z]:[\\/](?:Users|codex|seadrive_root)[\\/]',re.I),
    'credential-url': re.compile(r'https?://[^\s/@:]+:[^\s/@]+@'),
}


def candidates(tracked):
    if tracked:
        raw=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT)
        return [ROOT/Path(name.decode('utf-8')) for name in raw.split(b'\0') if name]
    return [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts
            and not set(p.relative_to(ROOT).parts)&BLOCKED_PARTS]


def audit(tracked=False):
    failures=[]
    files=candidates(tracked)
    for file in files:
        relative=file.relative_to(ROOT)
        if set(relative.parts)&BLOCKED_PARTS or file.name in BLOCKED_NAMES or file.suffix.lower() in {'.sqlite3','.log','.pem','.key','.exe','.zip','.db'}:
            failures.append((str(relative),'private-runtime-file'))
            continue
        data=file.read_bytes()
        try:
            text=data.decode('utf-8-sig')
        except UnicodeDecodeError:
            failures.append((str(relative),'unexpected-binary'))
            continue
        # Negative fixtures deliberately contain fabricated credential URLs.
        for name,pattern in PATTERNS.items():
            if name=='credential-url' and relative.parts[0]=='tests':
                continue
            if pattern.search(text):
                failures.append((str(relative),name))
        for address in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',text):
            try:
                ip=ipaddress.ip_address(address)
            except ValueError:
                continue
            if not (ip.is_loopback or str(ip) in ('0.0.0.0','192.0.2.1','203.0.113.1')):
                failures.append((str(relative),'non-example-ip'))
    if failures:
        for path,reason in failures:
            print(f'{path}: {reason}')
        raise SystemExit('Public audit failed.')
    print(f'Public audit passed: {len(files)} text files inspected.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--tracked',action='store_true')
    audit(parser.parse_args().tracked)
