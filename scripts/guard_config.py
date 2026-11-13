"""Validated per-user configuration. Importing modules never enables policy."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat

APP = 'sunshine-display-guard'


def config_path():
    return Path(os.environ.get('SDG_CONFIG') or
                Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/APP/'config.json')


def runtime_dir():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))/APP


def state_dir():
    return Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/APP


def journal_args(unit,scope,invocation=None):
    args=['--user-unit' if scope=='user' else '--unit',unit]
    if invocation:
        # Application stdout carries this trusted field (systemd >= 233).
        # Avoid --invocation, introduced much later than our journal baseline.
        args.append('_SYSTEMD_INVOCATION_ID='+invocation)
    return args


@dataclass(frozen=True)
class Settings:
    reserve_connector: str | None = None
    sunshine_unit: str = 'sunshine.service'
    sunshine_scope: str = 'user'
    sunshine_config: str = '~/.config/sunshine/sunshine.conf'
    follow_primary: bool = False
    restart_credentials: str | None = None
    api_port: int = 47990
    video_port: int = 47998
    moonlight_binary: str = 'moonlight'
    moonlight_host: str | None = None
    moonlight_app: str = 'Desktop'
    moonlight_fps: int = 60
    moonlight_bitrate: int = 20000
    resolution_fps_limits: dict = field(default_factory=dict)

    @property
    def unit_flags(self):
        return ['--user'] if self.sunshine_scope == 'user' else []


def load(path=None, required=False):
    path = config_path() if path is None else Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if required:
            raise ValueError('Configuration missing; copy examples/config.json and edit it first')
        return Settings()
    if len(raw)>65536:
        raise ValueError('Configuration exceeds 64 KiB')
    try:
        value=json.loads(raw)
    except (ValueError, RecursionError):
        raise ValueError('Invalid configuration JSON') from None
    if not isinstance(value,dict) or set(value)-set(Settings.__dataclass_fields__):
        raise ValueError('Unknown configuration keys or non-object configuration')
    result=Settings(**value)
    connector=result.reserve_connector
    if connector is not None and (not isinstance(connector,str) or
                                  not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',connector)):
        raise ValueError('Invalid reserve_connector')
    if not isinstance(result.sunshine_unit,str) or not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service',result.sunshine_unit):
        raise ValueError('Invalid sunshine_unit')
    if result.sunshine_scope not in ('user','system') or type(result.follow_primary) is not bool:
        raise ValueError('Invalid service scope or follow_primary')
    for key in ('api_port','video_port'):
        n=getattr(result,key)
        if type(n) is not int or not 1<=n<=65535:raise ValueError('Invalid port')
    for key,maximum in [('moonlight_fps',240),('moonlight_bitrate',1000000)]:
        n=getattr(result,key)
        if type(n) is not int or not 1<=n<=maximum:raise ValueError('Invalid client numeric option')
    for key in ('sunshine_config','moonlight_binary','moonlight_app'):
        s=getattr(result,key)
        if not isinstance(s,str) or not s or s.startswith('-') or len(s)>4096 or any(ord(c)<32 for c in s):raise ValueError('Invalid string option')
    host=result.moonlight_host
    if host is not None and (not isinstance(host,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}',host)):
        raise ValueError('Invalid moonlight_host')
    creds=result.restart_credentials
    if creds is not None and (not isinstance(creds,str) or not creds or '\x00' in creds):raise ValueError('Invalid credential path')
    if result.follow_primary and not creds:raise ValueError('follow_primary requires a local restart_credentials path')
    limits=result.resolution_fps_limits
    if not isinstance(limits,dict) or len(limits)>128:raise ValueError('Invalid refresh limits')
    for key,n in limits.items():
        if not re.fullmatch(r'[1-9][0-9]{0,4}x[1-9][0-9]{0,4}',key) or type(n) is not int or not 1<=n<=240:
            raise ValueError('Invalid resolution refresh limit')
    return result


SETTINGS=load()


def read_credentials(path):
    path=Path(path).expanduser()
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise ValueError('Credentials must be a private regular file owned by this user')
    with path.open('rb') as stream:raw=stream.read(16385)
    if len(raw)>16384:raise ValueError('Credential file exceeds 16 KiB')
    try:value=json.loads(raw)
    except (ValueError,RecursionError):raise ValueError('Invalid credential JSON') from None
    if (not isinstance(value,dict) or any(not isinstance(value.get(k),str) or not 0<len(value[k])<=4096 for k in ('username','password')) or ':' in value['username']):
        raise ValueError('Invalid credential fields')
    return value


def require_host():
    settings=load(required=True)
    if not settings.reserve_connector:
        raise ValueError('Set reserve_connector to an already-provisioned virtual output')
    return settings


def init_paths():
    for path in (runtime_dir(),state_dir()):
        path.mkdir(mode=0o700,parents=True,exist_ok=True)
        if path.is_symlink() or path.stat().st_uid!=os.getuid() or path.stat().st_mode & 0o077:
            raise ValueError('State and runtime directories must be private and owned by this user')
