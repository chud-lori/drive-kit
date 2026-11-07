# Security policy

drivekit runs with `sudo` and writes to raw block devices, so a bug can destroy
data. If you find a security issue, please report it privately rather than opening
a public issue.

## Reporting

- Open a private advisory from the repository's **Security** tab ("Report a
  vulnerability"), or
- Contact the maintainer, @chud-lori, through GitHub.

Please include your `dk --version`, your OS, the command you ran, and what happened.
You can expect a reply within a few days.

## Scope

This policy covers drivekit itself: the `drivekit` script, `install.sh`, and the
recovery module. Issues in the underlying tools (ntfs-3g, e2fsprogs, anylinuxfs,
and so on) belong with those projects.
