# Validation and release scope

This is an experimental source release, not certification of all display,
compositor or GPU combinations. The public project starts with a clean history;
no deployed-machine configuration, private history or raw hardware logs are part
of this repository.

## Evidence used before the initial publication

- Automated regression tests exercise layout normalization, mirror-member order,
  token/process/invocation ownership, bounded recovery, physical-input coverage,
  asynchronous callbacks, lost logs and journal-process EOF, client requery,
  strict configuration, private credentials, EDID checksums and clock ceilings.
- Installer tests execute actual file copies, immutable release pointers and
  rollback against a fake service boundary. They cover first install, existing
  service upgrade, failure of producer/consumer start, active video, masks,
  unsafe permissions, symlinked locks and corrupted releases.
- A real privileged first install and upgrade attested a new observer PID,
  instance, source hash and healthy input coverage. The generalized display
  policy remained inactive; the existing controller was preserved. The observer
  smoke-test service was disabled afterward.
- Real Mutter inventory/diagnostics were read without applying a layout. A
  predecessor operational profile exercised nine physical-layout transitions
  and headless portrait/ultrawide streams. That is historical evidence for the
  shared core, not a claim that every generalized configuration was hardware-tested.
  The nine completed layouts were portrait extension, portrait alone, landscape
  alone, landscape extension, stacked, mirrored, scaled mirror, mixed scales,
  and a mirror with the reserve output listed first. Each returned from reserve
  to its normalized physical layout. Input timestamps were controlled in this
  transition campaign; they were not nine human-observed login/wake tests.
- In a separate real-stream check, the watcher's journal child was paused while
  video stayed healthy beyond 55 seconds; after the client disconnected, bounded
  video-health cleanup restored the prior reserve mode. A paused reader and a
  reader that has exited are distinct cases; the later EOF follow-up below
  exercises the latter.
- A deterministic before/after witness reproduced early watcher exit when its
  journal process was already dead. The hardened watcher retained bounded
  packet-health checks. Regression tests also cover EOF without descriptor spin.
- Public-content checks run over the candidate tree, staged contents and reachable
  history, including author/committer metadata. A separate private denylist was
  used locally and is not distributed. These checks supplement manual review;
  they are not a mathematical proof that arbitrary future content is secret-free.

The exact reviewed Git revision identifies the source snapshot. Changes after
review require repeating the relevant checks. No CI badge is used because no
remote workflow is enabled. Run the local commands in the README for current
results; test counts may grow independently of hardware coverage.

## Real-session follow-up

The operational backport was subsequently exercised with real Moonlight streams
on 13 November 2026, after the initial publication. The public code already
contained the relevant EOF/packet-health correction and bounded lease parsing;
this update records new evidence rather than a missing code patch.

The client selected a portrait screen and an ultrawide landscape screen. Each
orientation had an initial connection/disconnection and a reconnection. On each
reconnection, only the test watcher's journal child was terminated; its parent
watcher and stream remained active beyond the initial 45-second grace period.

| Complete case | Requested stream | Healthy checkpoint since prepare | Lease release and layout restoration after client exit |
| --- | --- | --- | --- |
| Portrait, initial | 1080×1920 at 60 FPS | 9.08 s | 0.43 s |
| Portrait, reconnect with journal child terminated | 1080×1920 at 60 FPS | 53.11 s | 21.63 s |
| Landscape, initial | 2560×1080 at 50 FPS | 7.87 s | 0.42 s |
| Landscape, reconnect with journal child terminated | 2560×1080 at 50 FPS | 54.31 s | 21.29 s |

The host returned automatically to its pre-test 1024×768 reserve layout after
every complete case. Client physical layout was unchanged. Stream window bounds
matched the selected screen; decoder and renderer statistics confirmed actual
frames, not just a negotiated connection. Reconnection decoding rates were
59.63 and 49.91 FPS, with rendering rates of 59.53 and 48.18 FPS respectively.
These are observations from short sessions, not performance guarantees.

The approximately 21-second cleanup without a journal is the video-health timeout
plus polling. Normal disconnects with logs available cleaned up in about 0.4 s.
The same ownership token and watcher process remained active at the healthy
checkpoints; no manual host-layout restore was used to make the cases pass.

An independent SSH control remained connected throughout each test run. Protected
streaming, observer and SSH services retained their process/invocation identity.
Only test-owned clients and journal children were closed. Temporary test
preferences and idle inhibition were restored. No existing client was displaced.

Two instrumentation attempts were aborted safely before completing the campaign:
an AppImage helper in a separate process group was initially misclassified as a
foreign client, and a later collector expression had an extra parenthesis. The
harness was corrected to identify its own processes explicitly, and the incomplete
case was rerun. Only the four complete cases above count as passing.

Network quality was not perfect: reported jitter drops ranged from 0.16% to 3.87%,
and the landscape reconnection reported 0.44% network frame loss. This did not
break session ownership or restoration, but may affect perceived smoothness.

This validates the shared session/backport behavior in an operational profile.
It does **not** mean the entire generalized public controller was activated and
hardware-certified. The generalized observer installer has its separate real
install/upgrade smoke evidence; the isolated generic-policy campaign below supplies separate end-to-end
evidence for its stated environment. No human observation of physical panel power or login is
claimed. Deployment inventories, raw logs, connection data and full evidence
remain outside this public repository; only the de-identified summary is included.

## Isolated generic-controller end-to-end follow-up

A separate campaign on 13 November 2026 exercised the public controller itself,
including its configuration, installer, observer, active user policy, capture
synchronization/API restart, generated application hooks and client launcher.
The host was a disposable KVM/QEMU guest with Ubuntu 24.04, GNOME/Mutter 46.2 on
X11, a virtio GPU with three guest DRM connectors and Sunshine
2026.914.233613 using X11 capture and software H.264 encoding. A reserve mode
for each tested orientation was provisioned before testing.

Moonlight 6.2.0 ran with fresh pairing/settings in a separate headless
GNOME/Mutter 50.1 session, using its own session bus, runtime directory and
Xwayland display. Its portrait and landscape screens were **virtual test
screens**, not the user's physical panels. Both display authorities were
separate from the operational compositor; no second policy was started against
that compositor. This is real video streaming/decoding on isolated graphics
sessions, not human observation of physical panels or a hardware-performance
certification.

The initial public code failed a real X11 layout apply with `Can't set layout
mode`: it sent `layout-mode` merely because Mutter reported the current value.
Mutter's separate `supports-changing-layout-mode` capability must permit that
property. The correction omits it on fixed-layout backends while preserving the
reported mode for normalization. A new regression fails on the earlier implementation and passes with the
correction; a second test covers changeable backends. The complete suite passes
183 tests.
See the [Mutter interface contract](https://github.com/GNOME/mutter/blob/46.2/data/dbus-interfaces/org.gnome.Mutter.DisplayConfig.xml).

All nine installed controller modules matched the corrected public source byte
for byte. Four complete streams then passed:

| Case | Stream requested | Decoded / rendered FPS | Healthy checkpoint since prepare | Restoration after client exit |
| --- | --- | --- | --- | --- |
| Portrait, initial | 1080×1920 at 30 FPS | 30.27 / 30.13 | 14.64 s | 0.21 s |
| Portrait, reconnect with journal EOF | 1080×1920 at 30 FPS | 30.09 / 30.04 | 54.05 s | 21.19 s |
| Landscape, initial | 2560×1080 at 30 FPS | 30.34 / 30.11 | 13.32 s | 0.21 s |
| Landscape, reconnect with journal EOF | 2560×1080 at 30 FPS | 30.08 / 30.03 | 55.00 s | 20.47 s |

Window dimensions and bounds matched the selected isolated screen. Each case
restored the exact prior reserve layout and mode. On both EOF cases, only the
owned journal child was terminated; the same watcher process and token retained
the live video lease beyond the initial grace period. Packet timestamps and
actual decoder/render statistics supplied separate evidence. The approximately
21-second EOF cleanup is the bounded packet-health timeout, not an immediate
log-based disconnect. These short, 30-FPS software-encoding sessions are not
60-FPS, ultrawide-refresh or throughput benchmarks.

Additional real guest checks passed:

- First installation, corrected-release upgrade and readiness attestation with
  healthy input coverage and matching observer source/video port.
- An attempted installation during an active stream was refused before replacing
  the observer; its PID/instance and the active session token remained unchanged.
- Standby selected the reserve and reconciled Sunshine capture. QEMU input events
  delivered through guest PCI input devices advanced the observer's physical-input
  timestamp and restored the confirmed single-monitor, mirrored and extended
  layouts. Tests did not write synthetic timestamps into the observer JSON.
- Simulated disconnection of both physical-role guest DRM outputs left only the
  reserve available and usable. The fixture explicitly refreshed XRandR after
  changing guest connector status; this does not certify real cable hotplug or
  physical monitor power-button behavior.

Protected operational service identities, configuration hashes and compositor
layout were checked throughout the isolated streaming campaign. No operational
service, pairing profile or display layout was replaced by this test. Test-owned
clients, compositor and guest were closed afterward. Detailed evidence and local
fixtures remain outside the public repository; only this de-identified summary
is published.

## Remaining verification

No end-to-end claim is made for boot/GDM, suspend/resume, physical power-button
state, all input devices, multiple GPUs/accounts/streams, HDR or every packaging
format. The event reader was exercised on 64-bit Linux; other ABIs require their
own validation. Input entirely during observer downtime can be lost.

Read [compatibility](COMPATIBILITY.md) and [recovery](RECOVERY.md), provision a
usable reserve output, and perform your own physical return/login check before
relying on unattended access.
