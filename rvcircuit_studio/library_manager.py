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
from . import bundle_logic as bl

ADAFRUIT_BUNDLE_API = "https://api.github.com/repos/adafruit/Adafruit_CircuitPython_Bundle/releases/latest"

BUNDLE_CACHE_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "CircuitStudio", "bundle_cache"
)

# Bump this whenever the cached index/manifest shape changes so old caches
# built by a previous version are ignored and transparently rebuilt.
CACHE_FORMAT = 2


def _get_cache_dir():
    os.makedirs(BUNDLE_CACHE_DIR, exist_ok=True)
    return BUNDLE_CACHE_DIR


def _bundle_index_path(bundle_name: str) -> str:
    return os.path.join(_get_cache_dir(), f"{bundle_name}_index.json")


def _parse_cp_major(version_str: str) -> str:
    try:
        return str(int(version_str.strip().split(".")[0]))
    except Exception:
        return "9"


def _find_zip_asset(assets: list, major: str) -> dict | None:
    for asset in assets:
        name = asset.get("name", "")
        if f"-{major}.x-mpy-" in name and name.endswith(".zip"):
            return asset
    for asset in assets:
        name = asset.get("name", "")
        if "-mpy-" in name and name.endswith(".zip"):
            return asset
    return None


def _find_json_asset(assets: list, major: str) -> dict | None:
    """The manifest is the bundle's .json asset. Its name is version-agnostic,
    e.g. 'adafruit-circuitpython-bundle-20260602.json' (no -X.x-mpy- segment),
    so match by the bundle prefix while excluding the examples/py variants."""
    for asset in assets:
        name = asset.get("name", "")
        low = name.lower()
        if not low.endswith(".json"):
            continue
        if "examples" in low or "-py-" in low:
            continue
        if "bundle" in low:
            return asset
    # last resort: any .json
    for asset in assets:
        if asset.get("name", "").lower().endswith(".json"):
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
    Scan bundle zip and build a library index keyed by lowercase stem.

    Bundle layout:
        <root>/lib/<single_file>.mpy   -> one file-library
        <root>/lib/<package>/...       -> one package-library (folder)

    A library is ONLY the thing sitting directly under lib/. Files nested
    inside a package (e.g. adafruit_hashlib/_md5.mpy) belong to that package
    and must never appear as their own entry.
    """
    index = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if "/lib/" not in name:
                continue
            after = name.split("/lib/", 1)[1]
            if not after or after.endswith("/"):
                continue  # the lib/ dir entry itself or a sub-dir marker
            parts = after.split("/")
            head = parts[0]

            if len(parts) == 1:
                # single file directly under lib/  -> a file-library
                if not head.lower().endswith((".py", ".mpy")):
                    continue
                stem = head.rsplit(".", 1)[0].lower()
                index[stem] = {
                    "file": head, "path": name, "size": info.file_size,
                    "is_dir": False, "dir_path": "",
                }
            else:
                # nested -> belongs to package <head>; key by the package only
                stem = head.lower()
                dir_path = name.split("/lib/", 1)[0] + "/lib/" + head + "/"
                if stem not in index or not index[stem].get("is_dir"):
                    index[stem] = {
                        "file": head, "path": "", "size": 0,
                        "is_dir": True, "dir_path": dir_path,
                    }
                index[stem]["size"] += info.file_size
    return index


def _install_from_zip(zip_path: str, lib_entry: dict, lib_dir: str):
    """Extract one library (file or whole package folder) into lib_dir."""
    os.makedirs(lib_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        if lib_entry.get("is_dir"):
            prefix = lib_entry["dir_path"]
            pkg_name = lib_entry["file"]
            for member in zf.namelist():
                if not member.startswith(prefix) or member.endswith("/"):
                    continue
                rel = member[len(prefix):]
                dest = os.path.join(lib_dir, pkg_name, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        else:
            data = zf.read(lib_entry["path"])
            dest = os.path.join(lib_dir, lib_entry["file"])
            with open(dest, "wb") as f:
                f.write(data)


def load_cached_bundle(cp_major: str):
    """
    Return (zip_path, index, manifest) from the on-disk cache for this major
    version, or None if no usable cache exists. Used by the editor's
    auto-detect so it can resolve/install without opening the dialog.
    """
    index_path = _bundle_index_path("adafruit")
    if not os.path.exists(index_path):
        return None
    try:
        with open(index_path, "r") as f:
            data = json.load(f)
        if data.get("format") != CACHE_FORMAT:
            return None
        if data.get("major") != str(cp_major):
            return None
        zip_path = data.get("zip_path", "")
        index = data.get("index") or {}
        if not index or not os.path.exists(zip_path):
            return None
        return zip_path, index, (data.get("manifest") or {})
    except Exception:
        return None


def install_libraries(zip_path: str, index: dict, stems: list, lib_dir: str):
    """
    Install a list of library stems from the cached bundle zip into lib_dir.
    Returns (installed, skipped) lists of stems. Skips anything not in index.
    """
    installed, skipped = [], []
    for stem in stems:
        entry = index.get(stem)
        if not entry:
            skipped.append(stem)
            continue
        try:
            _install_from_zip(zip_path, entry, lib_dir)
            installed.append(stem)
        except Exception:
            skipped.append(stem)
    return installed, skipped


class LibraryManagerDialog(QDialog):
    """
    Library manager with parity to the CircuitPython online IDE:
      - Installed view with version-based update detection
      - Bundle browser with search + one-click install
      - Dependency resolution from the bundle JSON manifest
      - Auto Install: scan the open project and install exactly what it imports
      - Update All: bring every outdated library up to the bundle version
    """

    _status_signal   = Signal(str)
    _progress_signal = Signal(int)
    _index_ready     = Signal(dict, dict)        # file index, manifest
    _install_done    = Signal(str, bool, str)    # lib stem, success, message
    _batch_done      = Signal(str)               # summary message
    _refresh_signal  = Signal()
    _download_done   = Signal()                  # re-enable the button

    def __init__(self, drive_path: str, cp_version: str = "9",
                 project_dir: str = None, parent=None):
        super().__init__(parent)
        self.drive_path  = drive_path
        self.lib_dir     = os.path.join(drive_path, "lib") if drive_path else None
        self.cp_major    = _parse_cp_major(cp_version)
        self.project_dir = project_dir
        self._bundle_zip = None     # cached zip path
        self._index      = {}       # stem -> file entry
        self._manifest   = {}       # stem -> {version, dependencies, external_dependencies}
        self._installed  = {}       # stem -> {name, size, path, version}

        self.setWindowTitle("Library Manager")
        self.setMinimumSize(700, 560)
        self._build_ui()

        self._status_signal.connect(self._on_status)
        self._progress_signal.connect(self._on_progress)
        self._index_ready.connect(self._on_index_ready)
        self._download_done.connect(self._on_download_done)
        self._install_done.connect(self._on_install_done)
        self._batch_done.connect(self._on_batch_done)
        self._refresh_signal.connect(self._refresh_installed)

        self._try_load_cache()
        self._refresh_installed()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Library Manager")
        title.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {CS_PRIMARY};")
        top.addWidget(title)
        top.addStretch()

        self.auto_install_btn = QPushButton("Auto Install")
        self.auto_install_btn.setToolTip(
            "Scan your project's code, find every library it imports,\n"
            "resolve dependencies, and install them all from the bundle."
        )
        self.auto_install_btn.setStyleSheet(f"""
            QPushButton {{ background: {CS_PRIMARY}; color: white;
                           border: none; padding: 5px 14px; border-radius: 4px; }}
            QPushButton:hover {{ background: {CS_PRIMARY_HOVER}; }}
            QPushButton:disabled {{ background: {CS_SURFACE}; color: {CS_TEXT_MUTED}; }}
        """)
        self.auto_install_btn.clicked.connect(self._auto_install)
        top.addWidget(self.auto_install_btn)

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
            path_label = QLabel(f"CIRCUITPY/lib/  ->  {self.lib_dir}")
        else:
            path_label = QLabel("No board connected - showing bundle browser only.")
        path_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        layout.addWidget(path_label)

        self.installed_list = QListWidget()
        self.installed_list.setStyleSheet(f"""
            QListWidget {{ background: {CS_BG_DEEP}; color: {CS_TEXT}; border: 1px solid {CS_SURFACE}; }}
            QListWidget::item:selected {{ background: {CS_PRIMARY}; color: white; }}
        """)
        layout.addWidget(self.installed_list)

        btn_row = QHBoxLayout()
        self.update_all_btn = QPushButton("Update All")
        self.update_all_btn.setToolTip("Update every outdated library to the bundle version.")
        self.update_all_btn.setEnabled(False)
        self.update_all_btn.setStyleSheet(f"""
            QPushButton {{ background: {CS_ACCENT}; color: white;
                           border: none; padding: 5px 14px; border-radius: 4px; }}
            QPushButton:hover {{ background: #79b8ff; }}
            QPushButton:disabled {{ background: {CS_SURFACE}; color: {CS_TEXT_MUTED}; }}
        """)
        self.update_all_btn.clicked.connect(self._update_all)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        add_btn = QPushButton("Add File Manually...")
        add_btn.clicked.connect(self._add_manual)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_installed)
        btn_row.addWidget(self.update_all_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _build_browse_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)

        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search libraries... (e.g. neopixel, display, bme280)")
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

        note = QLabel("Dependencies are resolved and installed automatically.")
        note.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt; font-style: italic;")
        btn_row.addWidget(self.install_btn)
        btn_row.addStretch()
        btn_row.addWidget(note)
        layout.addLayout(btn_row)

        self._browse_placeholder = QLabel(
            "Click  Download Bundle  to fetch the Adafruit CircuitPython Library Bundle.\n"
            "It will be cached on your PC - you only need to download it once per version."
        )
        self._browse_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._browse_placeholder.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 10pt;")
        self.browse_list.addItem("")
        layout.insertWidget(2, self._browse_placeholder)

    # ------------------------------------------------------- installed view

    def _refresh_installed(self):
        self.installed_list.clear()
        self._installed.clear()
        if not self.lib_dir or not os.path.isdir(self.lib_dir):
            self.installed_list.addItem("(lib/ folder not found)")
            self.update_all_btn.setEnabled(False)
            return
        entries = sorted(os.listdir(self.lib_dir))
        if not entries:
            self.installed_list.addItem("(no libraries installed)")
            self.update_all_btn.setEnabled(False)
            return

        outdated_count = 0
        for name in entries:
            stem = name.rsplit(".", 1)[0].lower()
            full = os.path.join(self.lib_dir, name)
            try:
                size = os.path.getsize(full) if os.path.isfile(full) else 0
            except Exception:
                size = 0
            installed_ver = bl.read_installed_version(full)
            self._installed[stem] = {
                "name": name, "size": size, "path": full, "version": installed_ver,
            }

            bundle_ver = None
            if self._manifest and stem in self._manifest:
                bundle_ver = bl.parse_version(self._manifest[stem].get("version", ""))

            outdated = (
                bundle_ver is not None and installed_ver is not None
                and bl.compare_versions(installed_ver, bundle_ver) < 0
            )

            iv = bl.version_to_string(installed_ver) or "?"
            if outdated:
                outdated_count += 1
                label = f"!  {name}   (v{iv} -> v{bl.version_to_string(bundle_ver)})  update available"
            else:
                label = f"   {name}   (v{iv})" if installed_ver else f"   {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if outdated:
                item.setForeground(QColor(CS_WARNING))
            self.installed_list.addItem(item)

        self.update_all_btn.setEnabled(outdated_count > 0 and bool(self._bundle_zip))
        if outdated_count:
            self.tabs.setTabText(0, f"Installed  ! {outdated_count} outdated")
        else:
            self.tabs.setTabText(0, "Installed")

    def _outdated_stems(self) -> list[str]:
        out = []
        for stem, info in self._installed.items():
            if stem not in self._manifest:
                continue
            bundle_ver = bl.parse_version(self._manifest[stem].get("version", ""))
            if (bundle_ver is not None and info["version"] is not None
                    and bl.compare_versions(info["version"], bundle_ver) < 0):
                out.append(stem)
        return out

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

    # --------------------------------------------------------- bundle cache

    def _try_load_cache(self):
        index_path = _bundle_index_path("adafruit")
        if not os.path.exists(index_path):
            return
        try:
            with open(index_path, "r") as f:
                data = json.load(f)
            # Ignore caches written by an older format; they rebuild on demand.
            if data.get("format") != CACHE_FORMAT:
                return
            if data.get("major") == self.cp_major and data.get("index"):
                zip_path = data.get("zip_path", "")
                if os.path.exists(zip_path):
                    self._bundle_zip = zip_path
                    self._index_ready.emit(data["index"], data.get("manifest", {}))
        except Exception:
            pass

    def _download_bundle(self):
        self.download_btn.setEnabled(False)
        self._on_status("Checking for bundle...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        threading.Thread(target=self._worker_download, args=(self.cp_major,), daemon=True).start()

    def _worker_download(self, major: str):
        cache = _get_cache_dir()
        index_path = _bundle_index_path("adafruit")
        try:
            self._status_signal.emit("Fetching release info from GitHub...")
            release = _http_get_json(ADAFRUIT_BUNDLE_API)
            assets = release.get("assets", [])

            zip_asset = _find_zip_asset(assets, major)
            if not zip_asset:
                self._status_signal.emit(f"No bundle found for CircuitPython {major}.x")
                return

            zip_name = zip_asset["name"]
            zip_path = os.path.join(cache, zip_name)
            if not os.path.exists(zip_path):
                self._status_signal.emit(f"Downloading {zip_name}...")
                _http_download(zip_asset["browser_download_url"], zip_path,
                               progress_cb=lambda p: self._progress_signal.emit(p))
            else:
                self._status_signal.emit("Using cached bundle ZIP...")

            # manifest (dependency + version metadata)
            manifest = {}
            json_asset = _find_json_asset(assets, major)
            if json_asset:
                self._status_signal.emit("Downloading dependency manifest...")
                try:
                    raw = _http_get_json(json_asset["browser_download_url"])
                    manifest = {k.lower(): v for k, v in raw.items()}
                except Exception as e:
                    manifest = {}
                    self._status_signal.emit(f"Manifest download failed: {e}")
            else:
                self._status_signal.emit("No manifest asset found in release.")

            self._status_signal.emit("Indexing bundle...")
            index = _extract_bundle_index(zip_path)

            with open(index_path, "w") as f:
                json.dump({"format": CACHE_FORMAT, "major": major,
                           "zip_path": zip_path,
                           "index": index, "manifest": manifest}, f)

            self._bundle_zip = zip_path
            self._index_ready.emit(index, manifest)
        except Exception as e:
            self._status_signal.emit(f"Error: {e}")
        finally:
            self._progress_signal.emit(0)
            # Runs on every exit path. Without it a failed download left the
            # button disabled until the dialog was reopened.
            self._download_done.emit()

    def _on_download_done(self):
        self.progress_bar.setVisible(False)
        self.download_btn.setEnabled(True)

    def _on_index_ready(self, index: dict, manifest: dict):
        self._index = index
        self._manifest = manifest or {}
        self.progress_bar.setVisible(False)
        self.download_btn.setEnabled(True)
        self.download_btn.setText("Re-download Bundle")
        if self._browse_placeholder is not None:
            self._browse_placeholder.hide()
            self._browse_placeholder.setParent(None)
            self._browse_placeholder = None
        deps = "with dependency data" if self._manifest else "(no manifest - deps unavailable)"
        self._on_status(f"Bundle ready - {len(index):,} libraries available {deps}.")
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
            mark = "[*] " if installed else "      "
            ver = ""
            if stem in self._manifest:
                ver = f"   v{self._manifest[stem].get('version','')}"
            label = f"{mark}{entry['file']}{ver}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, stem)
            if installed:
                item.setForeground(QColor(CS_PRIMARY))
            self.browse_list.addItem(item)

    def _update_install_btn(self):
        self.install_btn.setEnabled(
            bool(self.browse_list.selectedItems()) and bool(self._index) and bool(self._bundle_zip)
        )

    def _filter_browse(self, _text: str):
        if self._index:
            self._populate_browse(self._index)
            self._update_install_btn()

    # ------------------------------------------------------- install paths

    def _resolve_lib_dir(self) -> str | None:
        """Return the install target, prompting for a folder if no board."""
        if self.lib_dir:
            return self.lib_dir
        QMessageBox.information(
            self, "No Board Connected",
            "No CIRCUITPY drive detected.\n\n"
            "Connect your CircuitPython board and reopen the Library Manager\n"
            "to install directly to CIRCUITPY/lib/, or pick a folder to save into."
        )
        chosen = QFileDialog.getExistingDirectory(
            self, "Select destination folder",
            os.path.join(os.path.expanduser("~"), "Documents")
            if os.name == "nt" else os.path.expanduser("~")
        )
        return chosen or None

    def _expand_with_deps(self, stems: list[str]) -> list[str]:
        """Resolve dependency closure if we have a manifest, else pass through."""
        if self._manifest:
            return bl.resolve_dependencies(self._manifest, stems)
        return sorted(set(stems))

    def _install_selected(self):
        item = self.browse_list.currentItem()
        if not item or not self._bundle_zip:
            return
        stem = item.data(Qt.ItemDataRole.UserRole)
        lib_dir = self._resolve_lib_dir()
        if not lib_dir:
            return
        targets = self._expand_with_deps([stem])
        self._run_batch_install(targets, lib_dir, headline=f"Installing {stem} + deps")

    def _update_all(self):
        if not self._bundle_zip:
            return
        lib_dir = self._resolve_lib_dir()
        if not lib_dir:
            return
        outdated = self._outdated_stems()
        if not outdated:
            self._on_status("Everything is already up to date.")
            return
        targets = self._expand_with_deps(outdated)
        self._run_batch_install(targets, lib_dir, headline=f"Updating {len(outdated)} libraries")

    def _auto_install(self):
        if not self.project_dir or not os.path.isdir(self.project_dir):
            QMessageBox.information(
                self, "Auto Install",
                "Auto Install needs an open project folder to scan.\n\n"
                "Open your project (the folder containing code.py / main.py) and try again."
            )
            return
        if not self._bundle_zip or not self._index:
            QMessageBox.information(
                self, "Auto Install",
                "Download the library bundle first (Browse Bundle tab),\n"
                "then run Auto Install."
            )
            self.tabs.setCurrentIndex(1)
            return
        lib_dir = self._resolve_lib_dir()
        if not lib_dir:
            return

        imports = bl.collect_top_level_imports(self.project_dir)
        wanted = [i for i in imports if bl.is_bundle_library(i)]
        # keep only names the bundle actually knows about
        known = [i for i in wanted if i.lower() in self._index or i.lower() in self._manifest]
        unknown = [i for i in wanted if i not in known]

        if not known:
            msg = "No installable bundle libraries were found in your project's imports."
            if unknown:
                msg += "\n\nNot in bundle (likely your own modules): " + ", ".join(unknown)
            QMessageBox.information(self, "Auto Install", msg)
            return

        targets = self._expand_with_deps([k.lower() for k in known])
        added_by_deps = [t for t in targets if t not in [k.lower() for k in known]]

        detail = "Will install:\n  " + "\n  ".join(known)
        if added_by_deps:
            detail += "\n\nPulled in as dependencies:\n  " + "\n  ".join(added_by_deps)
        if unknown:
            detail += "\n\nSkipped (not in bundle):\n  " + "\n  ".join(unknown)
        reply = QMessageBox.question(
            self, "Auto Install", detail + "\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_batch_install(targets, lib_dir, headline="Auto installing")

    def _run_batch_install(self, stems: list[str], lib_dir: str, headline: str):
        self.auto_install_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.update_all_btn.setEnabled(False)
        self._on_status(f"{headline}...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        def worker():
            total = len(stems)
            if total == 0:
                self._batch_done.emit("Nothing to install.")
                return
            installed, skipped, failed = [], [], []
            for i, stem in enumerate(stems):
                entry = self._index.get(stem)
                if not entry:
                    skipped.append(stem)
                    self._progress_signal.emit(int((i + 1) * 100 / total))
                    continue
                # skip if already at bundle version
                cur = self._installed.get(stem, {}).get("version")
                bundle_ver = bl.parse_version(self._manifest.get(stem, {}).get("version", "")) \
                    if self._manifest else None
                if cur and bundle_ver and bl.compare_versions(cur, bundle_ver) == 0:
                    skipped.append(stem)
                    self._progress_signal.emit(int((i + 1) * 100 / total))
                    continue
                try:
                    _install_from_zip(self._bundle_zip, entry, lib_dir)
                    installed.append(stem)
                except Exception as e:
                    failed.append(f"{stem} ({e})")
                self._status_signal.emit(f"{headline}: {stem}")
                self._progress_signal.emit(int((i + 1) * 100 / total))

            parts = []
            if installed:
                parts.append(f"installed/updated {len(installed)}")
            if skipped:
                parts.append(f"{len(skipped)} already current")
            if failed:
                parts.append(f"{len(failed)} failed")
            self._batch_done.emit("Done - " + ", ".join(parts) if parts else "Nothing to do.")

        threading.Thread(target=worker, daemon=True).start()

    def _on_batch_done(self, summary: str):
        self.auto_install_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._on_status(summary)
        self._refresh_installed()
        if self._index:
            self._populate_browse(self._index)
        self._update_install_btn()

    def _on_install_done(self, stem: str, success: bool, message: str):
        # retained for single-item compatibility; batch path uses _on_batch_done
        self.install_btn.setEnabled(True)
        if success:
            self._on_status(f"Installed {message}")
            self._refresh_installed()
            if self._index:
                self._populate_browse(self._index)
        else:
            self._on_status(f"Error: {message}")
            QMessageBox.critical(self, "Install Error", message)

    # ------------------------------------------------------------- signals

    def _on_status(self, msg: str):
        self.status_label.setText(msg)

    def _on_progress(self, val: int):
        self.progress_bar.setValue(val)
        if val >= 100:
            self.progress_bar.setVisible(False)