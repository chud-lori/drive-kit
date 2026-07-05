#!/usr/bin/env python3
"""
dk recover — free data recovery for deleted files and formatted disks.

Works on macOS and Linux. Orchestrates proven open-source engines:
  - The Sleuth Kit (fls/icat/tsk_recover/mmls) : filesystem-metadata undelete
  - PhotoRec                                   : signature carving (formatted/damaged disks)
  - GNU ddrescue                               : imaging failing drives safely

Recovery pipeline validated end-to-end on scratch images (exFAT/FAT32/ext4,
checksum-verified) before this tool was written around it.

Golden rules enforced here:
  1. The source is only ever opened read-only.
  2. Recovered data must NEVER be written to the disk it came from.
  3. For failing hardware: image first (ddrescue), recover from the image.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys

IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

# Homebrew keg-only / sbin locations (macOS); harmless on Linux
EXTRA_PATHS = [
    "/opt/homebrew/bin", "/opt/homebrew/sbin",
    "/usr/local/bin", "/usr/local/sbin",
    "/opt/homebrew/opt/e2fsprogs/sbin", "/usr/local/opt/e2fsprogs/sbin",
]
os.environ["PATH"] = os.environ.get("PATH", "") + ":" + ":".join(EXTRA_PATHS)

BOLD, DIM, RED, GRN, YEL, OFF = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def ok(msg):   print(f"{GRN}✔{OFF} {msg}")
def warn(msg): print(f"{YEL}!{OFF} {msg}")
def err(msg):  print(f"{RED}✘{OFF} {msg}", file=sys.stderr)
def die(msg, code=1):
    err(msg)
    sys.exit(code)


def have(tool):
    return shutil.which(tool) is not None


def run(cmd, sudo=False, capture=True, check=False, stdout_to=None, cwd=None):
    """Run a command; prefix sudo when reading raw devices as non-root."""
    if sudo and os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    if stdout_to is not None:
        with open(stdout_to, "wb") as fh:
            return subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, check=check, cwd=cwd)
    return subprocess.run(cmd, capture_output=capture, text=True, check=check, cwd=cwd)


def needs_sudo(src):
    return src.startswith("/dev/")


# ---------------------------------------------------------------- source prep

def normalize_source(src):
    """Validate the source (device or image file); return path to use."""
    if src.startswith("/dev/"):
        if IS_MAC and re.fullmatch(r"/dev/disk\d+(s\d+)?", src):
            # raw node is much faster for sequential forensic reads
            return src.replace("/dev/disk", "/dev/rdisk", 1)
        return src
    if re.fullmatch(r"disk\d+(s\d+)?", src) and IS_MAC:
        return "/dev/r" + src
    if re.fullmatch(r"sd[a-z]\d*|nvme\d+n\d+(p\d+)?", src) and IS_LINUX:
        return "/dev/" + src
    if os.path.exists(src):
        return os.path.abspath(src)
    die(f"Source not found: {src} (give a device like "
        + ("disk4s1" if IS_MAC else "sdb1") + " or a path to an image file)")


def whole_disk_id(dev):
    """Reduce a device node to its physical-disk identifier, cross-platform.
       /dev/rdisk4s1 -> disk4 ; /dev/sdb1 -> sdb ; /dev/nvme0n1p2 -> nvme0n1"""
    d = re.sub(r"^/dev/r?", "", dev)
    if IS_MAC:
        return re.sub(r"(s\d+)+$", "", d)   # disk4s1 -> disk4 ; disk3s1s1 -> disk3
    if re.match(r"(nvme\d+n\d+|mmcblk\d+|loop\d+)p\d+$", d):
        return re.sub(r"p\d+$", "", d)
    return re.sub(r"\d+$", "", d)


def mount_pairs():
    """[(device, mountpoint)] parsed from mount(8), macOS and Linux formats."""
    pairs = []
    for line in run(["mount"]).stdout.splitlines():
        m = re.match(r"^(\S+) on (.+?) (?:type \S+ )?\(", line)
        if m:
            pairs.append((m.group(1), m.group(2).rstrip("/") or "/"))
    return pairs


def disk_of_path(path):
    """Which physical disk a (possibly not-yet-existing) path lives on."""
    path = os.path.abspath(path)
    best = None
    for dev, mp in mount_pairs():
        under = path == mp or mp == "/" or path.startswith(mp + "/")
        if under and (best is None or len(mp) > len(best[1])):
            best = (dev, mp)
    return whole_disk_id(best[0]) if best else None


def guard_output_dir(outdir, src):
    """Rule 2: never recover onto the source disk itself. Decide BEFORE creating."""
    outdir = os.path.abspath(outdir)
    if src.startswith("/dev/"):
        src_disk = whole_disk_id(src)
        if disk_of_path(outdir) == src_disk:
            die(f"Output dir {outdir} is on the SAME disk you are recovering from ({src}).\n"
                f"  Writing there can overwrite the very data you want back. Choose another disk\n"
                f"  (e.g. your internal drive: -o ~/rescued).")
    os.makedirs(outdir, exist_ok=True)
    return outdir


def unmount_hint(src):
    """Recovering from a mounted, in-use volume risks the OS overwriting freed space."""
    if not src.startswith("/dev/"):
        return
    dev = src.replace("/dev/rdisk", "/dev/disk", 1) if IS_MAC else src
    src_disk = whole_disk_id(src)
    # catch both the exact device and any partition of the same physical disk
    mounted = [d for d, _ in mount_pairs() if whole_disk_id(d) == src_disk]
    if mounted:
        warn(f"{dev} (or a partition of it) is currently MOUNTED. Every write to it can destroy deleted data.")
        warn("Strongly consider unmounting first: "
             + (f"diskutil unmountDisk {dev}" if IS_MAC else f"umount {dev}"))


# ---------------------------------------------------------------- TSK layer

def mmls_partitions(src):
    """Return [(start_sector, description)] or [] when no partition table."""
    r = run(["mmls", src], sudo=needs_sudo(src))
    if r.returncode != 0:
        return []
    parts = []
    for line in r.stdout.splitlines():
        m = re.match(r"^\s*\d+:\s+(\S+)\s+(\d+)\s+\d+\s+\d+\s+(.*)$", line)
        if not m:
            continue
        slot, start, desc = m.group(1), int(m.group(2)), m.group(3).strip()
        if slot in ("Meta",) or slot.startswith("---") or "Table" in desc or desc == "Unallocated":
            continue
        parts.append((start, desc))
    return parts


def offsets_for(src, offset_flag):
    """Which partition offsets to inspect."""
    if offset_flag is not None:
        return [(offset_flag, "user-specified offset")]
    parts = mmls_partitions(src)
    return parts if parts else [(0, "whole source (no partition table)")]


DELETED_RE = re.compile(r"^(?P<type>[-\w]+/[-\w]+)\s+(?P<star>\*)\s+(?P<inode>[\d-]+)(\([^)]*\))?:\t(?P<path>.*)$")


def fls_deleted(src, offset):
    """List deleted files TSK can still see at a partition offset."""
    r = run(["fls", "-o", str(offset), "-rd", "-p", src], sudo=needs_sudo(src))
    entries = []
    for line in r.stdout.splitlines():
        m = DELETED_RE.match(line.strip("\r"))
        if not m:
            continue
        path = m.group("path")
        if os.path.basename(path).startswith("._"):     # AppleDouble noise
            continue
        inode = m.group("inode").split("-")[0]
        if not inode.isdigit():
            continue
        entries.append({"inode": int(inode), "path": path, "offset": offset})
    return entries, (r.returncode == 0)


def cmd_scan(args):
    src = normalize_source(args.source)
    unmount_hint(src)
    require("fls", "sleuthkit")
    found_any, results = False, []
    for offset, desc in offsets_for(src, args.offset):
        entries, fs_ok = fls_deleted(src, offset)
        if not fs_ok and not entries:
            continue
        found_any = True
        results.extend(entries)
        if not args.json:
            print(f"\n{BOLD}Partition at sector {offset}{OFF} {DIM}({desc}){OFF}")
            if not entries:
                print("  no recoverable deleted files visible in filesystem metadata")
            for e in entries:
                print(f"  inode {e['inode']:>8}  {e['path']}")
    if args.json:
        print(json.dumps(results, indent=2))
        return
    if not found_any:
        warn("No readable filesystem found — if the disk was formatted or is damaged,")
        warn(f"deep-scan it instead:  dk recover carve {args.source} -o <output-dir>")
    elif results:
        print(f"\n{len(results)} deleted file(s) visible. Recover them:")
        print(f"  dk recover files {args.source} -o <output-dir>          # all of them")
        print(f"  dk recover files {args.source} -o <dir> --inode N       # just one")
        print("Files listed here can still be partially overwritten — recover ASAP.")
    else:
        warn("Filesystem is readable but shows no deleted entries.")
        warn(f"A deep signature scan may still find data:  dk recover carve {args.source} -o <dir>")


def cmd_files(args):
    src = normalize_source(args.source)
    unmount_hint(src)
    require("tsk_recover", "sleuthkit")
    outdir = guard_output_dir(args.output, src)
    sudo = needs_sudo(src)
    if args.inode:
        require("icat", "sleuthkit")
        offset = args.offset if args.offset is not None else (offsets_for(src, None)[0][0])
        dest = os.path.join(outdir, f"inode_{args.inode}.recovered")
        r = run(["icat", "-r", "-o", str(offset), src, str(args.inode)], sudo=sudo, stdout_to=dest)
        if r.returncode == 0 and os.path.getsize(dest) > 0:
            ok(f"Recovered inode {args.inode} -> {dest}")
        elif os.path.getsize(dest) > 0:
            os.rename(dest, dest + ".partial")
            warn(f"icat returned an error but wrote partial data -> {dest}.partial (verify it)")
        else:
            os.unlink(dest)
            die(f"icat could not recover inode {args.inode} (try: dk recover carve)")
        return
    total = 0
    for offset, desc in offsets_for(src, args.offset):
        part_dir = os.path.join(outdir, f"sector_{offset}")
        os.makedirs(part_dir, exist_ok=True)
        print(f"Recovering deleted files from partition at sector {offset} {DIM}({desc}){OFF} ...")
        r = run(["tsk_recover", "-o", str(offset), src, part_dir], sudo=sudo)
        prune_appledouble(part_dir)
        m = re.search(r"Files Recovered:\s*(\d+)", r.stdout or "")
        n = int(m.group(1)) if m else sum(len(f) for _, _, f in os.walk(part_dir))
        total += n
        if n:
            ok(f"{n} file(s) -> {part_dir}")
        else:
            os.rmdir(part_dir) if not os.listdir(part_dir) else None
    if total == 0:
        warn("Nothing recoverable through filesystem metadata.")
        warn(f"Deep scan will likely find more:  dk recover carve {args.source} -o {args.output}")
    else:
        ok(f"Done: {total} file(s) under {outdir}")
        print(f"{DIM}Filenames/paths are restored when metadata allows; verify contents before trusting.{OFF}")


def cmd_carve(args):
    src = normalize_source(args.source)
    unmount_hint(src)
    require("photorec", "testdisk")
    outdir = guard_output_dir(args.output, src)
    size = source_size(src)
    if size:
        est = max(1, int(size / (250 * 1024 * 1024) / 60))
        print(f"Deep-scanning {human(size)} — roughly {est} min (works on formatted/damaged disks).")
    print(f"{DIM}Carving recovers file CONTENTS by signature; original names/folders are lost.{OFF}")
    recup = os.path.join(outdir, "carved")
    # Validated non-interactive invocation (curses output must be discarded).
    # cwd=outdir so photorec's /log file never lands on the source disk.
    cmdline = ["photorec", "/log", "/d", recup, "/cmd", src,
               "partition_none,fileopt,everything,enable," + ("options,mode_ext2," if args.ext else "") + "search"]
    r = run(cmdline, sudo=needs_sudo(src), capture=False, stdout_to=os.devnull, cwd=outdir)
    if r.returncode != 0:
        die(f"photorec failed (exit {r.returncode}); stderr: {r.stderr.decode() if r.stderr else ''}")
    n = sum(len(files) for root, _, files in os.walk(outdir)
            if os.path.basename(root).startswith("carved"))
    ok(f"Carve complete: {n} file(s) under {outdir} (folders named carved.1, carved.2, ...)")
    print(f"{DIM}Expect some false positives — sort by type/size and eyeball what matters.{OFF}")


def cmd_image(args):
    src = normalize_source(args.source)
    require("ddrescue", ddrescue_pkg())
    dest = os.path.abspath(args.output)
    mapfile = dest + ".map"
    if os.path.exists(dest) and not os.path.exists(mapfile):
        die(f"{dest} exists but has no .map file — refusing to overwrite it.")
    if os.path.exists(mapfile) and not os.path.exists(dest):
        die(f"Found {mapfile} but the image {dest} is missing — resuming would create a\n"
            f"  hole-filled image that looks complete but isn't. Delete the .map to start fresh.")
    guard_output_dir(os.path.dirname(dest) or ".", src)   # never image onto the source disk
    unmount_hint(src)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    print("Pass 1/2: fast copy of the healthy areas...")
    r = run(["ddrescue", "-f", "-n", src, dest, mapfile], sudo=needs_sudo(src), capture=False)
    if r.returncode != 0:
        warn("First pass had trouble; continuing to retry pass anyway.")
    print("Pass 2/2: retrying bad areas (3 attempts)...")
    # -d (O_DIRECT) is a Linux concept; on macOS the raw rdisk node already
    # bypasses the buffer cache, and -d makes ddrescue error out there.
    pass2 = ["ddrescue", "-f", "-r3", src, dest, mapfile]
    if IS_LINUX:
        pass2.insert(1, "-d")
    r2 = run(pass2, sudo=needs_sudo(src), capture=False)
    if r2.returncode != 0:
        warn(f"Retry pass exited {r2.returncode} — the image may be incomplete (check {mapfile}).")
    ok(f"Image: {dest}  (resume map: {mapfile} — rerun the same command to continue)")
    print("Now recover FROM THE IMAGE, never the dying disk:")
    print(f"  dk recover scan  {dest}")
    print(f"  dk recover carve {dest} -o <output-dir>")


def ddrescue_pkg():
    """Package that provides the `ddrescue` binary, per platform."""
    if IS_MAC:
        return "ddrescue"
    if have("apt-get"):
        return "gddrescue"      # Debian/Ubuntu ship GNU ddrescue as 'gddrescue'
    return "ddrescue"           # Fedora/Arch/etc.


def cmd_deps(args):
    missing = [(t, p) for t, p in
               [("mmls", "sleuthkit"), ("photorec", "testdisk"),
                ("ddrescue", ddrescue_pkg())]
               if not have(t)]
    for t in ("mmls", "fls", "icat", "tsk_recover", "photorec", "ddrescue"):
        (ok if have(t) else warn)(f"{t}: {'found' if have(t) else 'missing'}")
    if not missing:
        ok("All recovery engines present.")
        return
    pkgs = sorted({p for _, p in missing})
    if args.install:
        if IS_MAC:
            subprocess.run(["brew", "install"] + pkgs, check=True)
        elif have("apt-get"):
            subprocess.run(["sudo", "apt-get", "install", "-y"] + pkgs, check=True)
        elif have("dnf"):
            subprocess.run(["sudo", "dnf", "install", "-y"] + pkgs, check=True)
        elif have("pacman"):
            subprocess.run(["sudo", "pacman", "-S", "--noconfirm"] + pkgs, check=True)
        else:
            die("No known package manager; install manually: " + " ".join(pkgs))
        ok("Installed.")
    else:
        print("Install with:  dk recover deps --install")
        print("  (macOS: brew install " + " ".join(pkgs) + ")"
              if IS_MAC else "  (Debian/Ubuntu: sudo apt-get install " + " ".join(pkgs) + ")")


# ---------------------------------------------------------------- helpers

def prune_appledouble(root):
    """Remove macOS AppleDouble ._ sidecars that tsk_recover pulls from FAT/exFAT."""
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.startswith("._"):
                try:
                    os.unlink(os.path.join(dirpath, f))
                except OSError:
                    pass


def require(tool, pkg):
    if not have(tool):
        die(f"{tool} not found — install the recovery engines first:  dk recover deps --install")


def source_size(src):
    try:
        if src.startswith("/dev/"):
            if IS_MAC:
                r = run(["diskutil", "info", "-plist", src.replace("/dev/r", "/dev/")])
                m = re.search(r"<key>TotalSize</key>\s*<integer>(\d+)</integer>", r.stdout)
                return int(m.group(1)) if m else None
            r = run(["blockdev", "--getsize64", src], sudo=True)
            return int(r.stdout.strip())
        return os.path.getsize(src)
    except Exception:
        return None


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


EPILOG = f"""
scenarios:
  deleted files, disk still healthy:
      dk recover scan  <src>                 # see what's recoverable
      dk recover files <src> -o ~/rescued    # get them back (names kept)
  formatted disk / scan finds nothing / ext4:
      dk recover carve <src> -o ~/rescued    # deep signature scan (names lost)
  drive is failing (clicking, I/O errors):
      dk recover image <src> -o ~/disk.img   # rescue an image FIRST
      dk recover carve ~/disk.img -o ~/rescued

<src> = {'diskXsY (see: dk list)' if IS_MAC else '/dev/sdXN (see: lsblk)'} or a path to an image file

hard truths (so you don't waste hours):
  - STOP writing to the affected disk immediately; every write may destroy data.
  - Internal SSDs (TRIM): deleted data is usually physically gone within minutes.
    USB enclosures/HDDs/SD cards usually do NOT trim — good recovery odds.
  - ext4 zeroes file-location metadata on delete: 'scan' rarely helps; use carve.
  - A full (slow) format writes zeros — nothing survives that.
"""


def main():
    ap = argparse.ArgumentParser(
        prog="dk recover",
        description="Free deleted-file and formatted-disk recovery (Sleuth Kit + PhotoRec + ddrescue).",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="list deleted files still visible in filesystem metadata")
    p.add_argument("source"); p.add_argument("--offset", type=int); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("files", help="recover deleted files (keeps names/paths when possible)")
    p.add_argument("source"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--inode", type=int, help="recover one specific inode from 'scan'")
    p.add_argument("--offset", type=int)
    p.set_defaults(fn=cmd_files)

    p = sub.add_parser("carve", help="deep signature scan — works on formatted/damaged disks")
    p.add_argument("source"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--ext", action="store_true", help="tune for ext2/3/4 sources")
    p.set_defaults(fn=cmd_carve)

    p = sub.add_parser("image", help="safely image a failing drive with ddrescue (do this FIRST)")
    p.add_argument("source"); p.add_argument("-o", "--output", required=True)
    p.set_defaults(fn=cmd_image)

    p = sub.add_parser("deps", help="check/install the recovery engines")
    p.add_argument("--install", action="store_true")
    p.set_defaults(fn=cmd_deps)

    args = ap.parse_args()
    try:
        args.fn(args)
    except KeyboardInterrupt:
        die("\nInterrupted.", 130)


if __name__ == "__main__":
    main()
