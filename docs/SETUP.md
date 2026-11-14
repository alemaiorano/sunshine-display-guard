# Setup

## 1. Establish a working host and client

Install and pair Sunshine and Moonlight using upstream documentation. First test
normal streaming without this utility. Sunshine supports multiple capture
backends; validate your GPU/backend and permissions first. This utility does not
grant Sunshine capture capabilities or install a replacement display driver.

On Linux, Sunshine recommends stable connector names for `output_name`. The
policy follows Mutter's primary output and maps the common HDMI naming alias to
DRM. Confirm names in Sunshine's own startup display list. The capture settings
and prep-command semantics are documented [upstream](https://docs.lizardbyte.dev/projects/sunshine/latest/md_docs_2configuration.html).

Use one designated graphical account, one Sunshine service and one managed
stream at a time. Do not run another display automation controller alongside
this policy. Close streams before installation or upgrade. The installer
protects configured hooks; unrelated programs that bypass those hooks are
outside this ownership contract.

## 2. Dependencies and a reserve output

Install distribution packages for Python 3.10+, PyGObject/Gio/GLib, python-dbus,
systemd 237+ and tcpdump. On Debian/Ubuntu these commonly include `python3-gi`,
`python3-dbus` and `tcpdump`. Check that `/usr/bin/tcpdump` and the `tcpdump`
system account exist. Zenity is needed only for interactive multi-screen selection.
Install Moonlight separately; configure its executable path if it is not `moonlight`.

Provide a DRM-backed reserve display that both Mutter and Sunshine can already
activate/capture. Software-only remote-session outputs without a matching DRM
connector are outside this initial host profile. Options depend on
your GPU/driver: a suitable display emulator or a separately configured virtual
output. This project does not automatically choose an unused physical port or
modify sysfs, PCI paths, initramfs, firmware or kernel parameters.

For an EDID file **only**, generate and inspect your own timings:

```sh
/usr/bin/python3 scripts/generate_edid.py \
  --mode 1920x1080@60 --mode 1080x1920@60 \
  --mode 2560x1080@50 --mode 1080x2560@50 \
  --max-clock-mhz 165 > virtual-display.bin
```

The clock ceiling must match your hardware. DTD dimensions above 4095 are not
supported by this generator. A generated file alone does not create a monitor.
The synthetic identity is locally named `ZZV/Virtual`, not a registered hardware
vendor claim. GNOME may display the vendor code; the client launcher labels it
as a virtual monitor. No global hwdb modifications are installed.

## 3. Configure the graphical user

```sh
mkdir -p "$HOME/.config/sunshine-display-guard"
chmod 700 "$HOME/.config/sunshine-display-guard"
cp examples/config.json "$HOME/.config/sunshine-display-guard/config.json"
chmod 600 "$HOME/.config/sunshine-display-guard/config.json"
```

Edit that file. Use `moonlight-client.py --monitor-status` for connected/active
outputs; choose the reserve deliberately. Determine your Sunshine service name
with `systemctl --user list-unit-files '*sunshine*' '*Sunshine*'`, or the system
service list if yours runs system-wide. Set `sunshine_scope` to `user` or `system`.
Never guess the service name from an example.

Required for the supported automatic host profile:

- `reserve_connector`: the Mutter connector for the prepared reserve.
- `sunshine_unit` / `sunshine_scope`: your installed service and scope.
- `sunshine_config`: the configuration file actually used by Sunshine.
- `follow_primary`: `true` to reconcile capture after a topology change.
- `restart_credentials`: a local file path containing `username` and `password`
  for your Sunshine management API. Create it locally with an editor, mode 0600
  and ownership by the graphical user. Never put it in the checkout or command line.
- `api_port`: the local HTTPS management port; requests stay on `127.0.0.1`.
- `video_port`: Sunshine's outgoing UDP video source port, matching the observer.

For the optional client launcher set `moonlight_binary`, `moonlight_host`,
`moonlight_app`, `moonlight_fps` and `moonlight_bitrate`. `resolution_fps_limits`
can map dimensions such as `2560x1080` to `50` when your host's mode cannot reach
60 Hz. No device-specific limits are built in. Matching stream dimensions to
host display dimensions avoids unnecessary scaling; see the
[Moonlight guide](https://github.com/moonlight-stream/moonlight-docs/wiki/Setup-Guide).

Default configuration/state paths follow XDG user directories. A custom config
can be selected with `SDG_CONFIG`; persistent systemd services need an explicit
user drop-in containing the same environment. Runtime ownership uses the normal
systemd `/run/user/UID` path. Do not override `XDG_RUNTIME_DIR` for installed
services or hooks: installer maintenance uses that standard path.

## 4. Preview and install

```sh
/usr/bin/python3 scripts/install.py --user "$USER"
sudo /usr/bin/python3 scripts/install.py --user "$USER" --apply
```

`--apply` writes only the project's root-owned release directory and two units,
starts/enables the passive observer and restarts the user policy **only if already
active**. It refuses a masked unit, an active lease, recent video or an unverified
producer. It does not install Python dependencies, copy your credentials or
write your Sunshine/Moonlight configuration.

For a nondefault video port, create `/etc/sunshine-display-guard/observer.env`
from `examples/observer.env`, owned by root, and set `SDG_VIDEO_PORT` to match
`video_port`. Restart the observer with streams closed, then recheck diagnostics.
Changing it after installation does not automatically change the user config.
The initial installer uses the root file if it exists, so prepare it first if needed.

## 5. Create a separate Sunshine application

```sh
/usr/bin/python3 scripts/app_hooks.py --name 'Desktop (Display Guard)'
/usr/bin/python3 scripts/app_hooks.py --name 'Desktop (Display Guard)' --apply
```

Preview prints only the proposed entry. Applying creates a **new** app, preserving
existing entries and a private backup. Existing names are refused instead of
silently replacing your command or prep hooks. Use `--apps-file` if your Sunshine
configuration lives elsewhere. Close the Sunshine configuration UI while editing;
an external writer does not share the tool's lock. Restart Sunshine manually
with streams closed so it loads the new application.

The entry runs `prepare` followed by the session watcher. Restore is tied to the
watcher's ownership token, not an unscoped old undo hook. Do not manually attach
an undo command that could restore a newer session's lease.

### Optional: a virtual screen even with two physical monitors

For exclusive remote use, create a second app with `--exclusive-reserve`:

```sh
/usr/bin/python3 scripts/app_hooks.py --name 'Remote Desktop (Virtual)' --exclusive-reserve
/usr/bin/python3 scripts/app_hooks.py --name 'Remote Desktop (Virtual)' --exclusive-reserve --apply
```

This temporarily selects only `reserve_connector`, adjusts its mode to the client,
and restores the previous layout on exit. Physical outputs leave the desktop
while it runs; existing apps/default behavior are unchanged. Select the new app
in Moonlight. Read [exclusive reserve](EXCLUSIVE-RESERVE.md) for capture/backend
requirements, conflict refusal, standby recovery and phone input settings.

## 6. Verify and enable

```sh
/usr/bin/python3 /usr/local/lib/sunshine-display-guard/current/diagnose.py --require-ready
systemctl --user enable --now sunshine-display-guard.service
```

The unit checks readiness before starting. `ready` verifies configuration,
credentials' file permissions, source/port/input observer health, reserve
availability and an unambiguous matching DRM connector and a running Sunshine service. It is not a certificate of usable
video: authentication correctness and actual streaming must still be tested.
The disabled capture-sync profile remains useful for read-only tools or expert
manual integration, but does not pass automatic-host readiness.

Test one physical monitor, extension, mirroring, standby/return and the virtual
output. Keep a separate recovery connection available during your first tests.
Do not use logout or reboot as a casual test when unsaved work exists.

Optional client use:

```sh
/usr/bin/python3 scripts/moonlight-client.py --list-monitors
/usr/bin/python3 scripts/moonlight-client.py --monitor DP-9 --dry-run
/usr/bin/python3 scripts/moonlight-client.py
```

`DP-9` is only an example. The launcher owns only its own client lock; it does not
close other Moonlight instances or renegotiate an already-running stream when
you move its window. Stop and reconnect to change the target resolution.
