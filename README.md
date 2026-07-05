# drivekit

A free disk toolkit for the Mac (recovery works on Linux too). Run it as
`drivekit` or the short alias `dk`.

Mount **NTFS (read/write)** and **ext2/3/4** external drives, verify/repair/format
disks, and **recover deleted or lost data** — all with free open-source engines.
A free replacement for Paragon NTFS/extFS and Disk Drill / EaseUS.

Verified on macOS 15 (Sequoia), July 2026.

Everything mounts under `/Volumes` like a normal disk, so drives show up
**in Finder** (and to every app) — the tool is only the on/off switch, not a
gateway you browse files through.

## Feature parity with Paragon

| Paragon feature | dk | How |
|---|---|---|
| NTFS read/write | ✅ `dk mount` | ntfs-3g (same engine Paragon competes with) |
| Auto-mount r/w on plug-in | ✅ `dk automount enable` | root LaunchDaemon + ntfs-3g |
| Read-only mode | ✅ `dk mount --ro` | native driver |
| Verify / repair | ✅ `dk check` / `repair` | ntfsfix, e2fsck |
| Format NTFS / ext4 / exFAT / FAT32 | ✅ `dk format` | mkntfs, mke2fs, diskutil |
| Volume label editing | ✅ `dk label` | ntfslabel, e2label |
| Volume info | ✅ `dk info` | ntfsinfo, dumpe2fs |
| ext2/3/4 read | ✅ | ext4fuse |
| **ext4 write** | ⚠️ read-only | no reliable free driver exists (see below) |
| Menu-bar GUI | ❌ CLI by design | — |
| Boot from NTFS / startup disk | ❌ | needs a proprietary boot-time kext |
| Deep NTFS repair (chkdsk-level) | ⚠️ partial | only Windows chkdsk can; `repair` fixes journal/dirty flag & schedules chkdsk |

Bonus tools installed with the stack (CLI): `ntfsclone` (backup/clone),
`ntfsresize`, `ntfsundelete` (recover deleted files), `resize2fs`, `tune2fs`.

## Install

```sh
./install.sh         # links `dk` onto your PATH + installs the driver stack
```

Then one manual step (once): approve **macFUSE** when macOS asks
(System Settings → Privacy & Security), or for kext-free manual mounts enable it under
General → Login Items & Extensions → **File System Extensions**.

## Use

```sh
dk list                  # what's plugged in
dk mount                 # mount everything (NTFS read-write)
dk mount --ro disk4      # read-only session
dk unmount               # then unplug — only after "Safe to unplug"
dk automount enable      # Paragon-style: NTFS auto-mounts r/w on plug-in
dk check disk4s1         # verify filesystem (no changes)
dk repair disk4s1        # fix dirty NTFS volume / full ext fsck
dk label disk4s1 BACKUP  # rename volume
dk format disk4 ntfs "My Disk"   # DESTRUCTIVE — asks for confirmation
dk info disk4s1          # detailed filesystem info
dk remove-paragon        # cleanly strip a Paragon NTFS install/leftovers
```

`mount`, `unmount`, etc. accept `diskX` (whole disk) or `diskXsY` (one
partition). Destructive commands require typed confirmation (`--yes` to skip
in scripts). Most commands use `sudo` and will ask for your password.

## Drive tools

```sh
dk health disk4               # SMART check — is this drive failing? (works on internal too)
dk benchmark disk4            # sequential read speed (add --write to also test writes)
dk clone disk4 -o ~/disk.img  # image a disk/partition (or: dk clone disk4 -o disk5 to another disk)
dk partition list disk4       # show the partition layout
dk partition shrink disk4s1 200G   # shrink a partition (DANGEROUS — see below)
dk partition grow disk4s1     # grow into free space right after it
dk partition create disk4 ext4 DATA   # new partition in free space
dk partition delete disk4s2   # remove a partition
```

**`health`** reads SMART data and gives a plain verdict — `OK`, `WARN` (e.g. cable
CRC errors, or an SSD past 90% wear), or `FAILING` (reallocated/pending/uncorrectable
sectors). If a USB enclosure blocks SMART it says so rather than guessing. A `FAILING`
verdict tells you to `dk clone` it immediately.

**`clone`** uses `ddrescue`, so it's resumable and safe on flaky drives. Disk-to-image
is non-destructive; disk-to-disk erases the target and asks first (with a size check).

**`partition` is the most dangerous command in the tool.** Resizing keeps your data,
but a crash or power loss mid-resize can lose the whole partition. It enforces:
external disks only, unmounts first, filesystem check must pass, prompts you to
`dk clone` a backup first, shows the exact sector changes, and requires typed
confirmation. It only grows into free space *immediately after* a partition (it won't
move or merge partitions — those are refused). ext resize is fully supported; NTFS
resize needs the ntfs stack installed. Validated on scratch images with checksums
proving data survives a shrink-and-grow round-trip.

## Data recovery (deleted files & formatted disks)

A free alternative to Disk Drill / EaseUS (~$90+). Those apps are mostly polished
wrappers around the same open-source engines this uses: **The Sleuth Kit**
(metadata undelete), **PhotoRec** (signature carving), **GNU ddrescue** (imaging
failing drives). Works on macOS **and Linux**. Recovery pipelines were validated
end-to-end on scratch disk images with byte-for-byte checksum matches before shipping.

```sh
dk recover deps --install         # one-time: install the engines
dk recover scan  disk4s1          # list deleted files still recoverable by name
dk recover files disk4s1 -o ~/rescued   # recover them (keeps names/folders)
dk recover carve disk4s1 -o ~/rescued   # deep scan for formatted/damaged disks (names lost)
dk recover image /dev/disk4 -o ~/disk.img   # failing drive? image it FIRST, recover from the image
```

On Linux the source is a device like `sdb1` or `/dev/nvme0n1p2` (see `lsblk`);
on macOS it's `disk4s1` (see `dk list`) or any image file.

**Which command:** `scan`/`files` when a file was just deleted and the disk is
healthy (fast, restores names). `carve` when the disk was formatted, the
filesystem is damaged, or it's ext4 (whose deletes wipe the file's location
metadata — carving is the only real option; names are lost). `image` first,
always, if the drive is clicking or throwing I/O errors.

**Safety built in:** the source is only ever opened read-only; the tool refuses
to recover onto the same disk it's reading (that would overwrite what you're
saving); and it warns before scanning a mounted volume.

**Honest limits — read before spending hours:**
- **Stop using the affected disk immediately.** Every write can overwrite the
  data you want back.
- **Internal Mac SSD (APFS):** a deleted file is almost always *physically gone*
  within minutes (TRIM zeroes freed space) — no tool, free or $500, recovers it.
- **External USB SSDs, HDDs, USB sticks, SD cards:** macOS doesn't TRIM these, so
  recovery odds are **good** until the space is reused.
- **Quick format:** very recoverable (NTFS especially). **Full format** writes
  zeros — nothing survives.
- Carving recovers file *contents*, not names/folders, and produces some false
  positives you sort through.

## ext4 write support

There is **no reliable free ext4 write driver for macOS** (the one thing paid
tools genuinely add). Options, in order of safety:

1. Mount read-only with `dk mount` and copy files off.
2. Write sessions via a Linux VM: [UTM](https://mac.getutm.app/) (free) with
   the **QEMU backend** passes the USB drive to a Linux guest which mounts
   ext4 natively read/write.
3. Experimental: build `fuse2fs` from e2fsprogs source against macFUSE; if
   found on PATH, `dk mount` uses it for r/w ext mounts (after an
   automatic `e2fsck`, refusing if errors remain). Flaky — keep backups.

If you'll write to the disk from the Mac regularly, the pragmatic move is
`dk format diskX exfat` (after copying data off) — exFAT works natively
on macOS, Windows, and Linux.

## Automount details

`dk automount enable` installs a root LaunchDaemon
(`/Library/LaunchDaemons/com.drivekit.automount.plist`) plus a root-owned copy
of the script at `/usr/local/libexec/drivekit-automountd`. It wakes on disk
events (`diskutil activity` used purely as a wake-up signal), re-reads
authoritative state from `diskutil info`, and mounts any unmounted NTFS
partition read-write. Log: `/var/log/drivekit-automount.log`. The daemon needs
the macFUSE **kext** backend (FSKit is per-user and unavailable to daemons).
`dk automount disable` removes everything.

## Troubleshooting

- **Drive doesn't appear in `dk list` at all** → not a filesystem problem.
  Check cable/port and `system_profiler SPUSBDataType`. Spinning 2.5" HDDs can
  fail on low-power hubs — plug directly into the Mac.
- **Paragon NTFS installed or left over** → it intercepts NTFS drives before
  dk can (and when its trial expires, disks may stop mounting at all —
  they look "undetected"). `dk doctor` detects it; `dk remove-paragon`
  removes it using Paragon's own uninstaller plus leftover cleanup. Reboot after.
- **NTFS volume won't mount, "dirty" errors** → unclean Windows shutdown/unplug:
  `dk repair diskXsY`, or plug into Windows once and eject properly.
- **"Journal needs recovery" on ext** → `dk repair diskXsY` (runs e2fsck).
- **NTFS mounts read-only by macOS before you run `dk mount`** — expected;
  the tool replaces Apple's read-only mount with a read-write one.
