# Copyright 2026 Armstrong Subero
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Bundle logic helpers for the Library Manager.

This module provides the pieces needed to match the feature set of the
CircuitPython online IDE:

  * Scan a project for top-level imports (for Auto Install).
  * Resolve a library's full dependency closure from the bundle JSON manifest.
  * Parse the real __version__ out of installed .py and .mpy files so updates
    are detected by semantic version, not by file size.

The .mpy binary version decoding mirrors the approach used by circup
(see https://github.com/adafruit/circup/blob/main/circup/shared.py) and the
online IDE's installedLibUtils.js.
"""

import os
import re

# Modules that ship with CircuitPython firmware itself. Imports of these must
# never be treated as a bundle library to install.
BUILTIN_MODULES = {
    "adafruit_pixelbuf", "alarm", "analogio", "array", "audiobusio", "audiocore",
    "audioio", "audiomixer", "audiomp3", "audiopwmio", "binascii", "bitbangio",
    "bitmaptools", "board", "builtins", "busio", "collections", "countio",
    "digitalio", "displayio", "errno", "fontio", "framebufferio", "gc", "gifio",
    "hashlib", "i2cdisplaybus", "io", "ipaddress", "json", "keypad", "math",
    "microcontroller", "micropython", "neopixel_write", "nvm", "os",
    "paralleldisplaybus", "ps2io", "pulseio", "pwmio", "qrio", "rainbowio",
    "random", "re", "rgbmatrix", "rotaryio", "rtc", "sdcardio", "select", "sharpdisplay",
    "socketpool", "ssl", "storage", "struct", "supervisor", "sys", "terminalio",
    "time", "touchio", "traceback", "ulab", "usb_cdc", "usb_hid", "usb_midi",
    "vectorio", "watchdog", "wifi", "zlib",
}


# --------------------------------------------------------------------------- #
#  Project scanning  (Auto Install)
# --------------------------------------------------------------------------- #

def collect_top_level_imports(root_dir: str) -> list[str]:
    """
    Walk a project directory and collect every top-level module imported by
    its Python source files.

    Mirrors the online IDE's collectPythonTopLevelImports:
      * 'import a, b.c as d'   -> {'a', 'b'}
      * 'from x.y import z'    -> {'x'}

    Hidden files/folders (leading dot) and the lib/ folder are skipped so we
    only capture what the *user's* code asks for.
    """
    found: set[str] = set()
    valid_ext = (".py",)

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # prune hidden dirs and the lib folder itself
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d.lower() != "lib"
        ]
        for fname in filenames:
            if fname.startswith("."):
                continue
            if not fname.lower().endswith(valid_ext):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    _extract_imports(fh.read(), found)
            except Exception:
                # unreadable file -> skip, never abort the whole scan
                continue

    return sorted(found)


def _extract_imports(source: str, out: set[str]) -> None:
    for raw in source.splitlines():
        line = raw.strip()
        if line.startswith("import "):
            body = line[len("import "):]
            for part in body.split(","):
                # strip ' as alias' and dotted submodules
                top = part.split(" as ")[0].split(".")[0].strip()
                if top:
                    out.add(top)
        elif line.startswith("from "):
            m = re.match(r"^from\s+([a-zA-Z_][\w\.]*)\s+import", line)
            if m:
                top = m.group(1).split(".")[0]
                if top:
                    out.add(top)


def is_bundle_library(name: str) -> bool:
    """True if `name` is something we should look for in the bundle (not a
    builtin firmware module and not the user's own local module)."""
    return name.lower() not in BUILTIN_MODULES


# --------------------------------------------------------------------------- #
#  Dependency resolution  (from the bundle JSON manifest)
# --------------------------------------------------------------------------- #

def resolve_dependencies(manifest: dict, targets: list[str]) -> list[str]:
    """
    Given the bundle JSON manifest and a list of target library names, return
    the full closure of names including every (external) dependency.

    manifest entries look like:
        { "adafruit_bme280": {
              "version": "2.6.27",
              "dependencies": ["adafruit_bus_device", "adafruit_register"],
              "external_dependencies": [] }, ... }

    Mirrors resolveDependenciesFromJsonStrings in the online IDE.
    """
    visited: set[str] = set()

    def dfs(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        node = manifest.get(name)
        if not node:
            return
        deps = node.get("dependencies") or []
        ext = node.get("external_dependencies") or []
        for dep in list(deps) + list(ext):
            dfs(dep)

    for t in targets:
        if t:
            dfs(t)

    return sorted(visited)


# --------------------------------------------------------------------------- #
#  Version parsing  (for true update detection)
# --------------------------------------------------------------------------- #

_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(version_str: str):
    """'2.6.27' -> (2, 6, 27). Returns None if unparseable."""
    if not version_str:
        return None
    m = _VER_RE.match(version_str.strip())
    if not m:
        # tolerate 'v1.2.3' and '1.2' style strings
        m2 = re.match(r"^v?\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", version_str.strip())
        if not m2:
            return None
        return (
            int(m2.group(1)),
            int(m2.group(2)) if m2.group(2) else 0,
            int(m2.group(3)) if m2.group(3) else 0,
        )
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def compare_versions(a, b) -> int:
    """Return <0 if a<b, 0 if equal, >0 if a>b. None sorts as (0,0,0)."""
    a = a or (0, 0, 0)
    b = b or (0, 0, 0)
    return (a > b) - (a < b)


def version_to_string(v) -> str:
    if not v:
        return ""
    return f"{v[0]}.{v[1]}.{v[2]}"


def read_installed_version(path: str):
    """
    Read the __version__ from an installed library file (.py or .mpy) or, for a
    package directory, from the first parseable file inside it.

    Returns a (major, minor, patch) tuple or None.
    """
    if os.path.isdir(path):
        return _find_version_in_tree(path)
    return _version_from_file(path)


def _find_version_in_tree(dir_path: str):
    """Depth-first: first .py/.mpy under dir_path that yields a valid version."""
    try:
        entries = sorted(os.listdir(dir_path))
    except Exception:
        return None
    # files first
    files = [e for e in entries if os.path.isfile(os.path.join(dir_path, e))]
    subdirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
    for e in files:
        if e.lower().endswith((".py", ".mpy")):
            v = _version_from_file(os.path.join(dir_path, e))
            if v:
                return v
    for d in subdirs:
        v = _find_version_in_tree(os.path.join(dir_path, d))
        if v:
            return v
    return None


def _version_from_file(path: str):
    lower = path.lower()
    try:
        if lower.endswith(".py"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", content)
            if m:
                return parse_version(m.group(1))
            return None
        if lower.endswith(".mpy"):
            with open(path, "rb") as fh:
                buf = fh.read()
            return _version_from_mpy(buf)
    except Exception:
        return None
    return None


def _version_from_mpy(buf: bytes):
    """
    Extract __version__ from a compiled .mpy blob.

    The encoding differs by mpy format (identified by the first two bytes):
      M\x03            -> CircuitPython < 7   (length byte is at version_loc-1)
      C\x05            -> 7.0 .. 8.99         (length byte halved, at loc-2)
      C\x06            -> 9.0+                (semver stored null-terminated)

    Mirrors circup/shared.py and the online IDE's mpy decoder.
    """
    if len(buf) < 2:
        return None

    magic = bytes(buf[:2])
    needle = b"__version__"

    # 9.x and newer: a bare X.Y.Z string terminated by a null byte.
    if magic == b"C\x06":
        max_decode = min(len(buf), 2 * 1024 * 1024)
        text = buf[:max_decode].decode("latin-1", errors="ignore")
        m = re.search(r"(\d+\.\d+\.\d+)\x00", text)
        return parse_version(m.group(1)) if m else None

    idx = buf.find(needle)
    if idx < 0:
        return None

    if magic == b"M\x03":
        loc = idx - 1
        halve = False
    elif magic == b"C\x05":
        loc = idx - 2
        halve = True
    else:
        return None

    if loc < 1:
        return None

    offset = 1
    while offset < loc:
        val = buf[loc - offset]
        if halve:
            val = val // 2
        if val == offset - 1:
            start = loc - offset + 1
            chunk = buf[start:loc]
            try:
                return parse_version(chunk.decode("latin-1", errors="ignore"))
            except Exception:
                return None
        offset += 1
    return None


# --------------------------------------------------------------------------- #
#  Missing-library detection  (auto-detect on usage)
# --------------------------------------------------------------------------- #

def extract_imports_from_text(source: str) -> list[str]:
    """Top-level imports from a single source string (one open file)."""
    found: set[str] = set()
    _extract_imports(source, found)
    return sorted(found)


def installed_stems(lib_dir: str) -> set[str]:
    """Lowercase stems of whatever is currently in the board's lib/ folder."""
    stems: set[str] = set()
    if not lib_dir or not os.path.isdir(lib_dir):
        return stems
    try:
        for name in os.listdir(lib_dir):
            stems.add(name.rsplit(".", 1)[0].lower())
    except Exception:
        pass
    return stems


def find_missing_libraries(source: str, lib_dir: str, index: dict,
                           manifest: dict = None) -> list[str]:
    """
    Given the code in the editor, the board's lib/ folder, and the bundle
    index, return the bundle libraries the code imports that are NOT already
    installed. Builtins and the user's own local modules are excluded; only
    names the bundle actually knows about are returned.

    The result is the bare set of directly-imported missing libs. Dependency
    expansion is left to the caller (resolve_dependencies) so the nudge can
    report what the user asked for separately from what gets pulled in.
    """
    imported = extract_imports_from_text(source)
    have = installed_stems(lib_dir)
    index = index or {}
    manifest = manifest or {}

    missing = []
    for name in imported:
        low = name.lower()
        if not is_bundle_library(low):
            continue
        if low in have:
            continue
        if low in index or low in manifest:
            missing.append(low)
    return sorted(set(missing))