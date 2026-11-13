# Project instructions

Read README.md, docs/SETUP.md, docs/ARCHITECTURE.md and SECURITY.md before changes.
Keep host/user/service/port settings in validated local configuration. Never add
credentials, pairing state, real machine inventories or raw diagnostic logs.

Preview privileged operations by default. Preserve rollback evidence. Do not
reboot, log out, alter firmware or manipulate physical outputs as routine tests.
Use system Python for GI/dbus. Run unit tests and public-content checks before
commits; inspect history and author metadata before publication. GitHub Actions
is disabled unless explicitly authorized. Report modeled, hardware-tested and
unverified cases separately; do not promise universal monitor support.
