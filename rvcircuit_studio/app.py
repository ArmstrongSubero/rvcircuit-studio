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

# Set to the real registered family name once the bundled font loads at
# startup. Other modules read this so they request a name Qt actually has.
MONO_FONT_FAMILY = "JetBrains Mono NL"
DATA_DIR  = os.path.join(IDE_ROOT, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "circuit_studio_config.json")
STATE_FILE  = os.path.join(DATA_DIR, "circuit_studio_state.json")

def get_ide_root():
    return IDE_ROOT

def get_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR

def _load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_config(config):
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass

def _load_or_setup(app):
    config = _load_config()

    workspace = config.get("workspace_directory", "").strip()
    if not workspace or not os.path.isdir(workspace):
        workspace = QFileDialog.getExistingDirectory(
            None,
            "Select Workspace - RV Circuit Studio will save your CircuitPython projects here"
        )
        if not workspace:
            workspace = os.path.join(os.path.expanduser("~"), "CircuitStudioWorkspace")
        os.makedirs(workspace, exist_ok=True)
        config["workspace_directory"] = workspace
        _save_config(config)

    last_dir = config.get("last_project_directory", "").strip()
    if last_dir and os.path.isdir(last_dir) and config.get("restore_last", True):
        return last_dir

    from PySide6.QtWidgets import QInputDialog
    project_name, ok = QInputDialog.getText(
        None, "New Project", "Project name:", text="MyProject"
    )
    if not ok or not project_name.strip():
        project_name = "MyProject"
    project_name = project_name.strip()
    project_dir  = os.path.join(workspace, project_name)
    os.makedirs(project_dir, exist_ok=True)

    starter = os.path.join(project_dir, "code.py")
    if not os.path.exists(starter):
        with open(starter, "w", encoding="utf-8") as f:
            f.write(
                "# code.py - CircuitPython Starter\n"
                "# RV Circuit Studio\n\n"
                "import board\n"
                "import digitalio\n"
                "import time\n\n"
                "led = digitalio.DigitalInOut(board.LED)\n"
                "led.direction = digitalio.Direction.OUTPUT\n\n"
                "while True:\n"
                "    led.value = True\n"
                "    time.sleep(0.5)\n"
                "    led.value = False\n"
                "    time.sleep(0.5)\n"
            )

    config["last_project_directory"] = project_dir
    _save_config(config)
    return project_dir

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
        editor.save_editor_state()
        try:
            if hasattr(editor, "camera_panel"):
                editor.camera_panel.cleanup()
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
            with open(STATE_FILE, "r") as f:
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