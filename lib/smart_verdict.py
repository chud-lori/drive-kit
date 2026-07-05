#!/usr/bin/env python3
"""Turn `smartctl -j -a` JSON (on stdin) into a one-line health verdict.

Usage: smartctl -j -a <dev> | smart_verdict.py <device-name> [<-d type used>]
Exit code: 0 = OK/WARN, 2 = FAILING (so callers can branch on failure).
"""
import json
import sys

C = {"OK": "\033[32m", "WARN": "\033[33m", "FAILING": "\033[31m"}
MARK = {"OK": "✔", "WARN": "!", "FAILING": "✘"}


def main():
    dev = sys.argv[1] if len(sys.argv) > 1 else "disk"
    via = sys.argv[2] if len(sys.argv) > 2 else "auto"
    try:
        d = json.load(sys.stdin)
    except (ValueError, TypeError):
        print("%s%s %s: SMART data unreadable\033[0m" % (C["WARN"], MARK["WARN"], dev))
        sys.exit(1)

    passed = d.get("smart_status", {}).get("passed")
    verdict, reasons = "OK", []

    def num(v, default=0):  # tolerate null / missing / non-numeric
        return v if isinstance(v, (int, float)) else default

    if "nvme_smart_health_information_log" in d:
        n = d["nvme_smart_health_information_log"]
        cw = num(n.get("critical_warning"))
        me = num(n.get("media_errors"))
        spare = num(n.get("available_spare"), 100)
        thr = num(n.get("available_spare_threshold"))
        used = num(n.get("percentage_used"))
        if cw:
            verdict = "FAILING"; reasons.append("NVMe critical_warning=%s" % cw)
        if me:
            verdict = "FAILING"; reasons.append("%s media errors" % me)
        if spare < thr:
            verdict = "FAILING"; reasons.append("spare %s%% below threshold %s%%" % (spare, thr))
        if verdict == "OK" and used >= 90:
            verdict = "WARN"; reasons.append("%s%% of rated write life used" % used)
        info = "temp %sC, %sh powered on, %s%% wear" % (
            n.get("temperature", "?"), n.get("power_on_hours", "?"), used)
    else:
        ata = d.get("ata_smart_attributes", {})
        table = ata.get("table", []) if isinstance(ata, dict) else []
        attrs = {a["id"]: a for a in table if isinstance(a, dict) and "id" in a}

        def raw(i):
            return num(attrs.get(i, {}).get("raw", {}).get("value", 0))

        r5, r197, r198, r199 = raw(5), raw(197), raw(198), raw(199)
        if passed is False or r5 or r197 or r198:
            verdict = "FAILING"
            if r5:
                reasons.append("%s reallocated sectors" % r5)
            if r197:
                reasons.append("%s pending sectors" % r197)
            if r198:
                reasons.append("%s uncorrectable sectors" % r198)
            if passed is False:
                reasons.append("drive self-assessment FAILED")
        elif r199:
            verdict = "WARN"
            reasons.append("%s CRC errors (usually a bad cable/enclosure, not the disk)" % r199)
        info = "temp %sC, %sh powered on" % (raw(194), raw(9))

    print("%s%s %s: %s\033[0m  (%s)" % (C[verdict], MARK[verdict], dev, verdict, info))
    for r in reasons:
        print("    - %s" % r)
    if via != "auto":
        print("    (read via %s)" % via)
    if verdict == "FAILING":
        print("    Back it up NOW:  dk clone %s -o ~/backup.img   then  dk recover ..." % dev)
    sys.exit(2 if verdict == "FAILING" else 0)


if __name__ == "__main__":
    main()
