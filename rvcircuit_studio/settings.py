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

from .common import *

def _load_config():
    from .app import CONFIG_FILE
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_config(config):
    from .app import CONFIG_FILE, DATA_DIR
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

class SettingsDialog(QDialog):
    """Circuit Studio Settings - Editor, Workspace, Board."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Circuit Studio - Settings")
        self.setMinimumSize(520, 420)
        self.config = _load_config()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        tabs = QTabWidget()
        tabs.addTab(self._build_editor_tab(),    "Editor")
        tabs.addTab(self._build_workspace_tab(), "Workspace")
        tabs.addTab(self._build_board_tab(),     "Board")
        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        for label, slot in [("Apply", self._apply), ("OK", self._ok), ("Cancel", self.reject)]:
            btn = QPushButton(label)
            btn.setFixedWidth(80)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

    def _build_editor_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        editor = self.config.get("editor", {})

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 32)
        self.font_size_spin.setValue(editor.get("font_size", 10))
        form.addRow("Editor Font Size:", self.font_size_spin)

        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(8, 32)
        self.ui_font_size_spin.setValue(self.config.get("ui", {}).get("font_size", 10))
        form.addRow("UI Font Size:", self.ui_font_size_spin)

        self.tab_width_spin = QSpinBox()
        self.tab_width_spin.setRange(2, 8)
        self.tab_width_spin.setValue(editor.get("tab_width", 4))
        form.addRow("Tab Width:", self.tab_width_spin)

        self.vim_check = QCheckBox("Enable Vim Mode")
        self.vim_check.setChecked(editor.get("vim_mode", False))
        form.addRow("", self.vim_check)

        self.autocomplete_check = QCheckBox("Enable Autocomplete")
        self.autocomplete_check.setChecked(editor.get("autocomplete", True))
        form.addRow("", self.autocomplete_check)

        self.line_numbers_check = QCheckBox("Show Line Numbers")
        self.line_numbers_check.setChecked(editor.get("line_numbers", True))
        form.addRow("", self.line_numbers_check)

        return w

    def _build_workspace_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        workspace = self.config.get("workspace_directory", "")
        row = QHBoxLayout()
        self.workspace_input = QLineEdit(workspace)
        self.workspace_input.setPlaceholderText("Select workspace folder...")
        browse = QPushButton("Browse...")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse_workspace)
        row.addWidget(self.workspace_input)
        row.addWidget(browse)
        form.addRow("Workspace:", row)

        self.restore_check = QCheckBox("Restore last project on startup")
        self.restore_check.setChecked(self.config.get("restore_last", True))
        form.addRow("", self.restore_check)

        return w

    def _build_board_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        board = self.config.get("board", {})

        self.filename_combo = QComboBox()
        for name in ["code.py", "main.py"]:
            self.filename_combo.addItem(name)
        current = board.get("filename", "code.py")
        idx = self.filename_combo.findText(current)
        if idx >= 0:
            self.filename_combo.setCurrentIndex(idx)
        form.addRow("Save as:", self.filename_combo)

        self.auto_connect_check = QCheckBox("Auto-connect REPL when board detected")
        self.auto_connect_check.setChecked(board.get("auto_connect", True))
        form.addRow("", self.auto_connect_check)

        self.auto_save_check = QCheckBox("Auto-save to board on Ctrl+S")
        self.auto_save_check.setChecked(board.get("auto_save", True))
        form.addRow("", self.auto_save_check)

        info = QLabel(
            "CircuitPython is interpreted - no compiler needed.\n"
            "Circuit Studio saves your .py file directly to the\n"
            "CIRCUITPY drive and the board auto-reloads."
        )
        info.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt; font-style: italic;")
        form.addRow("", info)

        return w

    def _browse_workspace(self):
        d = QFileDialog.getExistingDirectory(self, "Select Workspace Folder",
                                              self.workspace_input.text())
        if d:
            self.workspace_input.setText(d)

    def _apply(self):
        self.config.setdefault("editor", {}).update({
            "font_size":    self.font_size_spin.value(),
            "tab_width":    self.tab_width_spin.value(),
            "vim_mode":     self.vim_check.isChecked(),
            "autocomplete": self.autocomplete_check.isChecked(),
            "line_numbers": self.line_numbers_check.isChecked(),
        })
        self.config["workspace_directory"] = self.workspace_input.text()
        self.config["restore_last"]        = self.restore_check.isChecked()
        self.config.setdefault("ui", {}).update({
            "font_size": self.ui_font_size_spin.value(),
        })
        self.config.setdefault("board", {}).update({
            "filename":     self.filename_combo.currentText(),
            "auto_connect": self.auto_connect_check.isChecked(),
            "auto_save":    self.auto_save_check.isChecked(),
        })
        _save_config(self.config)

    def _ok(self):
        self._apply()
        self.accept()