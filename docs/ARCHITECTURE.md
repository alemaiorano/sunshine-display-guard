# Architecture and ownership

The privileged observer reads physical Linux input event devices and outgoing
UDP packet metadata for one configured video source port. It publishes only
boot/instance/source identity, timestamps and input-coverage counters in a
root-owned runtime directory. Event codes, key values, payloads and peer
addresses are not written to that JSON. Sunshine-created virtual input devices
are excluded by their sysfs path; Bluetooth UHID paths remain eligible.

The unprivileged policy uses Mutter DisplayConfig, the idle monitor, a normalized
saved layout and a single per-user transaction lock. It detects connected and
active outputs, not the physical power button. On standby it preserves a
confirmed physical layout before selecting the reserve; confirmed input latches
a return request. A live stream lease vetoes topology changes. Input coverage
can be ready, legitimately empty, degraded or unknown. Degraded input falls back
to compositor idle; that fallback can misclassify synthetic activity.

Prepare writes rollback intent before a mode mutation. A reserve is exclusive
only when one logical group has one member; the first member of a mirror does
not imply exclusivity. A watcher binds its token to the Sunshine invocation,
PID and process start identity. Logging, packet progress and PID liveness are
separate signals. A dead/EOF journal cannot end a healthy video lease; packet
health and bounded grace continue without spinning on the dead descriptor.

The same reentrant lock covers policy ticks, hooks, primary-output configuration
and API restart retries. A new session cannot enter while capture reconciliation
is pending. A deferred asynchronous sync preserves its forced-refresh request
and uses one timer. Settings are fixed for a process lifetime; restart affected
services with streams closed after changing configuration.

Physical layouts are per-user state. Mode changes are temporary Mutter changes;
the utility does not replace GNOME's persistent display settings. New manual
layouts and mirrors are preserved rather than overwritten by an older session's
restore. Recovery failures are retried boundedly and quarantined with evidence.

Installation uses one global maintenance lock, the designated user's display
lock and immutable root-owned releases. It stops active consumers, switches the
current release, restarts/attests the observer and only then restarts consumers.
Previous releases and private root unit backups remain for rollback. The initial
release targets one graphical account; coordination among multiple independent
user sessions is not certified.

Journal selection respects user versus system service scope and uses the trusted
application invocation field. It does not require the newer --invocation option.
See [journalctl](https://www.freedesktop.org/software/systemd/man/latest/journalctl.html)
and [journal fields](https://www.freedesktop.org/software/systemd/man/latest/systemd.journal-fields.html).

The optional exclusive-reserve app uses the same lock and watcher with a
`prepare-remote` entry point. It checks configured-scope journal and fresh,
source/port-matching observer data before recovery/mutation, snapshots the full
layout, selects only the reserve and confirms the result. Its lease includes
rollback and an explicit boolean mode marker. Default prep does not force this
transition. Capture-backend reenumeration remains an upstream prerequisite;
see [exclusive reserve](EXCLUSIVE-RESERVE.md).
