# Sunshine Display Guard

Experimental display automation for **GNOME/Mutter on Linux**, with Sunshine on
the host and Moonlight on the client. Keep a prepared virtual output available
for streaming, preserve physical layouts, and use the selected client's screen
size and orientation.

[Português](docs/README.pt-BR.md) · [Setup](docs/SETUP.md) ·
[Recovery](docs/RECOVERY.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Compatibility and limits](docs/COMPATIBILITY.md) · [Security](SECURITY.md)

## What it does

- Preserves extended, mirrored, portrait, landscape and scaled physical layouts.
- Switches to an **already-provisioned, DRM-backed** reserve output when physical displays
  enter power saving; physical input requests a verified return to the saved layout.
- Adapts an exclusive reserve output to a Moonlight session, without treating a
  mirror group as a single physical monitor. An [optional exclusive profile](docs/EXCLUSIVE-RESERVE.md)
  selects the reserve even with physical monitors connected, restoring the prior layout on exit.
- Serializes display/capture changes with session ownership, including asynchronous
  callbacks and retries. Managed active streams veto topology changes.
- Separates video progress, process identity, logging progress and input coverage.
- Launches Moonlight on a selected logical screen; rechecks orientation and
  connection after the selection dialog.
- Installs immutable releases with producer attestation and rollback on failure.

This is **not a virtual-display driver**. It does not provision DRM outputs,
change boot arguments, install GPU drivers, open firewall ports, pair clients,
unlock sessions or expose a management server. An offline EDID generator is
included, but installing/forcing EDID is a separate hardware-specific operation.

## Before installing

Get Sunshine and Moonlight working first using their upstream instructions:
[Sunshine](https://docs.lizardbyte.dev/projects/sunshine/latest/md_docs_2getting__started.html)
and [Moonlight](https://github.com/moonlight-stream/moonlight-docs/wiki/Setup-Guide).
This project adds display policy; it does not replace their installation or pairing.

Initial target: a GNU/Linux graphical user session with Mutter DisplayConfig,
systemd 237+, Python 3.10+, PyGObject, python-dbus, `/usr/bin/tcpdump`, its package-provided
`tcpdump` account, and optional Zenity for multi-screen selection. Packaging and
permissions vary by distribution. Start with [SETUP](docs/SETUP.md), including
configuration, preview commands, dependencies, hooks and verification.

```sh
# Read-only inspection from a source checkout:
/usr/bin/python3 scripts/moonlight-client.py --list-monitors
/usr/bin/python3 scripts/diagnose.py
/usr/bin/python3 scripts/install.py --user "$USER"   # plan only
```

The example configuration deliberately selects no reserve output and enables no
capture synchronization. Edit your **local** configuration before enabling the
user service. First installation starts only the passive privileged observer;
the display policy is a separate explicit user action.

## Important limits

A connected monitor and DPMS `On` do not prove that its panel is physically on.
A monitor switched off at its button can continue advertising EDID and retain
part of an extended desktop. No DDC panel-power detection is implemented.

One physical monitor works without inventing the missing second monitor. With
no physical monitor, a usable reserve output is required. With no usable output
at all, this utility cannot provide a capture framebuffer. Boot/GDM, suspend,
HDR, multiple GPUs, simultaneous independent streams and all peripheral types
are not certified. Input entirely inside an observer outage can be missed.

The first release is an experimental source release. Automated model/service
boundary tests are distinct from hardware testing; see
[validation](docs/VALIDATION.md) and the [included corrections](docs/CORRECTIONS.md).
The validation page includes real portrait/ultrawide reconnect and journal-EOF
results, with their scope and network-quality limits. No GitHub Actions workflows are enabled by this
project. Maintainers run the local checks before committing and publishing.

## Local checks

Use the system interpreter, because distribution GI/dbus modules are not normally
available in an arbitrary virtual environment. No pip dependencies are needed.

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 tools/check_public.py --tree
```

Test and diagnostic output may contain local paths and connector metadata. Review
it before sharing. Never upload your Sunshine state, Moonlight configuration,
credentials, pairing material, raw journals or local backup directory.

## License

MIT. Sunshine and Moonlight remain separate upstream projects with their own
licenses. Their names identify interoperability; this is not an official release
of either project.
