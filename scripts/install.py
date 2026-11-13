#!/usr/bin/python3
"""Install an immutable release; privileged mutation requires --apply."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
PREFIX=Path('/usr/local/lib/sunshine-display-guard')
SYSTEM=Path('/etc/systemd/system')
USER=Path('/etc/systemd/user')
OBSERVER='sunshine-display-guard-observer.service'
POLICY='sunshine-display-guard.service'
STATE=Path('/run/sunshine-display-guard/observer.json')
BOOT=Path('/proc/sys/kernel/random/boot_id')
INSTALL_LOCK=Path('/run/lock/sunshine-display-guard-install.lock')
MODULES=('guard_config.py','sunshine_layout.py','sunshine_observer.py',
         'sunshine_session_display.py','keep-display-awake.py',
         'sunshine-desktop-policy.py','moonlight-client.py','diagnose.py','app_hooks.py')


def run(args,check=True):
    return subprocess.run(args,text=True,capture_output=True,check=check,timeout=15)


def user_command(account,*args):
    return ['/usr/sbin/runuser','-u',account.pw_name,'--','/usr/bin/env',
            f'HOME={account.pw_dir}',f'XDG_RUNTIME_DIR=/run/user/{account.pw_uid}',
            f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{account.pw_uid}/bus',
            '/usr/bin/systemctl','--user',*args]


def active(command):
    return run([*command,'is-active','--quiet',OBSERVER if command==['systemctl'] else POLICY],False).returncode==0


def payload():
    result={}
    for name in MODULES:
        path=ROOT/'scripts'/name
        if path.is_symlink():raise ValueError('Release source cannot contain symlinks')
        data=path.read_bytes();compile(data,str(path),'exec');result[name]=data
    for name in (OBSERVER,POLICY):
        path=ROOT/'systemd'/name
        if path.is_symlink():raise ValueError('Unit source cannot be a symlink')
        result[name]=path.read_bytes()
    return result


def identity(files):
    h=hashlib.sha256()
    for name,data in sorted(files.items()):h.update(name.encode()+b'\0'+data+b'\0')
    return h.hexdigest()


def atomic_write(path,data,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.sdg-',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)


def ensure_directory(path,mode=0o755):
    try:path.mkdir(mode=mode)
    except FileExistsError:pass
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Unsafe ownership/permissions in managed installation directory')


@contextlib.contextmanager
def global_lock():
    fd=os.open(INSTALL_LOCK,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or info.st_mode & 0o022:
            raise ValueError('Unsafe installation lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:os.close(fd)


def point_to(target):
    temporary=PREFIX/('current.new-'+str(os.getpid()))
    try:
        temporary.symlink_to(target);os.replace(temporary,PREFIX/'current')
    finally:temporary.unlink(missing_ok=True)


def preflight_video():
    running=run(['systemctl','is-active','--quiet',OBSERVER],False).returncode==0
    if not STATE.exists():
        if running:raise ValueError('Running observer has no heartbeat; recover it first')
        return
    value=json.loads(STATE.read_bytes())
    now=time.monotonic()
    if value['boot_id']!=BOOT.read_text().strip():raise ValueError('Stale boot heartbeat')
    if running and not 0<=now-value['observed_at']<5:raise ValueError('Observer heartbeat stale')
    if value['video_at'] and now-value['video_at']<=3:raise ValueError('Video active; close streams before updating')


def attest(expected,timeout=8):
    pid=int(run(['systemctl','show',OBSERVER,'-p','MainPID','--value']).stdout)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            v=json.loads(STATE.read_bytes());now=time.monotonic()
            good=(v['schema']==2 and v['boot_id']==BOOT.read_text().strip() and
                  v['producer_pid']==pid and pid>0 and v['source_sha256']==expected and
                  0<=now-v['producer_started_at']<10 and 0<=now-v['observed_at']<2 and
                  0<=now-v['input_scan_at']<5 and v['input_errors']==0 and
                  v['input_opened']==v['input_eligible'] and
                  (not v['video_at'] or now-v['video_at']>3))
            if good:return
        except (OSError,ValueError,KeyError,TypeError):pass
        time.sleep(.1)
    raise RuntimeError('New observer failed source/PID/boot/coverage attestation')


@contextlib.contextmanager
def maintenance_lock(account):
    # Anchor to an opened directory: never follow a user-supplied lock symlink.
    runtime=Path(f'/run/user/{account.pw_uid}')/'sunshine-display-guard'
    if not runtime.exists():
        yield  # First installation has no configured hooks yet.
        return
    dfd=os.open(runtime,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    fd=None
    try:
        if os.fstat(dfd).st_uid!=account.pw_uid:raise ValueError('Runtime owner mismatch')
        created=False
        try:
            fd=os.open('lease.lock',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dfd);created=True
        except FileExistsError:
            fd=os.open('lease.lock',os.O_RDWR|os.O_NOFOLLOW,dir_fd=dfd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('Lock is not a regular file')
        if created:os.fchown(fd,account.pw_uid,account.pw_gid)
        deadline=time.monotonic()+5
        while True:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise TimeoutError('Display transaction busy')
                time.sleep(.025)
        if os.path.lexists(runtime/'lease.json'):raise ValueError('Lease exists; close/recover the display session first')
        yield
    finally:
        if fd is not None:os.close(fd)
        os.close(dfd)


def apply(account,files):
    revision=identity(files);release=PREFIX/'releases'/revision
    def userctl(*args):return run(user_command(account,*args))
    with global_lock():
        with maintenance_lock(account):
            # A socket can outlive its manager; verify the user bus before writes.
            if not userctl('show','-p','Version','--value').stdout.strip():
                raise ValueError('Graphical user manager is unavailable')
            preflight_video()
            ensure_directory(PREFIX)
            ensure_directory(PREFIX/'releases')
            ensure_directory(PREFIX/'backups',0o700)
            current=PREFIX/'current'
            if current.exists() and not current.is_symlink():raise ValueError('current must be a managed release symlink')
            old_target=os.readlink(current) if current.is_symlink() else None
            if old_target is not None and current.resolve().parent!=(PREFIX/'releases').resolve():
                raise ValueError('current points outside managed releases')
            unit_paths=[SYSTEM/OBSERVER,USER/POLICY]
            # Never overwrite an administrator's mask or foreign unit symlink.
            if any(p.is_symlink() for p in unit_paths):raise ValueError('Unmask/review unit symlinks before installing')
            old_units={p:p.read_bytes() if p.exists() else None for p in unit_paths}
            root_active=run(['systemctl','is-active','--quiet',OBSERVER],False).returncode==0
            root_enabled=run(['systemctl','is-enabled','--quiet',OBSERVER],False).returncode==0
            policy_active=run(user_command(account,'is-active','--quiet',POLICY),False).returncode==0
            # Retain immutable previous releases and root-owned unit backups.
            backup=PREFIX/'backups'/str(time.time_ns());backup.mkdir(mode=0o700)
            atomic_write(backup/'state.json',json.dumps(dict(previous_release=old_target,root_active=root_active,root_enabled=root_enabled,policy_active=policy_active)).encode(),0o600)
            for p,data in old_units.items():
                if data is not None:atomic_write(backup/p.name,data,0o600)
            if release.exists():
                if release.is_symlink() or any((release/name).is_symlink() or (release/name).read_bytes()!=data for name,data in files.items()):
                    raise ValueError('Existing immutable release differs; refusing overwrite')
            else:
                staging=Path(tempfile.mkdtemp(prefix='.release-',dir=release.parent))
                try:
                    staging.chmod(0o755)
                    for name,data in files.items():atomic_write(staging/name,data)
                    staging.rename(release)
                finally:
                    if staging.exists():shutil.rmtree(staging)
            try:
                if policy_active:userctl('stop',POLICY)
                if root_active:run(['systemctl','stop',OBSERVER])
                point_to(release)
                for p in unit_paths:atomic_write(p,files[p.name])
                run(['systemctl','daemon-reload']);userctl('daemon-reload')
                run(['systemctl','enable',OBSERVER]);run(['systemctl','restart',OBSERVER])
                attest(hashlib.sha256(files['sunshine_observer.py']).hexdigest())
                if policy_active:
                    userctl('start',POLICY);userctl('is-active','--quiet',POLICY)
            except BaseException:
                # Restoration failures are reported; never silently claim rollback.
                stopped=run(['systemctl','stop',OBSERVER],False)
                if stopped.returncode not in (0,5):raise RuntimeError('Rollback could not stop observer')
                if policy_active:userctl('stop',POLICY)
                if not root_enabled:run(['systemctl','disable',OBSERVER])
                if old_target is None:current.unlink(missing_ok=True)
                else:point_to(old_target)
                for p,data in old_units.items():
                    if data is None:p.unlink(missing_ok=True)
                    else:atomic_write(p,data)
                run(['systemctl','daemon-reload'])
                # Restore the passive producer even if the user logged out
                # during maintenance and its manager cannot be reached.
                if root_active:run(['systemctl','start',OBSERVER])
                userctl('daemon-reload')
                if policy_active:userctl('start',POLICY)
                raise
            print('Installed release:',revision)
            print('Rollback evidence:',backup)
            print('User policy was restarted only if it was already active.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user',required=True,help='existing non-root desktop account')
    p.add_argument('--apply',action='store_true',help='perform root installation; default prints a plan')
    args=p.parse_args();account=pwd.getpwnam(args.user)
    if account.pw_uid==0:raise ValueError('Select the non-root graphical-session account')
    files=payload()
    if not args.apply:
        print(json.dumps(dict(release=identity(files),prefix=str(PREFIX),units=[OBSERVER,POLICY],activate_user_policy=False),indent=2));return
    if os.geteuid()!=0:raise PermissionError('--apply requires root; use sudo and enter credentials only in your terminal')
    if not Path(f'/run/user/{account.pw_uid}/bus').is_socket():
        raise ValueError('An active graphical user session bus is required before installation')
    if not Path('/usr/bin/tcpdump').is_file():raise ValueError('Install tcpdump first')
    pwd.getpwnam('tcpdump')  # Package-provided privilege-drop account.
    apply(account,files)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as e:
        raise SystemExit(str(e))
