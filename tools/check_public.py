#!/usr/bin/python3
"""Scan source, staged files or reachable Git history without printing matches."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','__pycache__','.venv','artifacts','backups','state'}
BAD_NAMES={'Moonlight.conf','sunshine_state.json','apps.json','restart-credentials.json',
           '.env','id_rsa','id_ed25519','tailscaled.state'}
PATTERNS=[r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
          r'\bgh[pousr]_[A-Za-z0-9]{25,}',r'\bgithub_pat_[A-Za-z0-9_]{30,}',
          r'(?i)https?://[^/\s]+:[^/\s]+@',r'(?i)ssh-(?:ed25519|rsa)\s+[A-Za-z0-9+/]{30,}',
          r'/home/[A-Za-z0-9_.-]+',r'(?i)[A-Z]:\\Users\\[A-Za-z0-9_.-]+']


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)


def scan(name,data,deny=()):
    findings=[];path=Path(name)
    if path.name in BAD_NAMES or (path.name=='config.json' and name!='examples/config.json') or path.suffix in {'.pem','.key','.pfx','.log','.bin','.zip','.gz'}:
        findings.append(f'{name}: forbidden artifact/config filename')
    try:text=data.decode('utf-8')
    except UnicodeDecodeError:return findings+[f'{name}: binary/non-UTF8 content requires explicit review']
    if any(re.search(p,text) for p in PATTERNS):findings.append(f'{name}: possible secret or private path')
    for match in re.finditer(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',text):
        try:address=ipaddress.ip_address(match.group())
        except ValueError:continue
        if not address.is_loopback and address not in ipaddress.ip_network('192.0.2.0/24') and address not in ipaddress.ip_network('198.51.100.0/24') and address not in ipaddress.ip_network('203.0.113.0/24'):
            findings.append(f'{name}: non-documentation IP literal');break
    emails=re.findall(r'(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',text)
    if any(not re.fullmatch(r'\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com',e) for e in emails):
        findings.append(f'{name}: email address requires review')
    if any(value and value.casefold() in text.casefold() for value in deny):
        findings.append(f'{name}: external private-data denylist match')
    return findings


def inspect(mode,deny=()):
    errors=[];count=0
    if mode=='tree':
        for path in sorted(ROOT.rglob('*')):
            rel=path.relative_to(ROOT)
            if any(part in SKIP for part in rel.parts):continue
            if path.is_symlink():errors.append(f'{rel}: source symlink requires review')
            elif path.is_file():errors+=scan(rel.as_posix(),path.read_bytes(),deny);count+=1
    elif mode=='index':
        for entry in git('ls-files','--stage','-z').split(b'\0'):
            if not entry:continue
            info,name=entry.split(b'\t',1);permissions,oid,stage=info.split();name=name.decode()
            if permissions==b'120000' or stage!=b'0':errors.append(f'{name}: symlink or unmerged index entry')
            errors+=scan(name,git('cat-file','blob',oid.decode()),deny);count+=1
    else:
        commits=git('rev-list','--all').splitlines()
        if not commits:errors.append('No commits available for history review')
        for row in git('rev-list','--objects','--all').splitlines():
            oid,_,name=row.partition(b' ')
            if git('cat-file','-t',oid.decode()).strip()==b'blob':
                errors+=scan(name.decode() or 'unnamed-blob',git('cat-file','blob',oid.decode()),deny);count+=1
        metadata=git('log','--all','--format=%an <%ae>%n%cn <%ce>%n%B')
        errors+=scan('commit-metadata',metadata,deny)
        remotes=subprocess.run(['git','config','--get-regexp',r'remote\..*\.url'],cwd=ROOT,capture_output=True).stdout
        errors+=scan('remote-metadata',remotes,deny)
    return dict(mode=mode,objects_scanned=count,errors=sorted(set(errors)))


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    for name in ('tree','index','history'):g.add_argument('--'+name,action='store_true')
    p.add_argument('--deny-file',type=Path,help='private external JSON list; its content is never printed')
    args=p.parse_args();deny=json.loads(args.deny_file.read_text()) if args.deny_file else []
    if not isinstance(deny,list) or not all(isinstance(x,str) for x in deny):p.error('deny-file must contain strings')
    mode=next(name for name in ('tree','index','history') if getattr(args,name))
    result=inspect(mode,deny);print(json.dumps(result,indent=2));return bool(result['errors'])


if __name__=='__main__':raise SystemExit(main())
