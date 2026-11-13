# Security and privacy

The observer needs raw packet capture and access to physical input devices. It
is privileged, uses a restricted systemd unit, drops tcpdump privileges to the
package-provided account, and stores only timestamps/counters/instance metadata.
This is meaningful privilege: review the unit and source before installation.
It does not log keystrokes, packet payloads, peer addresses or display serials.
It never sends telemetry.

The user policy changes display topology and can write Sunshine's selected
capture output. When explicitly enabled it authenticates to a pinned local
HTTPS restart endpoint. The local self-signed certificate is accepted; no
remote API endpoint can be supplied. Credentials are local mode-0600 files,
never command arguments, release contents or tracked examples.

Root release files and units must remain administrator-owned and not writable by
other users. Do not run arbitrary repository scripts as root before reviewing
them. The installer validates Python syntax and source identity, not trust in a
third-party fork. One designated graphical account and the configured hooks are
the supported ownership boundary.

The app helper preserves private backups and refuses name collisions and symlinked
apps configuration. External Sunshine UI writers do not share its lock; close
the UI while applying the change. Its last-minute comparison narrows the race,
but does not turn apps.json into a transaction shared with arbitrary writers.

Report suspected vulnerabilities through GitHub's private vulnerability reporting
feature when available. Do not post secrets or remote-access material in a public
issue. Review diagnostic output before sharing. The MIT warranty disclaimer
applies; unsupported display/driver changes can remove local access.

The runtime heartbeat is readable by local users so unprivileged consumers can
use it. Its timestamps reveal host activity/presence even though event contents
are absent. The initial deployment contract is one designated graphical account;
this is not a privacy-isolation mechanism between mutually untrusted local users.
