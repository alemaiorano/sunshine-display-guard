#!/usr/bin/python3
"""Select a GNOME screen and launch an explicitly configured Moonlight host."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from gi.repository import Gio, GLib
from guard_config import SETTINGS, runtime_dir, init_paths


def monitor_name(spec, props):
    # Match our EDID identity; a physical Dell must retain its real name.
    if spec[1:3] in (('ZZV', 'Virtual'),):
        return 'Virtual monitor'
    return props.get('display-name', spec[0])


def monitor_status(state):
    active = {output[0] for group in state[2] for output in group[5]}
    result = []
    for spec, modes, props in state[1]:
        connector = spec[0]
        drm = connector.replace('HDMI-', 'HDMI-A-', 1) if connector.startswith('HDMI-') else connector
        paths = list(Path('/sys/class/drm').glob('card*-' + drm))
        def read(name):
            if len(paths) != 1:
                return None
            try:
                return (paths[0] / name).read_text().strip()
            except OSError:
                return None
        result.append(dict(connector=connector, name=monitor_name(spec, props),
                           connected=True, active=connector in active,
                           drm_status=read('status'), dpms=read('dpms'),
                           panel_power='unknown'))
    return result


def targets(state):
    _, monitors, logical, _ = state
    result = []
    for x,y,scale,transform,primary,outputs,_ in logical:
        spec, modes, props = next(m for m in monitors if m[0] == outputs[0])
        current = next(m for m in modes if m[-1].get('is-current'))
        width,height = current[1:3]
        if transform % 2:
            width,height = height,width
        connector=spec[0]
        result.append(dict(connector=connector, connectors=[o[0] for o in outputs], x=x,y=y,
                           width=width,height=height,scale=scale,primary=primary,
                           label=f'{monitor_name(spec, props)} — {width}×{height}' +
                                 (' — mirrored' if len(outputs)>1 else '') +
                                 (' — primary' if primary else '')))
    return result


def choose_target(screens, connector=None):
    if not screens:
        raise ValueError('No active screen; recover the local display first')
    if connector:
        return next(s for s in screens if connector in s['connectors'])
    if len(screens)==1:
        return screens[0]
    args=['zenity','--list','--radiolist','--title=Moonlight — target screen',
          '--text=Choose the target screen. Resolution follows its current orientation.',
          '--column=Use','--column=Output','--column=Screen','--hide-column=2',
          '--print-column=2','--width=650','--height=280']
    for screen in screens:
        args.extend(['TRUE' if screen['primary'] else 'FALSE',screen['connector'],screen['label']])
    choice=subprocess.run(args,text=True,capture_output=True,check=False)
    if choice.returncode:
        raise SystemExit(0)  # Cancel never launches a stream.
    return choose_target(screens,choice.stdout.strip())


def window_geometry(screen):
    # Qt places the initial window on this screen; Moonlight creates its SDL
    # streaming window on that same Qt screen. Keep the rectangle inside it.
    w=max(1,min(800,int(screen['width']/screen['scale'])-40))
    h=max(1,min(600,int(screen['height']/screen['scale'])-80))
    return f'{w}x{h}{screen["x"]+20:+d}{screen["y"]+40:+d}'



def client_fps(width, height, requested):
    limit=SETTINGS.resolution_fps_limits.get(f'{width}x{height}',requested)
    return min(max(int(requested),1),limit)


def stream_command(target):
    if not SETTINGS.moonlight_host:
        raise ValueError('Set moonlight_host in your local configuration')
    return [SETTINGS.moonlight_binary,'-platform','xcb','-qwindowgeometry',window_geometry(target),
            'stream',SETTINGS.moonlight_host,SETTINGS.moonlight_app,
            '--resolution',f'{target["width"]}x{target["height"]}',
            '--display-mode','borderless','--fps',
            str(client_fps(target['width'],target['height'],SETTINGS.moonlight_fps)),
            '--bitrate',str(SETTINGS.moonlight_bitrate)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monitor')
    parser.add_argument('--list-monitors',action='store_true')
    parser.add_argument('--monitor-status',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    proxy=Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION,Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
        None,'org.gnome.Mutter.DisplayConfig','/org/gnome/Mutter/DisplayConfig','org.gnome.Mutter.DisplayConfig',None)
    def state():return proxy.call_sync('GetCurrentState',None,Gio.DBusCallFlags.NONE,3000,None).unpack()
    current=state()
    if args.monitor_status:
        print(json.dumps(monitor_status(current),ensure_ascii=False,indent=2));return
    if args.list_monitors:
        print(json.dumps(targets(current),ensure_ascii=False,indent=2));return
    screen=choose_target(targets(current),args.monitor)
    connector=screen['connector']
    def fresh_command():
        screens=targets(state())
        try:target=next(s for s in screens if connector in s['connectors'])
        except StopIteration:
            raise ValueError('Selected screen changed or disconnected; select again') from None
        return target,stream_command(target)
    if args.dry_run:
        screen,command=fresh_command()
        print(json.dumps(dict(screen=screen,command=command),ensure_ascii=False,indent=2));return
    init_paths()
    with (runtime_dir()/'client.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('A client started by this launcher is already active') from None
        screen,command=fresh_command()
        raise SystemExit(subprocess.call(command))


if __name__=='__main__':
    try:main()
    except (ValueError,StopIteration,OSError,GLib.Error) as error:
        print(str(error) or 'No active screen',file=sys.stderr)
        raise SystemExit(1)
