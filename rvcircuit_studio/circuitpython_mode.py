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

import os
import sys
import platform
import threading as _threading

from .common import QTimer, Signal, Qt
from PySide6.QtCore import QObject

try:
    import adafruit_board_toolkit.circuitpython_serial as _cp_serial
    HAS_ADAFRUIT_TOOLKIT = True
except ImportError:
    HAS_ADAFRUIT_TOOLKIT = False

def detect_circuitpy():
    """
    Scan mounted volumes for a CIRCUITPY drive.
    Returns the drive path (str) or None.
    Works on Windows, macOS, Linux, ChromeOS.
    """
    system = platform.system()

    if system == "Windows":
        return _detect_windows()
    elif system == "Darwin":
        return _detect_macos()
    elif system == "Linux":
        return _detect_linux()
    return None

def _detect_windows():
    """Enumerate mounted drive letters and check each volume name via ctypes.
    Uses the logical-drive bitmask to skip absent letters and guards each probe
    so one flaky drive can't hang or abort the scan. Drive type is not filtered;
    boards vary (removable or fixed) and only the volume name is reliable."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32

    # Declare signatures so ctypes marshals args/returns correctly.
    try:
        kernel32.GetLogicalDrives.restype = wintypes.DWORD
        kernel32.GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD,
        ]
        kernel32.GetVolumeInformationW.restype = wintypes.BOOL
    except Exception:
        pass

    try:
        drives_mask = kernel32.GetLogicalDrives()
    except Exception:
        drives_mask = 0  # 0 => probe all letters below

    buf = ctypes.create_unicode_buffer(1024)
    for i, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        if drives_mask and not (drives_mask & (1 << i)):
            continue  # letter not mounted
        drive = f"{letter}:\\"
        try:
            result = kernel32.GetVolumeInformationW(drive, buf, 1024,
                                                    None, None, None, None, 0)
            if result and buf.value == "CIRCUITPY":
                return drive
        except Exception:
            # A single bad drive must never abort the scan.
            continue

    # If the masked scan found nothing, probe every letter unconditionally.
    if drives_mask:
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            try:
                result = kernel32.GetVolumeInformationW(drive, buf, 1024,
                                                        None, None, None, None, 0)
                if result and buf.value == "CIRCUITPY":
                    return drive
            except Exception:
                continue
    return None

def _detect_macos():
    """Check /Volumes/ for CIRCUITPY."""
    volumes_dir = "/Volumes"
    if os.path.isdir(volumes_dir):
        for name in os.listdir(volumes_dir):
            if name.startswith("CIRCUITPY") or name.startswith("PYBFLASH"):
                path = os.path.join(volumes_dir, name)
                if os.path.isdir(path):
                    return path
    return None

def _detect_linux():
    """Check /media/<user>/, /media/, /mnt/, and ChromeOS paths."""
    chromeos_path = "/mnt/chromeos/removable/CIRCUITPY"
    if os.path.isdir(chromeos_path):
        return chromeos_path

    search_roots = ["/media", "/mnt"]
    import getpass
    try:
        user = getpass.getuser()
        user_media = f"/media/{user}"
        if os.path.isdir(user_media):
            search_roots.insert(0, user_media)
    except Exception:
        pass

    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                if entry.startswith("CIRCUITPY") or entry.startswith("PYBFLASH"):
                    path = os.path.join(root, entry)
                    if os.path.isdir(path):
                        return path
        except PermissionError:
            continue

    return None

def find_repl_port():
    """
    Find the CDC serial REPL port for the connected CircuitPython board.
    Returns a port name string (e.g. 'COM3', '/dev/ttyACM0') or None.
    Prefers adafruit-board-toolkit; falls back to scanning serial ports.
    """
    if HAS_ADAFRUIT_TOOLKIT:
        try:
            ports = _cp_serial.repl_comports()
            if ports:
                return ports[0].device
        except Exception:
            pass

    try:
        import serial.tools.list_ports
        CP_VIDS = {0x239A, 0xF055, 0x2E8A}  # includes Raspberry Pi Pico
        for port in serial.tools.list_ports.comports():
            if hasattr(port, 'vid') and port.vid in CP_VIDS:
                return port.device
            desc = (port.description or "").lower()
            if "circuitpython" in desc or "circuit python" in desc:
                return port.device
    except ImportError:
        pass

    return None

def safe_write(path: str, content: str) -> None:
    """
    Write content to path safely using fsync + atomic rename.

    Steps:
      1. Write to a temp file alongside the target (same directory = same drive)
      2. flush() - moves data from Python buffer to OS buffer
      3. fsync() - forces OS buffer to hardware
      4. rename temp over target - atomic on FAT, never leaves a half-written file

    This prevents CIRCUITPY corruption when the user unplugs or
    CircuitPython resets before Windows flushes its lazy write buffer.
    """
    dir_name  = os.path.dirname(os.path.abspath(path))
    tmp_path  = os.path.join(dir_name, os.path.basename(path) + ".tmp")
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)   # atomic on all platforms

    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

def save_to_board(code: str, drive_path: str, filename: str = "code.py") -> bool:
    """
    Write code to the CIRCUITPY drive.
    CircuitPython auto-reloads when code.py changes.
    Returns True on success, False on failure.
    """
    target = os.path.join(drive_path, filename)
    try:
        safe_write(target, code)
        return True
    except Exception:
        return False

class BoardStatus:
    DISCONNECTED = "disconnected"   # No drive, no serial
    PARTIAL      = "partial"        # Drive found, no serial REPL
    CONNECTED    = "connected"      # Drive + serial REPL both found

class BoardWatcher(QObject):
    """
    Polls every 2 seconds for CircuitPython board connect/disconnect.
    Signals:
        board_connected(drive_path: str, port: str)
        board_disconnected()
        board_status_changed(status: str)
    """
    board_connected    = Signal(str, str)   # drive_path, port
    board_disconnected = Signal()
    board_status_changed = Signal(str)      # BoardStatus string
    _poll_result       = Signal(object, object)  # internal: drive, port from worker

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drive_path  = None
        self._repl_port   = None
        self._status      = BoardStatus.DISCONNECTED
        self._poll_busy   = False   # guard: don't overlap polls

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._poll)
        # Worker threads emit _poll_result; Qt queues it onto the UI thread.
        self._poll_result.connect(self._apply_poll)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    @property
    def drive_path(self):
        return self._drive_path

    @property
    def repl_port(self):
        return self._repl_port

    @property
    def status(self):
        return self._status

    def _poll(self):
        # Detection (drive + port enumeration) can block for a second or more
        # when a drive or port is flaky, so run it off the UI thread and return
        # the result via a queued signal. _poll_busy prevents overlapping scans.
        if self._poll_busy:
            return
        self._poll_busy = True
        _threading.Thread(target=self._poll_worker, daemon=True).start()

    def _poll_worker(self):
        try:
            drive = detect_circuitpy()
            port  = find_repl_port() if drive else None
        except Exception:
            drive, port = None, None
        finally:
            self._poll_busy = False
        # Queued signal marshals to the UI thread; a QTimer started from a
        # worker thread would not fire.
        self._poll_result.emit(drive, port)

    def _apply_poll(self, drive, port):
        if drive and port:
            new_status = BoardStatus.CONNECTED
        elif drive:
            new_status = BoardStatus.PARTIAL
        else:
            new_status = BoardStatus.DISCONNECTED

        if new_status != BoardStatus.DISCONNECTED and self._status == BoardStatus.DISCONNECTED:
            self._drive_path = drive
            self._repl_port  = port or ""
            self.board_connected.emit(drive, port or "")

        if new_status == BoardStatus.DISCONNECTED and self._status != BoardStatus.DISCONNECTED:
            self._drive_path = None
            self._repl_port  = None
            self.board_disconnected.emit()

        if new_status != self._status:
            self._status = new_status
            self._drive_path = drive
            self._repl_port  = port or ""
            self.board_status_changed.emit(new_status)

import re as _re

def read_boot_out(drive_path: str) -> dict:
    """
    Read and parse CIRCUITPY/boot_out.txt.

    Returns a dict:
        {
            "raw":         "Adafruit CircuitPython 9.2.1 on ...",
            "version":     "9.2.1",       # full version string
            "major":       "9",           # major only, for bundle matching
            "board":       "Raspberry Pi Pico with RP2040",
            "board_id":    "raspberry_pi_pico",
            "outdated":    True/False,    # True if not on latest patch
        }
    Returns {} if boot_out.txt is missing or unreadable.
    """
    boot_path = os.path.join(drive_path, "boot_out.txt")
    if not os.path.isfile(boot_path):
        return {}

    try:
        with open(boot_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception:
        return {}

    result = {"raw": raw.strip(), "version": "", "major": "9",
              "board": "", "board_id": "", "outdated": False}

    m = _re.search(
        r"CircuitPython\s+([\d]+\.[\d]+\.[\d]+(?:\S*)?)\s+on\s+[^;]+;\s*(.+)",
        raw, _re.IGNORECASE
    )
    if m:
        result["version"] = m.group(1).strip()
        result["board"]   = m.group(2).strip()
        try:
            result["major"] = str(int(result["version"].split(".")[0]))
        except Exception:
            pass

    m2 = _re.search(r"Board\s+ID\s*:\s*(\S+)", raw, _re.IGNORECASE)
    if m2:
        result["board_id"] = m2.group(1).strip()

    return result

import urllib.request as _urllib_request
import json as _json

CP_RELEASES_API = "https://api.github.com/repos/adafruit/circuitpython/releases/latest"
CP_DOWNLOAD_PAGE = "https://circuitpython.org/board/{board_id}"

def _fetch_latest_cp_version() -> str:
    try:
        req = _urllib_request.Request(
            CP_RELEASES_API,
            headers={"User-Agent": "CircuitStudio/1.0"}
        )
        with _urllib_request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        tag = data.get("tag_name", "").lstrip("v")
        if any(x in tag for x in ("-alpha", "-beta", "-rc")):
            return ""
        return tag
    except Exception:
        return ""

def _version_tuple(v: str):
    """Convert '9.2.1' to (9, 2, 1) for comparison."""
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0, 0, 0)

def check_cp_version_async(board_version: str, board_id: str, callback):
    """
    In a background thread, fetch the latest CP release and call
    callback(board_version, latest_version, download_url) on completion.
    callback is always called on a worker thread - caller must use a Signal
    to marshal back to the Qt main thread.
    """
    def worker():
        latest = _fetch_latest_cp_version()
        if not latest:
            return  # network unavailable - don't nag
        board_t  = _version_tuple(board_version)
        latest_t = _version_tuple(latest)
        if board_t < latest_t:
            url = CP_DOWNLOAD_PAGE.format(board_id=board_id) if board_id else "https://circuitpython.org"
            callback(board_version, latest, url)

    _threading.Thread(target=worker, daemon=True).start()