# Corrections included in the public code

These are behavioral guarantees exercised by the regression suite, not a claim
of universal hardware support. Host names, connectors, service scope and ports
belong in local configuration; deployment-specific values are not published.

| Failure class | Included correction | Regression evidence |
| --- | --- | --- |
| Mirror group mistaken for an exclusive reserve | Exclusivity requires one logical group with one member; preserve remaining mirror members and newer manual layouts. | `test_sunshine_regressions.py`, `test_sunshine_layout.py` |
| Session ownership checked outside the mutation transaction | Policy, hooks, asynchronous primary sync and restart retries share a reentrant lock. Active lease/video defers sync before writes; one retry timer preserves forced refresh. | `test_sunshine_regressions.py`, `test_sunshine_observer_update.py` |
| Live watcher PID keeps a stale session indefinitely | Video progress is independent of PID/logging; process identity and bounded grace control recovery. | `test_sunshine_regressions.py` |
| Physical input discarded during display settling | Latch confirmed physical input through settling and active ownership; simultaneous input/power-save wakes the existing physical layout. | `test_sunshine_regressions.py`, `test_desktop_policy.py` |
| Capture restart intent lost across consumer restart | Persist reconciliation intent before replacing capture configuration and retry after process restart. | `test_sunshine_regressions.py`, `test_display_awake.py` |
| Client screen changes while selection dialog is open | Requery orientation, dimensions and connection before launch; reject a removed target. | `test_sunshine_regressions.py`, `test_moonlight_client.py` |
| Invalid process/lease data crashes recovery | Validate numeric types, PID range and process start identity; bound lease JSON to 64 KiB and quarantine invalid state. | `test_sunshine_session.py`, `test_sunshine_regressions.py`, `test_generic.py` |
| Healthy heartbeat masks unreadable input devices | Report eligible/open/error counts and scan age; distinguish ready, legitimately empty, degraded and unknown coverage. Retry hotplug/access failures and clean stale axis state. | `test_sunshine_observer_update.py` |
| Upgrade leaves old producer running | Use immutable releases, explicit producer restart, source/PID/boot/coverage attestation and rollback before restarting consumers. | `test_install.py`; real observer install/upgrade smoke tests |
| Dead journal process or EOF ends a healthy stream | Continue bounded packet-health checks; unregister EOF to avoid descriptor spin and limit partial log-line buffering. | `test_generic.py`, `test_sunshine_regressions.py`; real-session results in [validation](VALIDATION.md#real-session-follow-up) |
| Generic user service queried as a system service | Select the matching journal scope and trusted invocation field without requiring the newer invocation CLI option. | `test_generic.py`; real user-journal marker probe |
| Unsafe generic configuration or privileged paths | Strict settings, private regular credential files, preview defaults, no-follow locks, owner/permission checks, protected masks and managed release targets. | `test_generic.py`, `test_install.py` |

A later comparison against the operational backport found matching critical
layout, lease, input-coverage and watcher logic. The watcher's journal arguments
are intentionally different: the public version supports configurable service
scope and invocation filtering. Machine-specific deployment scripts are not
copied over the generic installer.

See [validation](VALIDATION.md) for modeled versus real evidence and
[compatibility](COMPATIBILITY.md) for limits that remain.
