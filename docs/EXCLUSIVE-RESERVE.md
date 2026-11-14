# Use one virtual screen while physical monitors are connected

Choose this optional profile for a phone/tablet or remote desktop session that
should use **one prepared virtual screen**, even when two physical monitors are
extended or mirrored. A stream that captures only one member of an extended
desktop can leave windows or the pointer on the other, invisible screen.

During this profile the physical outputs are temporarily removed from the desktop
layout. It is **not** simultaneous independent local and remote use. The normal
profile remains available when you want to keep the physical layout active.

## Create a separate application

First follow [SETUP](SETUP.md): provision a usable DRM-backed reserve, select its
`reserve_connector`, configure the actual Sunshine service/scope and matching
observer video port, then install the current controller release. This option
does not create a virtual monitor or install firmware/drivers.

With streams closed, preview a **new** app:

```sh
/usr/bin/python3 scripts/app_hooks.py \
  --name 'Remote Desktop (Virtual)' --exclusive-reserve
```

Apply after reviewing the preview:

```sh
/usr/bin/python3 scripts/app_hooks.py \
  --name 'Remote Desktop (Virtual)' --exclusive-reserve --apply
```

The helper preserves existing applications and saves a private backup. It refuses
to overwrite an existing name; use a separate name instead of replacing another
app's hooks. Reload Sunshine's application list with streams closed as described
in SETUP, then select **Remote Desktop (Virtual)** in Moonlight. If using the
optional client launcher, set its local `moonlight_app` to this same name.

Without `--exclusive-reserve`, generated apps keep the original behavior: they
preserve physical layouts and resize the reserve only when it is already the
sole output. The new app uses `prepare-remote`; the watcher and ownership token
remain shared with the normal profile.

## Behavior and recovery

- Supports one or multiple physical outputs, including extended or mirrored
  layouts, and an already-exclusive reserve. There is no built-in monitor-count
  rule or connector/GPU inventory.
- Before changing displays, refuses an active lease, capture reconciliation,
  recent video or a connected client. Unavailable/mismatched observer metadata,
  the wrong video port, or an incomplete journal query also refuse the change.
  Journal scope follows the configured Sunshine service.
- Saves the full previous layout **before** selecting the configured reserve
  alone. The selected reserve mode follows requested dimensions and FPS within
  supported modes; it does not invent an unsupported mode.
- Confirms the reserve is exclusive. Preparation errors abort this app and attempt
  rollback, rather than silently continuing with a physical screen.
- On exit, restores the previous layout if the current topology/mode still belongs
  to that session. A newer manual layout or another session's token is preserved.
  Existing bounded recovery/quarantine behavior also applies.

If the host was already on the reserve because of standby, that reserve is the
immediate previous layout; the physical-input policy controls the subsequent
return to physical screens. Do not expect a phone reconnect to renegotiate an
existing stream's dimensions automatically.

## Capture and input limits

The capture backend must follow the sole active reserve after preparation. A
backend pinned to an unavailable physical output might reject capture instead.
Verify usable video on your actual Sunshine/backend before relying on unattended
access. The controller does not change global capture configuration or restart
Sunshine from inside the prepare hook. Current KMS Sunshine has reenumeration and
fallback behavior, but that is not a guarantee for every backend or release.

This profile prevents an extended desktop from placing the pointer on an
uncaptured second screen. It does not change Android/iOS input preferences,
unlock the session, or repair arbitrary input permissions/cursor-plane defects.
For touchpad-style control on a phone, choose the client's touchscreen-as-trackpad
setting; see the [Moonlight input guide](https://github.com/moonlight-stream/moonlight-docs/wiki/Setup-Guide).

One managed session remains the supported contract. A second client resuming an
already-running Sunshine app can share that app without running prep again;
this is not certified multi-user isolation. Close conflicting sessions naturally,
not by killing unrelated clients. See [validation](VALIDATION.md) for exactly what
was tested, and [recovery](RECOVERY.md) for failures.
