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

## Remaining verification

No end-to-end claim is made for boot/GDM, suspend/resume, physical power-button
state, all input devices, multiple GPUs/accounts/streams, HDR or every packaging
format. The event reader was exercised on 64-bit Linux; other ABIs require their
own validation. Input entirely during observer downtime can be lost.

Read [compatibility](COMPATIBILITY.md) and [recovery](RECOVERY.md), provision a
usable reserve output, and perform your own physical return/login check before
relying on unattended access.
