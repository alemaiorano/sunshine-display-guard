# Contributing

Use `/usr/bin/python3` with distribution GI/dbus bindings. Run the unit suite and
`tools/check_public.py --tree` before a commit; scan `--index` before committing
and `--history` before pushing. Keep generated configs, logs, private fixtures,
credentials, state and hardware inventories outside the repository.

Preserve token ownership, lock reentrancy and bounded retries when changing
policy. Test user/system Sunshine service scopes, generic connectors, headless
operation, mirror order, physical-input coverage and rollback. Model tests do
not certify a new GPU/compositor; report the distinction.

No package installation, privileged system changes, reboot or logout should be
an implicit effect of tests. Tests use isolated filesystem/service boundaries.
Root installation needs explicit `--apply`. Never silently broaden backend or
hardware claims based only on tests with mocks.

GitHub Actions stays disabled unless maintainers explicitly authorize a change.
No workflow or scheduled job is part of this source release. Publish a reviewed
commit, not a directory with unknown history or generated artifacts.
