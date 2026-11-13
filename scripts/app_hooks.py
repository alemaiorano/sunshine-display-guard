#!/usr/bin/python3
"""Create a separate Sunshine desktop app; preview by default."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import time
from guard_config import init_paths,runtime_dir,state_dir
from sunshine_layout import atomic_json

PROGRAM='/usr/bin/python3 /usr/local/lib/sunshine-display-guard/current/sunshine_session_display.py'


def application(name):
    if not name or len(name)>128 or any(ord(c)<32 for c in name):raise ValueError('Invalid app name')
    return {'name':name,'cmd':PROGRAM+' session','auto-detach':False,'wait-all':False,
            'prep-cmd':[{'do':PROGRAM+' prepare','undo':''}]}


def update(path,name,apply=False):
    path=Path(path).expanduser();entry=application(name)
    if not apply:return {'app':entry,'writes_files':False}
    init_paths()
    with (runtime_dir()/'apps.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if path.is_symlink():raise ValueError('Review symlinked apps configuration manually')
        info=path.stat()
        if info.st_uid!=os.getuid():raise ValueError('Apps configuration must be owned by this user')
        original=path.read_bytes()
        if len(original)>1048576:raise ValueError('Apps configuration too large')
        data=json.loads(original)
        if not isinstance(data,dict) or not isinstance(data.get('apps'),list):raise ValueError('Invalid apps.json')
        matches=[a for a in data['apps'] if isinstance(a,dict) and a.get('name')==name]
        if matches:raise ValueError('App name already exists; select a separate name instead of overwriting it')
        data['apps'].append(entry)
        backup=state_dir()/'backups'/str(time.time_ns());backup.mkdir(parents=True,mode=0o700)
        destination=backup/'apps.json';destination.write_bytes(original);destination.chmod(0o600)
        # An external Sunshine UI edit must not silently be overwritten.
        if path.read_bytes()!=original:raise ValueError('Apps changed during preparation; retry')
        temporary=path.with_name(path.name+'.sdg-new')
        if os.path.lexists(temporary):raise ValueError('Stale apps transaction file; review it first')
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,info.st_mode & 0o777)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(data,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
        return {'created':name,'backup':str(destination),'restart_sunshine_manually':True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apps-file',default='~/.config/sunshine/apps.json')
    p.add_argument('--name',default='Desktop (Display Guard)');p.add_argument('--apply',action='store_true')
    args=p.parse_args();print(json.dumps(update(args.apps_file,args.name,args.apply),indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,TypeError,RecursionError) as e:raise SystemExit(str(e))
