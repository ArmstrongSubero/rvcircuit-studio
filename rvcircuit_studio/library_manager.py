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
import json
import shutil
import zipfile
import threading
import urllib.request
import urllib.error

from .common import *

ADAFRUIT_BUNDLE_API = "https://api.github.com/repos/adafruit/Adafruit_CircuitPython_Bundle/releases/latest"
COMMUNITY_BUNDLE_API = "https://api.github.com/repos/adafruit/CircuitPython_Community_Bundle/releases/latest"

BUNDLE_CACHE_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "CircuitStudio", "bundle_cache"
)

def _get_cache_dir():
    os.makedirs(BUNDLE_CACHE_DIR, exist_ok=True)
    return BUNDLE_CACHE_DIR

def _bundle_index_path(bundle_name: str) -> str:
    return os.path.join(_get_cache_dir(), f"{bundle_name}_index.json")

def _parse_cp_major(version_str: str) -> str:
    """Extract major version number from '9.2.1' → '9'."""
    try:
        return str(int(version_str.strip().split(".")[0]))
    except Exception:
        return "9"

def _find_asset(assets: list, major: str, bundle_name: str) -> dict | None:
    """Find the correct .zip asset for this CircuitPython major version."""
    for asset in assets:
        name = asset.get("name", "")
        if f"-{major}.x-mpy-" in name and name.endswith(".zip"):
            return asset
    for asset in assets:
        name = asset.get("name", "")
        if "-mpy-" in name and name.endswith(".zip"):
            return asset
    return None

def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "CircuitStudio/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def _http_download(url: str, dest_path: str, progress_cb=None):
    req = urllib.request.Request(url, headers={"User-Agent": "CircuitStudio/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total:
                    progress_cb(int(downloaded * 100 / total))

def _extract_bundle_index(zip_path: str) -> dict:
    """
    Scan bundle zip and build index:
    { "adafruit_neopixel": {"file": "adafruit_neopixel.mpy", "path": "...", "size": 1234}, ... }
    """
    index = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            basename = os.path.basename(name)
            if not basename:
                continue
            stem = basename.rsplit(".", 1)[0].lower()
            if "/lib/" in name and (name.endswith(".mpy") or name.endswith(".py")):
                info = zf.getinfo(name)
                index[stem] = {
                    "file":  basename,
                    "path":  name,
                    "size":  info.file_size,
                }
    return index

def _install_from_zip(zip_path: str, lib_entry: dict, lib_dir: str):
    """Extract a single library file from the bundle zip into lib_dir."""
    os.makedirs(lib_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        data = zf.read(lib_entry["path"])
        dest = os.path.join(lib_dir, lib_entry["file"])
        with open(dest, "wb") as f:
            f.write(data)

class LibraryManagerDialog(QDialog):
    """
    Full library manager:
    - Shows installed libraries on CIRCUITPY/lib/
    - Downloads Adafruit bundle index
    - Search + one-click install
    - Update detection
    """

    _status_signal   = Signal(str)
    _progress_signal = Signal(int)
    _index_ready     = Signal(dict)   # bundle name → index dict
    _install_done    = Signal(str, bool, str)  # lib_name, success, message

    def __init__(self, drive_path: str, cp_version: str = "9", parent=None):
        super().__init__(parent)
        self.drive_path  = drive_path
        self.lib_dir     = os.path.join(drive_path, "lib") if drive_path else None
        self.cp_major    = _parse_cp_major(cp_version)
        self._bundle_zip = None   # path to cached zip
        self._index      = {}     # stem → {file, path, size}
        self._installed  = {}    # stem -> {name, size, path}

        self.setWindowTitle("Library Manager")
        self.setMinimumSize(680, 520)
        self._build_ui()

        self._status_signal.connect(self._on_status)
        self._progress_signal.connect(self._on_progress)
        self._index_ready.connect(self._on_index_ready)
        self._install_done.connect(self._on_install_done)

        self._try_load_cache()
        self._refresh_installed()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Library Manager")
        title.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {CS_PRIMARY};")
        top.addWidget(title)
        top.addStretch()

        self.version_label = QLabel(f"CircuitPython {self.cp_major}.x bundle")
        self.version_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        top.addWidget(self.version_label)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {CS_SURFACE}; }}
            QTabBar::tab {{ padding: 6px 16px; color: {CS_TEXT_MUTED}; background: {CS_BG_DEEP}; }}
            QTabBar::tab:selected {{ color: {CS_TEXT}; background: {CS_SURFACE}; border-bottom: 2px solid {CS_PRIMARY}; }}
        """)
        root.addWidget(self.tabs)

        installed_tab = QWidget()
        self._build_installed_tab(installed_tab)
        self.tabs.addTab(installed_tab, "Installed")

        browse_tab = QWidget()
        self._build_browse_tab(browse_tab)
        self.tabs.addTab(browse_tab, "Browse Bundle")

        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setVisible(False)
        status_row.addWidget(self.progress_bar)
        root.addLayout(status_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _build_installed_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)

        if self.lib_dir:
            path_label = QLabel(f"CIRCUITPY/lib/  →  {self.lib_dir}")
        else:
            path_label = QLabel("No board connected — showing bundle browser only.")
        path_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        layout.addWidget(path_label)

        self.installed_list = QListWidget()
        self.installed_list.setStyleSheet(f"""
            QListWidget {{ background: {CS_BG_DEEP}; color: {CS_TEXT}; border: 1px solid {CS_SURFACE}; }}
            QListWidget::item:selected {{ background: {CS_PRIMARY}; color: white; }}
        """)
        layout.addWidget(self.installed_list)

        btn_row = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        add_btn = QPushButton("Add File Manually…")
        add_btn.clicked.connect(self._add_manual)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_installed)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _build_browse_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)

        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search libraries… (e.g. neopixel, display, bme280)")
        self.search_box.textChanged.connect(self._filter_browse)
        self.search_box.setStyleSheet(f"""
            QLineEdit {{ background: {CS_BG_DEEP}; color: {CS_TEXT};
                         border: 1px solid {CS_SURFACE}; padding: 4px 8px; border-radius: 4px; }}
        """)
        search_row.addWidget(self.search_box)

        self.download_btn = QPushButton("Download Bundle")
        self.download_btn.setStyleSheet(f"""
            QPushButton {{ background: {CS_PRIMARY}; color: white;
                           border: none; padding: 5px 14px; border-radius: 4px; }}
            QPushButton:hover {{ background: #2ea043; }}
            QPushButton:disabled {{ background: {CS_SURFACE}; color: {CS_TEXT_MUTED}; }}
        """)
        self.download_btn.clicked.connect(self._download_bundle)
        search_row.addWidget(self.download_btn)
        layout.addLayout(search_row)

        self.browse_list = QListWidget()
        self.browse_list.setStyleSheet(f"""
            QListWidget {{ background: {CS_BG_DEEP}; color: {CS_TEXT}; border: 1px solid {CS_SURFACE}; }}
            QListWidget::item:selected {{ background: {CS_ACCENT}33; color: {CS_TEXT}; }}
            QListWidget::item {{ padding: 3px 6px; }}
        """)
        layout.addWidget(self.browse_list)

        btn_row = QHBoxLayout()
        self.install_btn = QPushButton("Install Selected")
        self.install_btn.setEnabled(False)
        self.install_btn.setStyleSheet(f"""
            QPushButton {{ background: {CS_ACCENT}; color: white;
                           border: none; padding: 5px 14px; border-radius: 4px; }}
            QPushButton:hover {{ background: #79b8ff; }}
            QPushButton:disabled {{ background: {CS_SURFACE}; color: {CS_TEXT_MUTED}; }}
        """)
        self.install_btn.clicked.connect(self._install_selected)
        self.browse_list.itemSelectionChanged.connect(self._update_install_btn)

        note = QLabel("Bundle is cached locally after first download.")
        note.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt; font-style: italic;")
        btn_row.addWidget(self.install_btn)
        btn_row.addStretch()
        btn_row.addWidget(note)
        layout.addLayout(btn_row)

        self._browse_placeholder = QLabel(
            "Click  Download Bundle  to fetch the Adafruit CircuitPython Library Bundle.\n"
            "It will be cached on your PC — you only need to download it once per version."
        )
        self._browse_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._browse_placeholder.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 10pt;")
        self.browse_list.addItem("")   # spacer so list is visible
        layout.insertWidget(2, self._browse_placeholder)

    def _refresh_installed(self):
        self.installed_list.clear()
        self._installed.clear()
        if not self.lib_dir or not os.path.isdir(self.lib_dir):
            self.installed_list.addItem("(lib/ folder not found)")
            return
        entries = sorted(os.listdir(self.lib_dir))
        if not entries:
            self.installed_list.addItem("(no libraries installed)")
            return
        for name in entries:
            stem = name.rsplit(".", 1)[0].lower()
            size_path = os.path.join(self.lib_dir, name)
            try:
                size = os.path.getsize(size_path)
            except Exception:
                size = 0
            self._installed[stem] = {"name": name, "size": size, "path": size_path}

            outdated = False
            if self._index and stem in self._index:
                bundle_size = self._index[stem].get("size", 0)
                if bundle_size and size != bundle_size:
                    outdated = True

            if outdated:
                label = f"⚠  {name}   ({size:,} bytes)  — update available"
            else:
                label = f"   {name}   ({size:,} bytes)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if outdated:
                item.setForeground(QColor(CS_WARNING))
            self.installed_list.addItem(item)

        outdated_count = sum(
            1 for stem, info in self._installed.items()
            if self._index and stem in self._index
            and self._index[stem].get("size", 0)
            and info["size"] != self._index[stem]["size"]
        )
        if outdated_count:
            self.tabs.setTabText(0, f"Installed  ⚠ {outdated_count} outdated")
        else:
            self.tabs.setTabText(0, "Installed")

    def _remove_selected(self):
        item = self.installed_list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        reply = QMessageBox.question(
            self, "Remove Library",
            f"Remove  {name}  from CIRCUITPY/lib/?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            path = os.path.join(self.lib_dir, name)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self._refresh_installed()
                self._on_status(f"Removed {name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _add_manual(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Library File(s)", "",
            "CircuitPython Libraries (*.py *.mpy);;All Files (*)"
        )
        if not paths:
            return
        os.makedirs(self.lib_dir, exist_ok=True)
        for path in paths:
            try:
                shutil.copy2(path, os.path.join(self.lib_dir, os.path.basename(path)))
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        self._refresh_installed()

    def _try_load_cache(self):
        """Load bundle index from cache on startup if available."""
        index_path = _bundle_index_path("adafruit")
        if not os.path.exists(index_path):
            return
        try:
            with open(index_path, "r") as f:
                data = json.load(f)
            if data.get("major") == self.cp_major and data.get("index"):
                zip_path = data.get("zip_path", "")
                if os.path.exists(zip_path):
                    self._bundle_zip = zip_path
                    self._index_ready.emit(data["index"])
        except Exception:
            pass

    def _download_bundle(self):
        self.download_btn.setEnabled(False)
        self._on_status("Checking for bundle…")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        major = self.cp_major
        t = threading.Thread(target=self._worker_download, args=(major,), daemon=True)
        t.start()

    def _worker_download(self, major: str):
        cache = _get_cache_dir()
        index_path = _bundle_index_path("adafruit")

        if os.path.exists(index_path):
            try:
                with open(index_path, "r") as f:
                    data = json.load(f)
                if data.get("major") == major and data.get("index"):
                    zip_path = data.get("zip_path", "")
                    if os.path.exists(zip_path):
                        self._bundle_zip = zip_path
                        self._status_signal.emit("Loaded bundle from cache.")
                        self._index_ready.emit(data["index"])
                        return
            except Exception:
                pass

        try:
            self._status_signal.emit("Fetching release info from GitHub…")
            release = _http_get_json(ADAFRUIT_BUNDLE_API)
            assets  = release.get("assets", [])
            asset   = _find_asset(assets, major, "adafruit")

            if not asset:
                self._status_signal.emit(f"No bundle found for CircuitPython {major}.x")
                return

            zip_name = asset["name"]
            zip_path = os.path.join(cache, zip_name)

            if not os.path.exists(zip_path):
                self._status_signal.emit(f"Downloading {zip_name}…")
                _http_download(
                    asset["browser_download_url"],
                    zip_path,
                    progress_cb=lambda p: self._progress_signal.emit(p)
                )
            else:
                self._status_signal.emit("Using cached bundle ZIP…")

            self._status_signal.emit("Indexing bundle…")
            index = _extract_bundle_index(zip_path)

            with open(index_path, "w") as f:
                json.dump({"major": major, "zip_path": zip_path, "index": index}, f)

            self._bundle_zip = zip_path
            self._index_ready.emit(index)

        except Exception as e:
            self._status_signal.emit(f"Error: {e}")
        finally:
            self._progress_signal.emit(0)

    def _on_index_ready(self, index: dict):
        self._index = index
        self.progress_bar.setVisible(False)
        self.download_btn.setEnabled(True)
        self.download_btn.setText("Re-download Bundle")
        self._browse_placeholder.hide()
        self._browse_placeholder.setParent(None)  # fully remove from layout
        self._status_signal.emit(f"Bundle ready — {len(index):,} libraries available.")
        self._populate_browse(index)
        self._refresh_installed()

    def _populate_browse(self, index: dict):
        self.browse_list.clear()
        query = self.search_box.text().lower().strip()
        for stem in sorted(index.keys()):
            if query and query not in stem:
                continue
            entry = index[stem]
            installed = stem in self._installed
            label = f"{'✓  ' if installed else '      '}{entry['file']}   ({entry['size']:,} bytes)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, stem)
            if installed:
                item.setForeground(QColor(CS_PRIMARY))
            self.browse_list.addItem(item)

    def _update_install_btn(self):
        has_selection = bool(self.browse_list.selectedItems())
        has_bundle    = bool(self._index) and bool(self._bundle_zip)
        self.install_btn.setEnabled(has_selection and has_bundle)

    def _filter_browse(self, _text: str):
        if self._index:
            self._populate_browse(self._index)
            self._update_install_btn()

    def _install_selected(self):
        item = self.browse_list.currentItem()
        if not item or not self._bundle_zip:
            return
        stem = item.data(Qt.ItemDataRole.UserRole)
        lib_entry = self._index.get(stem)
        if not lib_entry:
            return

        lib_dir = self.lib_dir
        if not lib_dir:
            QMessageBox.information(
                self, "No Board Connected",
                "No CIRCUITPY drive detected.\n\n"
                "Connect your CircuitPython board and reopen the Library Manager\n"
                "to install directly to CIRCUITPY/lib/.\n\n"
                "Alternatively, select a local folder to save the library file."
            )
            lib_dir = QFileDialog.getExistingDirectory(
                self, "Select destination folder",
                os.path.join(os.path.expanduser("~"), "Documents") if os.name == "nt" else os.path.expanduser("~")
            )
            if not lib_dir:
                return

        self.install_btn.setEnabled(False)
        self._on_status(f"Installing {lib_entry['file']}…")

        def worker():
            try:
                _install_from_zip(self._bundle_zip, lib_entry, lib_dir)
                self._install_done.emit(stem, True, lib_entry["file"])
            except Exception as e:
                self._install_done.emit(stem, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_done(self, stem: str, success: bool, message: str):
        self.install_btn.setEnabled(True)
        if success:
            self._on_status(f"✓ Installed {message}")
            lib_entry = self._index.get(stem, {})
            self._installed[stem] = {"name": lib_entry.get("file", stem), "size": lib_entry.get("size", 0), "path": ""}
            self._refresh_installed()
            self._populate_browse(self._index)
        else:
            self._on_status(f"Error: {message}")
            QMessageBox.critical(self, "Install Error", message)

    def _on_status(self, msg: str):
        self.status_label.setText(msg)

    def _on_progress(self, val: int):
        self.progress_bar.setValue(val)
        if val >= 100:
            self.progress_bar.setVisible(False)

