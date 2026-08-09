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
import json
import time

os.environ['QT_OPENGL'] = 'desktop'

from .common import *
from .main_window import CircuitStudioEditor
from .utils import _fixSysPath

IDE_ROOT = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir() -> str:
    """Per-user writable directory for config, state and custom snippets.

    IDE_ROOT is inside the app bundle once frozen. On macOS writing there
    breaks the code signature and is blocked outright under app translocation,
    so every setting change was silently discarded in the shipped build.
    """
    try:
        from PySide6.QtCore import QStandardPaths
        # GenericDataLocation, not AppDataLocation: the latter appends
        # QApplication.applicationName(), which is unset at import time and
        # would make the path depend on how the app was launched.
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.GenericDataLocation)
    except Exception:
        base = ""
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".rvcircuitstudio")
    else:
        base = os.path.join(base, "RV Circuit Studio")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = os.path.join(os.path.expanduser("~"), ".rvcircuitstudio")
        os.makedirs(base, exist_ok=True)
    return base


USER_DATA_DIR = _user_data_dir()
BUNDLED_DATA_DIR = os.path.join(IDE_ROOT, "data")


def _migrate_legacy(name: str):
    """Copy a file from the old in-package location once, if present."""
    new = os.path.join(USER_DATA_DIR, name)
    if os.path.exists(new):
        return
    for old_dir in (BUNDLED_DATA_DIR,
                    os.path.join(os.path.dirname(IDE_ROOT), "data")):
        old = os.path.join(old_dir, name)
        if os.path.exists(old):
            try:
                import shutil
                shutil.copyfile(old, new)
            except OSError:
                pass
            return


for _f in ("circuit_studio_config.json", "circuit_studio_state.json",
           "snippets.json"):
    _migrate_legacy(_f)


# Set to the real registered family name once the bundled font loads at
# startup. Other modules read this so they request a name Qt actually has.
MONO_FONT_FAMILY = "JetBrains Mono NL"
DATA_DIR  = USER_DATA_DIR
CONFIG_FILE = os.path.join(DATA_DIR, "circuit_studio_config.json")
STATE_FILE  = os.path.join(DATA_DIR, "circuit_studio_state.json")
SNIPPETS_FILE = os.path.join(DATA_DIR, "snippets.json")


def _find_bundled_snippets() -> str:
    """Locate the read-only default snippets.

    Under PyInstaller the add-data flag puts this at
    _MEIPASS/rvcircuit_studio/snippets.json, while icons and font land at the
    _MEIPASS root, so both layouts have to be checked.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(IDE_ROOT, "rvcircuit_studio", "snippets.json"),
                 os.path.join(IDE_ROOT, "snippets.json"),
                 os.path.join(here, "snippets.json")):
        if os.path.exists(cand):
            return cand
    return os.path.join(here, "snippets.json")


BUNDLED_SNIPPETS = _find_bundled_snippets()

def get_ide_root():
    return IDE_ROOT

def get_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR

def _load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_config(config):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = CONFIG_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

def _load_or_setup(app):
    config = _load_config()

    workspace = config.get("workspace_directory", "").strip()
    if not workspace or not os.path.isdir(workspace):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            None,
            "Welcome to RV Circuit Studio",
            "Pick a folder to keep backups of your code.\n\n"
            "Your code runs on the board (CIRCUITPY drive).\n"
            "Every time you hit Run, a copy is backed up\n"
            "here automatically.\n\n"
            "You can change this in Settings."
        )
        workspace = QFileDialog.getExistingDirectory(
            None,
            "Select Backup Folder"
        )
        if not workspace:
            workspace = os.path.join(os.path.expanduser("~"), "CircuitStudioBackups")
        os.makedirs(workspace, exist_ok=True)
        config["workspace_directory"] = workspace
        config["last_project_directory"] = workspace
        _save_config(config)

    last_dir = config.get("last_project_directory", "").strip()
    if last_dir and os.path.isdir(last_dir) and config.get("restore_last", True):
        return last_dir

    config["last_project_directory"] = workspace
    _save_config(config)
    return workspace

def _create_splash():
    from PySide6.QtGui import QPainter, QLinearGradient
    from PySide6.QtCore import QRect

    W, H = 480, 280
    pix = QPixmap(W, H)
    pix.fill(QColor("#0D1117"))

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    grad = QLinearGradient(0, 0, W, 0)
    grad.setColorAt(0.0, QColor("#238636"))
    grad.setColorAt(0.5, QColor("#58A6FF"))
    grad.setColorAt(1.0, QColor("#238636"))
    p.fillRect(0, 0, W, 3, grad)

    title_font = QFont(MONO_FONT_FAMILY, 28, QFont.Weight.Bold)
    p.setFont(title_font)
    p.setPen(QColor("#58A6FF"))
    p.drawText(QRect(0, 60, W, 50), Qt.AlignmentFlag.AlignCenter, "RV Circuit Studio")

    sub_font = QFont(MONO_FONT_FAMILY, 11)
    p.setFont(sub_font)
    p.setPen(QColor("#3FB950"))
    p.drawText(QRect(0, 115, W, 25), Qt.AlignmentFlag.AlignCenter, "CircuitPython IDE")

    ver_font = QFont(MONO_FONT_FAMILY, 9)
    p.setFont(ver_font)
    p.setPen(QColor("#8B949E"))
    from ._version import __version__
    p.drawText(QRect(0, 145, W, 20), Qt.AlignmentFlag.AlignCenter, f"v{__version__}")

    p.drawText(QRect(0, 240, W, 20), Qt.AlignmentFlag.AlignCenter, "rvembedded.com")

    bar_x, bar_y, bar_w, bar_h = 60, 200, W - 120, 6
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1C2128"))
    p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 3, 3)

    p.end()
    return pix, (bar_x, bar_y, bar_w, bar_h)

def _update_splash(splash, pix, bar_rect, progress, message=""):
    from PySide6.QtGui import QPainter, QLinearGradient

    frame = pix.copy()
    p = QPainter(frame)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    bx, by, bw, bh = bar_rect
    fill_w = int(bw * max(0.0, min(1.0, progress)))

    if fill_w > 0:
        grad = QLinearGradient(bx, 0, bx + bw, 0)
        grad.setColorAt(0.0, QColor("#238636"))
        grad.setColorAt(1.0, QColor("#58A6FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(bx, by, fill_w, bh, 3, 3)

    if message:
        p.setFont(QFont(MONO_FONT_FAMILY, 8))
        p.setPen(QColor("#8B949E"))
        p.drawText(bx, by + bh + 14, message)

    p.end()
    splash.setPixmap(frame)
    splash.repaint()
    QApplication.processEvents()

def main():
    _fixSysPath()

    app = QApplication(sys.argv)
    app.setApplicationName("RV Circuit Studio")
    app.setStyleSheet(GLOBAL_STYLE)

    font_path = os.path.join(IDE_ROOT, "font", "jetbrains.ttf")
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            # Use the EXACT registered family name everywhere; the bundled file
            # registers as "JetBrains Mono NL", and asking for "JetBrains Mono"
            # triggers Qt's slow missing-family alias lookup + a warning.
            global MONO_FONT_FAMILY
            MONO_FONT_FAMILY = families[0]
            app.setProperty("mono_font_family", families[0])
            print(f"[RV Circuit Studio] Font: {families[0]}")

    pix, bar_rect = _create_splash()
    splash = QSplashScreen(pix)
    splash.show()
    app.processEvents()

    _update_splash(splash, pix, bar_rect, 0.2, "Loading workspace…")
    time.sleep(0.4)

    get_data_dir()

    _update_splash(splash, pix, bar_rect, 0.4, "Setting up project…")
    time.sleep(0.3)

    project_dir = _load_or_setup(app)

    _update_splash(splash, pix, bar_rect, 0.6, "Building interface…")
    time.sleep(0.3)

    window = QMainWindow()
    window.setWindowTitle("RV Circuit Studio")

    logo_path = os.path.join(IDE_ROOT, "icons", "rovari_logo.png")
    if not os.path.exists(logo_path):
        logo_path = os.path.join(IDE_ROOT, "icons", "rovari_logo.svg")
    if os.path.exists(logo_path):
        icon = QIcon(logo_path)
        ico_path = os.path.join(IDE_ROOT, "icons", "rovari_logo.ico")
        if os.path.exists(ico_path):
            icon.addFile(ico_path)
        window.setWindowIcon(icon)
        app.setWindowIcon(icon)

    editor = CircuitStudioEditor(window, project_dir=project_dir)
    window.setCentralWidget(editor)

    _update_splash(splash, pix, bar_rect, 0.85, "Almost ready…")
    time.sleep(0.3)

    def on_close(event):
        if not editor.confirm_close():
            event.ignore()
            return
        editor.save_editor_state()
        # Stop the board-detection polling thread so it doesn't fire after
        # widgets are destroyed.
        try:
            editor.board_watcher.stop()
        except Exception:
            pass
        # Disconnect the serial REPL so the COM port is released immediately
        # (on Windows, the port stays locked until the process fully exits).
        try:
            if hasattr(editor, 'repl_panel') and editor.repl_panel.is_connected:
                editor.repl_panel.disconnect()
        except Exception:
            pass
        # Stop autosave timers on any open tabs.
        try:
            for i in range(editor.editor_tab_widget.count()):
                w = editor.editor_tab_widget.widget(i)
                if hasattr(w, 'autosave_timer'):
                    w.autosave_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(editor, "camera_panel"):
                editor.camera_panel.cleanup()
        except Exception:
            pass
        try:
            drive = getattr(editor, '_board_drive', None)
            if drive and os.path.isdir(drive):
                from .cp_debugger import cleanup_debug_files
                cleanup_debug_files(drive)
        except Exception:
            pass
        try:
            editor.terminate_editors()
        except Exception:
            pass
        # STATE_FILE was read at startup and never written by anything, so
        # window geometry never survived a restart.
        try:
            geo = window.normalGeometry()
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"window_maximized": window.isMaximized(),
                           "window_x": geo.x(),  "window_y": geo.y(),
                           "window_width": geo.width(),
                           "window_height": geo.height()}, f)
        except Exception:
            pass
        config = _load_config()
        config["last_project_directory"] = editor.current_project_directory or ""
        _save_config(config)
        event.accept()

    window.closeEvent = on_close

    status = QStatusBar()
    status.showMessage("RV Circuit Studio - Ready  |  Connect a CircuitPython board to begin")
    window.setStatusBar(status)

    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("window_maximized", True):
                window.showMaximized()
            else:
                window.setGeometry(
                    state.get("window_x", 100), state.get("window_y", 100),
                    state.get("window_width", 1280), state.get("window_height", 800),
                )
                window.show()
        except Exception:
            window.showMaximized()
    else:
        window.showMaximized()

    _update_splash(splash, pix, bar_rect, 1.0, "Ready")
    QTimer.singleShot(600, splash.close)

    return app.exec()

if __name__ == "__main__":
    sys.exit(main())