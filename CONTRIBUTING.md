# Contributing to drivekit

Thanks for helping out. drivekit is a single Bash script (`drivekit`, run as `dk`)
plus a small Python recovery module.

## Before you open a PR

- Run `shellcheck drivekit install.sh` and `bash -n drivekit`. Both must be clean.
- Match the surrounding style. The script uses the `ok` / `warn` / `err` / `die`
  helpers and the `have` command check. Keep comments to a line where they earn it.
- Test disk-touching changes on a scratch USB stick or a disk image, never on a
  drive holding data you care about. The destructive paths (`format`, `partition`,
  `clone`) must keep their typed confirmation.
- Keep commit messages to one imperative line ("add", "fix").

## Branches

Work on a feature branch and open a PR against `main`. Don't push to `main` directly.

## Scope

drivekit wraps the free filesystem tools behind one command. A new command should
wrap an existing open-source engine rather than reimplement it.
