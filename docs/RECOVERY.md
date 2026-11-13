# Recovery, upgrade and removal

Keep independent access during first setup. No recovery action here unlocks a
session or bypasses authentication.

## Stop automated changes

From the graphical user's session:

```sh
systemctl --user disable --now sunshine-display-guard.service
```

Choose your physical layout using GNOME Displays. The passive observer can remain
running while investigating; it does not apply layouts. To stop it as well:

```sh
sudo systemctl disable --now sunshine-display-guard-observer.service
```

Use the JSON-only `diagnose.py` output first. It omits credentials, host addresses
and display serials. Do not upload full Sunshine journals, apps.json backups or
Moonlight settings; they may contain local identifiers or secrets.

## Pending or orphaned sessions

Close the managed stream before changing state. Runtime files are in
`$XDG_RUNTIME_DIR/sunshine-display-guard`; the lease contains ownership, process
identity and rollback intent. Do not delete an active lease to force a topology
change. Check its process/service ownership and let bounded recovery run.

With the stream definitely stopped, the session helper's `restore` action can
attempt guarded recovery. It preserves a newer manual layout if the old target
no longer matches. Quarantined `.invalid-*` or `.recovery.json` files are evidence,
not proof that the previous physical state was restored.

## Upgrade and rollback

Close streams and run the new installer's preview, then `--apply`. It retains
previous immutable releases and root-owned unit backups under
`/usr/local/lib/sunshine-display-guard/backups`. Automatic rollback handles an
installation failure; a failed rollback is reported and needs operator review.

For manual rollback, stop the user policy and observer, review the backup's
`state.json` and unit files, restore the previous managed `current` symlink and
units, reload both system and user managers, then restart the prior services.
Do not guess a previous version or delete releases before checking dependencies.
No automatic pruning discards recovery evidence.

## Undo the app entry / remove installed units

Stop streams first. Remove only the separately named Display Guard application
using Sunshine's UI. If restoring a private apps.json backup manually, compare
newer entries first so later changes are not discarded.

After stopping/disabling both project services, an administrator may remove the
project's two unit files from `/etc/systemd/system` and `/etc/systemd/user`, then
reload the respective systemd managers. Retain releases/backups and user state
until any unique recovery evidence is preserved. Credentials belong to the
user; the installer never copies or deletes them. No kernel/firmware changes
need undoing because this installer does not make them.
