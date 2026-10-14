#!/usr/bin/env python3
"""Take out of a built bundle what must come from the user's own system.

- Qt's GTK theme and GLib network plug-ins pull GTK and GLib's I/O library into the program,
  which then load the system's own GTK and GIO modules. Those are built for the system's
  GLib, not the build machine's, so on a newer system every start fails to load them.
  The two plug-ins go, with every library only they needed.
- The C++ runtime (libstdc++, libgcc_s) goes too. The bundle is built on the oldest system
  it supports, so the user's runtime is always new enough, and graphics drivers loaded into
  the program need the user's.

usage: trim_bundle.py BUNDLE_DIR
"""

import os
import re
import subprocess
import sys

PLUGINS = ("platformthemes/libqgtk3.so", "networkinformation/libqglib.so")
SYSTEM_RUNTIME = ("libstdc++.so.6", "libgcc_s.so.1")


def _is_elf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def _needed(path: str) -> list:
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\).*\[(.+?)\]", out)


def trim(root: str) -> list:
    files = [os.path.join(folder, name) for folder, _dirs, names in os.walk(root) for name in names]
    elves = [f for f in files if not os.path.islink(f) and _is_elf(f)]
    needs = {f: set(_needed(f)) for f in elves}
    gone = {f for f in elves
            if f.replace(os.sep, "/").endswith(PLUGINS) or os.path.basename(f) in SYSTEM_RUNTIME}
    while True:  # libraries that only removed files need, to the end of the chain
        still_needed = set().union(*(needs[f] for f in elves if f not in gone))
        needed_by_gone = set().union(*(needs[f] for f in gone)) if gone else set()
        more = {f for f in elves if f not in gone
                and os.path.basename(f) in needed_by_gone and os.path.basename(f) not in still_needed}
        if not more:
            break
        gone |= more
    for f in sorted(gone):
        os.remove(f)
    for link in [f for f in files if os.path.islink(f) and not os.path.exists(f)]:
        os.remove(link)
    return sorted(os.path.relpath(f, root) for f in gone)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(__doc__)
    removed = trim(sys.argv[1])
    for name in removed:
        print("removed", name)
    if not any(n.endswith(PLUGINS) for n in removed):
        print("note: no GTK or GLib plug-in was in the bundle")
