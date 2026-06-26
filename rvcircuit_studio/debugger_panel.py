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

from .common import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QTableWidget, QTableWidgetItem, QStackedWidget, QSplitter, QTimer,
    QTextCursor, QTextCharFormat, QColor, QFont, Qt, Signal, QSize,
    QHeaderView, QAbstractItemView, CS_BG_DEEP, CS_BG_TOOLBAR, CS_SURFACE,
    CS_ACCENT, CS_TEXT, CS_TEXT_MUTED, CS_SUCCESS, CS_WARNING, CS_DANGER,
    CS_PRIMARY,
)
from PySide6.QtWidgets import QScrollArea, QFrame, QSizePolicy

from .cp_debugger import (
    identify_steppable_lines, write_debug_files, cleanup_debug_files,
    get_all_python_files, parse_debug_output,
    DEBUG_SIGNAL_S, DEBUG_SIGNAL_CO, DEBUG_SIGNAL_CW,
    DEBUG_START, DEBUG_END,
)

_C_ACTIVE   = CS_ACCENT
_C_STEP     = CS_ACCENT
_C_HIST     = "#B794F6"   # purple for history nav
_C_STOP     = CS_DANGER
_C_START    = CS_SUCCESS
_C_DISABLED = CS_TEXT_MUTED

_BTN = (
    "QPushButton {{"
    "  background: transparent; color: {fg}; border: none;"
    "  padding: 2px 6px; border-radius: 3px; font-size: 16px;"
    "}}"
    "QPushButton:hover {{ background: #2a2a4a; }}"
    "QPushButton:disabled {{ color: {dis}; }}"
)

def _btn_style(fg=CS_TEXT, dis=_C_DISABLED):
    return _BTN.format(fg=fg, dis=dis)

def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n/1024:.1f} KB"
    return f"{n/1048576:.1f} MB"

class _CodeView(QWidget):
    """
    Thin wrapper: a read-only Qutepart with a blue-arrow current-line highlight.
    Loads files from disk on demand and caches the last loaded path.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QTextEdit
        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        try:
            from .app import MONO_FONT_FAMILY as _mono
        except Exception:
            _mono = "JetBrains Mono NL"
        font = QFont(_mono, 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._view.setFont(font)
        self._view.setStyleSheet(
            f"QTextEdit {{ background: {CS_BG_DEEP}; color: {CS_TEXT};"
            f"border: none; }}"
        )
        layout.addWidget(self._view)

        self._current_path = None
        self._current_line = None

    def show_line(self, filepath: str, line_num: int):
        """Load *filepath* (if changed) and highlight 1-based *line_num*."""
        if filepath != self._current_path:
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                    self._view.setPlainText(fh.read())
            except OSError:
                self._view.setPlainText(f"# Could not open: {filepath}")
            self._current_path = filepath
        self._highlight_line(line_num)
        self._current_line = line_num

    def _highlight_line(self, line_num: int):
        doc = self._view.document()
        block = doc.findBlockByLineNumber(line_num - 1)
        if not block.isValid():
            return
        from PySide6.QtWidgets import QTextEdit
        sel = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#1a3a5c"))          # blue tint
        fmt.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
        sel.format = fmt
        sel.cursor = self._view.textCursor()
        sel.cursor.setPosition(block.position())
        self._view.setExtraSelections([sel])
        cur = self._view.textCursor()
        cur.setPosition(block.position())
        self._view.setTextCursor(cur)
        self._view.ensureCursorVisible()

    def clear_view(self):
        self._view.clear()
        self._current_path = None
        self._current_line = None

class _WatchDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Expression", "Value"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {CS_SURFACE}; color: {CS_TEXT};"
            f"gridline-color: #30363d; border: none; }}"
            f"QHeaderView::section {{ background: {CS_BG_TOOLBAR}; color: {CS_TEXT_MUTED};"
            f"padding: 4px; border: none; }}"
        )
        layout.addWidget(self._table)

    def update_watches(self, watch_dict: dict):
        self._table.setRowCount(0)
        for expr, val in watch_dict.items():
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(expr)))
            self._table.setItem(row, 1, QTableWidgetItem(str(val)))

    def clear(self):
        self._table.setRowCount(0)

class _ConfigPage(QWidget):
    """
    Config page with:
      - list of .py files with checkboxes (which to instrument for debugging)
      - watch expression editor (global + per-file)
      - conditional breakpoints editor (global)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        files_label = QLabel("Files to debug (instrument):")
        files_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(files_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(140)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {CS_SURFACE}; border: 1px solid #30363d; border-radius: 4px; }}"
        )
        self._files_container = QWidget()
        self._files_layout    = QVBoxLayout(self._files_container)
        self._files_layout.setContentsMargins(6, 4, 6, 4)
        self._files_layout.setSpacing(2)
        scroll.setWidget(self._files_container)
        layout.addWidget(scroll)

        self._file_checkboxes: dict[str, QCheckBox] = {}

        watch_label = QLabel("Watch expressions (one per line, prefix 'file.py:' for file-specific):")
        watch_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(watch_label)

        from PySide6.QtWidgets import QPlainTextEdit
        self._watch_edit = QPlainTextEdit()
        self._watch_edit.setPlaceholderText(
            "Examples:\n  x\n  len(buf)\n  code.py: my_var"
        )
        self._watch_edit.setMaximumHeight(80)
        self._watch_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {CS_SURFACE}; color: {CS_TEXT};"
            f"border: 1px solid #30363d; border-radius: 4px; padding: 4px; font-family: 'JetBrains Mono'; }}"
        )
        layout.addWidget(self._watch_edit)

        cbp_label = QLabel("Conditional breakpoints (Python expressions, one per line):")
        cbp_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(cbp_label)

        self._cbp_edit = QPlainTextEdit()
        self._cbp_edit.setPlaceholderText("Example:\n  x > 10")
        self._cbp_edit.setMaximumHeight(60)
        self._cbp_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {CS_SURFACE}; color: {CS_TEXT};"
            f"border: 1px solid #30363d; border-radius: 4px; padding: 4px; font-family: 'JetBrains Mono'; }}"
        )
        layout.addWidget(self._cbp_edit)

        layout.addStretch()

    def populate_files(self, filenames: list):
        """Rebuild the file checkbox list."""
        prev_checked = {n for n, cb in self._file_checkboxes.items() if cb.isChecked()}

        while self._files_layout.count():
            item = self._files_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._file_checkboxes.clear()

        seen = set()
        for name in sorted(filenames):
            if name in seen:
                continue
            seen.add(name)
            cb = QCheckBox(name)
            cb.setStyleSheet(f"color: {CS_TEXT}; font-family: 'JetBrains Mono'; font-size: 10px;")
            cb.setChecked(name in prev_checked or name == "code.py")
            self._files_layout.addWidget(cb)
            self._file_checkboxes[name] = cb

    def get_debug_files(self) -> list:
        return [n for n, cb in self._file_checkboxes.items() if cb.isChecked()]

    def get_watch_exprs(self) -> dict:
        """Parse the watch text into {scope: [expr, ...]}."""
        result: dict[str, list] = {"": []}
        for line in self._watch_edit.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                scope, expr = line.split(":", 1)
                scope = scope.strip()
                expr  = expr.strip()
                if expr:
                    result.setdefault(scope, []).append(expr)
            else:
                result[""].append(line)
        return result

    def get_cond_breakpoints(self) -> dict:
        """Parse conditional breakpoints into {scope: [expr, ...]}."""
        exprs = [l.strip() for l in self._cbp_edit.toPlainText().splitlines() if l.strip()]
        return {"": exprs}

class _DebugToolbar(QWidget):
    sig_restart         = Signal()
    sig_stop            = Signal()
    sig_step            = Signal()
    sig_continue_log    = Signal()
    sig_continue        = Signal()
    sig_rewind_all      = Signal()
    sig_rewind          = Signal()
    sig_forward         = Signal()
    sig_forward_all     = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet(f"background: {CS_BG_TOOLBAR};")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(4)

        _TBTN = (
            "QPushButton {{"
            "  background: {bg}; color: {fg}; border: none;"
            "  padding: 3px 10px; border-radius: 3px; font-size: 11px;"
            "  font-weight: bold;"
            "}}"
            "QPushButton:hover {{ background: {hover}; }}"
            "QPushButton:disabled {{ background: {CS_SURFACE}; color: {dis}; }}"
        )

        def _tbtn(label, tooltip, bg, fg="#fff", hover=None):
            b = QPushButton(label)
            b.setToolTip(tooltip)
            if hover is None:
                hover = bg
            b.setStyleSheet(_TBTN.format(
                bg=bg, fg=fg, hover=hover,
                CS_SURFACE=CS_SURFACE, dis=_C_DISABLED
            ))
            return b

        self.btn_run     = _tbtn("  Run",   "Run with visual line tracking",
                                  CS_PRIMARY, hover="#2ea043")
        self.btn_step    = _tbtn(" Step",  "Execute one line, then pause",
                                  CS_ACCENT, fg=CS_BG_DEEP, hover="#79c0ff")
        self.btn_restart = _tbtn("  Restart", "Restart from the top",
                                  CS_SURFACE, fg=CS_TEXT, hover="#30363d")
        self.btn_stop    = _tbtn("  Stop",   "Stop debugger and clean up",
                                  CS_DANGER, hover="#da3633")

        row.addWidget(self.btn_run)
        row.addWidget(self.btn_step)
        row.addWidget(self.btn_restart)
        row.addWidget(self.btn_stop)
        row.addStretch()

        self._status = QLabel("Stopped")
        self._status.setStyleSheet(
            f"color: {CS_TEXT_MUTED}; font-size: 10px; padding: 0 8px;"
        )
        row.addWidget(self._status)

        self._mem_lbl  = QLabel("")
        self._time_lbl = QLabel("")
        for lbl in (self._mem_lbl, self._time_lbl):
            lbl.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 10px; padding: 0 6px;")
            row.addWidget(lbl)

        self.btn_restart.clicked.connect(self.sig_restart)
        self.btn_stop.clicked.connect(self.sig_stop)
        self.btn_step.clicked.connect(self.sig_step)
        self.btn_run.clicked.connect(self.sig_continue_log)

        # History nav signals still exist for programmatic use but
        # ambiguous when there are side effects").
        self.btn_cont_log    = self.btn_run    # alias for existing wiring
        self.btn_cont        = self.btn_run
        self.btn_rewind_all  = QPushButton()
        self.btn_rewind      = QPushButton()
        self.btn_forward     = QPushButton()
        self.btn_forward_all = QPushButton()

    def set_status(self, text: str, color: str = CS_TEXT_MUTED):
        self._status.setText(text)
        self._status.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 0 8px;"
        )

    def set_memory(self, text: str):
        self._mem_lbl.setText(text)

    def set_time(self, text: str):
        self._time_lbl.setText(text)

    def update_enabled(self, running: bool, halted: bool,
                       viewing_latest: bool, has_history: bool):
        can_run = running and halted and viewing_latest

        self.btn_run.setEnabled(can_run)
        self.btn_step.setEnabled(can_run)
        self.btn_stop.setEnabled(running)
        self.btn_restart.setEnabled(True)

class DebuggerPanel(QWidget):
    """
    Full debugger UI panel -- drop into bottom_stack as index 2.

    Usage
    -----
    panel = DebuggerPanel(repl_widget, parent=self)
    panel.set_drive("/Volumes/CIRCUITPY")
    repl_panel.data_received.connect(panel.feed_serial)
    """

    def __init__(self, repl_widget=None, parent=None):
        super().__init__(parent)
        self._repl   = repl_widget
        self._drive  = None
        self._main_editor = None  # set by set_main_editor() after construction

        self._debug_history:   list[dict] = []
        self._history_index:   int        = 0
        self._debugger_running: bool      = False
        self._debugger_halted:  bool      = False
        self._serial_buf:       str       = ""

        self._gutter_connections: dict = {}

        self._build_ui()

    def set_main_editor(self, editor):
        """Store reference to the main editor (survives widget reparenting)."""
        self._main_editor = editor

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setMinimumHeight(0)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)
        root.addWidget(self._stack)

        self._stack.addWidget(self._build_config_page())   # index 0
        self._stack.addWidget(self._build_debug_page())    # index 1
        self._stack.setCurrentIndex(0)

    def _build_config_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet(f"background: {CS_BG_TOOLBAR}; border-bottom: 1px solid #30363d;")
        hrow = QHBoxLayout(header)
        hrow.setContentsMargins(8, 0, 8, 0)
        title = QLabel("Debugger - Configuration")
        title.setStyleSheet(f"color: {CS_TEXT}; font-size: 11px; font-weight: bold;")
        hrow.addWidget(title)
        hrow.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Rescan CIRCUITPY for Python files")
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background: {CS_SURFACE}; color: {CS_TEXT_MUTED};"
            f"border: 1px solid #30363d; border-radius: 3px; padding: 2px 8px; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {CS_TEXT}; }}"
        )
        refresh_btn.clicked.connect(self._refresh_file_list)
        hrow.addWidget(refresh_btn)

        cleanup_btn = QPushButton("Cleanup")
        cleanup_btn.setToolTip("Remove all ide_debug_* files from CIRCUITPY")
        cleanup_btn.setStyleSheet(refresh_btn.styleSheet())
        cleanup_btn.clicked.connect(self._cleanup)
        hrow.addWidget(cleanup_btn)

        start_btn = QPushButton("▶  Start Debugger")
        start_btn.setToolTip("Instrument files and start debugging session")
        start_btn.setStyleSheet(
            f"QPushButton {{ background: {CS_PRIMARY}; color: #fff;"
            f"border: none; border-radius: 3px; padding: 2px 12px; font-size: 11px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: #2ea043; }}"
        )
        start_btn.clicked.connect(self._on_start_clicked)
        hrow.addWidget(start_btn)

        layout.addWidget(header)

        self._config_page = _ConfigPage()
        layout.addWidget(self._config_page)
        return page

    def _build_debug_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toolbar = _DebugToolbar()
        layout.addWidget(self._toolbar)

        config_bar = QWidget()
        config_bar.setFixedHeight(24)
        config_bar.setStyleSheet(f"background: {CS_SURFACE}; border-bottom: 1px solid #30363d;")
        cbar_row = QHBoxLayout(config_bar)
        cbar_row.setContentsMargins(6, 0, 6, 0)
        cfg_btn = QPushButton("← Config")
        cfg_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {CS_TEXT_MUTED};"
            f"border: none; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {CS_TEXT}; }}"
        )
        cfg_btn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        cbar_row.addWidget(cfg_btn)
        cbar_row.addStretch()

        self._file_label = QLabel("")
        self._file_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 10px;")
        cbar_row.addWidget(self._file_label)
        layout.addWidget(config_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet("QSplitter::handle { background: #30363d; }")

        self._watch_display = _WatchDisplay()
        self._watch_display.setMaximumHeight(150)
        splitter.addWidget(self._watch_display)

        self._code_view = _CodeView()
        splitter.addWidget(self._code_view)
        splitter.setSizes([120, 400])

        layout.addWidget(splitter, 1)

        self._toolbar.sig_restart.connect(self._on_restart)
        self._toolbar.sig_stop.connect(self._on_stop)
        self._toolbar.sig_step.connect(self._on_step)
        self._toolbar.sig_continue_log.connect(self._on_continue_log)
        self._toolbar.sig_continue.connect(self._on_continue)
        self._toolbar.sig_rewind_all.connect(self._on_rewind_all)
        self._toolbar.sig_rewind.connect(self._on_rewind)
        self._toolbar.sig_forward.connect(self._on_forward)
        self._toolbar.sig_forward_all.connect(self._on_forward_all)

        return page

    def set_drive(self, drive_path: str | None):
        """Set the CIRCUITPY drive path and refresh file list."""
        self._drive = drive_path
        self._refresh_file_list()

    def set_repl(self, repl_widget):
        """Attach or swap the REPL widget used for serial I/O."""
        self._repl = repl_widget

    def feed_serial(self, text: str):
        """
        Called with every chunk of serial data from repl_panel.data_received.
        Accumulates into a buffer and extracts debug state JSON blocks.
        """
        # This is wired to every serial chunk, including normal (non-debug)
        # REPL output. Without a cap, _serial_buf would grow for the whole
        # session on a streaming board. Only accumulate while a debug session
        # is active, and bound the buffer regardless.
        if not getattr(self, "_debugger_running", False):
            self._serial_buf = ""
            return

        self._serial_buf += text
        if len(self._serial_buf) > 131072:
            self._serial_buf = self._serial_buf[-16384:]

        states = parse_debug_output(self._serial_buf)

        if states:
            from .cp_debugger import DEBUG_OUT_END
            last_end = self._serial_buf.rfind(DEBUG_OUT_END)
            if last_end != -1:
                self._serial_buf = self._serial_buf[last_end + len(DEBUG_OUT_END):]

            self._debug_history.extend(states)
            # Bound history so a long debug session doesn't grow without limit.
            if len(self._debug_history) > 2000:
                self._debug_history = self._debug_history[-2000:]
            self._history_index = len(self._debug_history) - 1

            latest = self._debug_history[-1]
            self._debugger_halted = latest.get("h", False)

            if self._debugger_halted:
                self._toolbar.set_status("Halted", CS_WARNING)
            else:
                self._toolbar.set_status("Running", _C_START)

            self._refresh_debug_view()
            self._update_toolbar_state()
            return

        if self._debug_history and self._serial_buf.endswith("\n>>> "):
            self._debugger_running = False
            self._debugger_halted  = False
            self._toolbar.set_status("Stopped", _C_STOP)
            self._update_toolbar_state()

    def install_gutter(self, qpart, filename: str):
        """
        Connect a Qutepart instance's MarkArea.blockClicked signal so that
        gutter clicks toggle breakpoint comments (# ●) in the source.

        Also installs an event filter on the LineNumberArea so that clicking
        line numbers toggles breakpoints too (the MarkArea alone is too narrow
        for users to discover reliably).

        Safe to call multiple times for the same qpart -- duplicate connections
        are skipped.
        """
        qpart_id = id(qpart)
        if qpart_id in self._gutter_connections:
            return

        try:
            mark_area = qpart._margins[1]
        except (AttributeError, IndexError):
            return

        def _on_gutter_click(block):
            self._toggle_breakpoint(qpart, block, filename)

        mark_area.blockClicked.connect(_on_gutter_click)

        line_num_filter = None
        try:
            line_num_area = qpart._margins[0]
            from PySide6.QtCore import QObject, QEvent
            from PySide6.QtCore import QPoint

            class _LineNumClickFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Type.MouseButtonPress:
                        from PySide6.QtCore import Qt as _Qt
                        if event.button() == _Qt.MouseButton.LeftButton:
                            cursor = qpart.cursorForPosition(QPoint(0, int(event.position().y())))
                            block = cursor.block()
                            rect = qpart.blockBoundingGeometry(block).translated(
                                qpart.contentOffset())
                            if rect.bottom() >= event.position().y():
                                _on_gutter_click(block)
                    return False  # let the event propagate normally

            line_num_filter = _LineNumClickFilter(line_num_area)
            line_num_area.installEventFilter(line_num_filter)
        except (AttributeError, IndexError):
            pass

        self._gutter_connections[qpart_id] = (qpart, filename, _on_gutter_click, line_num_filter)

        self._sync_breakpoint_marks(qpart)

    def _sync_breakpoint_marks(self, qpart):
        """Scan the editor text for # ● comments and set the corresponding
        gutter marks so the red dots are visible even after a file reload."""
        try:
            mark_area = qpart._margins[1]
        except (AttributeError, IndexError):
            return
        doc = qpart.document()
        block = doc.begin()
        while block.isValid():
            if "# \u25cf" in block.text():   # ● = U+25CF
                mark_area.setBlockValue(block, 1)
            else:
                mark_area.setBlockValue(block, 0)
            block = block.next()
        mark_area.update()

    def uninstall_gutter(self, qpart):
        """Disconnect the gutter signal for a Qutepart instance being closed."""
        qpart_id = id(qpart)
        if qpart_id not in self._gutter_connections:
            return
        _, _, slot, line_num_filter = self._gutter_connections.pop(qpart_id)
        try:
            mark_area = qpart._margins[1]
            mark_area.blockClicked.disconnect(slot)
        except (AttributeError, IndexError, RuntimeError):
            pass
        if line_num_filter is not None:
            try:
                line_num_area = qpart._margins[0]
                line_num_area.removeEventFilter(line_num_filter)
            except (AttributeError, IndexError, RuntimeError):
                pass

    def _toggle_breakpoint(self, qpart, block, filename: str):
        """
        Toggle a # ● breakpoint comment on the clicked block after validating
        that the line is steppable.
        """
        line_text = block.text()
        line_num  = block.blockNumber()  # 0-based

        code = qpart.toPlainText()
        steppable = identify_steppable_lines(code)
        if line_num not in steppable:
            return  # not a steppable line -- ignore the click

        if "# ●" in line_text or "# ●" in line_text.lower():
            new_text = line_text.replace(" # ●", "").replace("# ●", "").rstrip()
            marked = False
        else:
            new_text = line_text.rstrip() + " # ●"
            marked = True

        cursor = qpart.textCursor()
        cursor.setPosition(block.position())
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfLine,
            QTextCursor.MoveMode.KeepAnchor
        )
        cursor.insertText(new_text)
        qpart.setTextCursor(cursor)

        try:
            mark_area = qpart._margins[1]
            block_after = qpart.document().findBlockByLineNumber(line_num)
            mark_area.setBlockValue(block_after, 1 if marked else 0)
            mark_area.update()
        except (AttributeError, IndexError):
            pass

    def _refresh_file_list(self):
        if not self._drive or not os.path.isdir(self._drive):
            return
        files = get_all_python_files(self._drive)
        self._config_page.populate_files(files)

    def _cleanup(self):
        if self._drive:
            cleanup_debug_files(self._drive)

    def _save_drive_tabs(self):
        """Auto-save any open editor tabs whose files reside on the CIRCUITPY
        drive so that breakpoint markers (# ●) in the editor buffer are
        written to disk before instrumentation reads them."""
        if not self._drive:
            return
        main = self._main_editor
        if not main or not hasattr(main, 'editor_tab_widget'):
            return
        tab_widget = main.editor_tab_widget
        drive = os.path.normcase(os.path.abspath(self._drive))
        for i in range(tab_widget.count()):
            widget = tab_widget.widget(i)
            fp = getattr(widget, '_file_path', None) or getattr(widget, 'current_file', None)
            if not fp:
                continue
            try:
                norm_fp = os.path.normcase(os.path.abspath(fp))
                if norm_fp.startswith(drive) and hasattr(widget, 'qpart'):
                    from .cp_debugger import _safe_write
                    _safe_write(fp, widget.qpart.toPlainText())
                    widget._modified = False
            except Exception:
                pass

    def _on_start_clicked(self):
        if not self._drive or not os.path.isdir(self._drive):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Drive", "Please connect a CIRCUITPY board first.")
            return
        if not self._repl or not self._repl.is_connected:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Serial", "Please connect to the REPL serial port first.")
            return

        debug_files = self._config_page.get_debug_files()
        if not debug_files:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Files", "Select at least one file to debug.")
            return

        self._save_drive_tabs()

        all_files    = get_all_python_files(self._drive)
        watch_exprs  = self._config_page.get_watch_exprs()
        cond_bps     = self._config_page.get_cond_breakpoints()

        try:
            write_debug_files(
                self._drive, all_files, debug_files,
                watch_exprs, cond_bps
            )
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Instrumentation Error", str(exc))
            return

        self._stack.setCurrentIndex(1)
        self._start_debug_session(all_files)

    def _start_debug_session(self, all_python_files: list):
        """Reset state and kick the board into the debug session."""
        self._debug_history   = []
        self._history_index   = 0
        self._serial_buf      = ""
        self._debugger_halted = False
        self._debugger_running = True

        self._watch_display.clear()
        self._code_view.clear_view()
        self._file_label.setText("")
        self._toolbar.set_status("Starting...", CS_TEXT_MUTED)
        self._update_toolbar_state()

        has_code_py = "code.py" in all_python_files
        entry = "ide_debug_code" if has_code_py else "ide_debug_main"

        self._send_start_sequence(entry)

    def _send_start_sequence(self, entry_module: str):
        """Send the Ctrl+C / Ctrl+D / import sequence asynchronously."""
        steps = [
            (0,    b"\x03"),   # Ctrl+C
            (120,  b"\x03"),
            (240,  b"\x03"),
            (500,  b"\x04"),   # Ctrl+D (soft reboot)
            (1100, b"\x03"),
            (1220, b"\x03"),
            (1340, b"\x03"),
            (1700, f"from {entry_module} import *\r".encode()),
        ]

        def _fire(step_bytes):
            if self._repl and self._repl.is_connected:
                self._repl._write_bytes(step_bytes)

        for delay_ms, data in steps:
            QTimer.singleShot(delay_ms, lambda d=data: _fire(d))

    def _send(self, signal: str):
        """Send a debug protocol signal over serial."""
        if self._repl and self._repl.is_connected:
            self._repl._write_bytes((signal + "\r").encode())

    def _on_restart(self):
        all_files = get_all_python_files(self._drive) if self._drive else []
        debug_files = self._config_page.get_debug_files()
        if not debug_files:
            debug_files = [f for f in all_files if f == "code.py"] or all_files[:1]

        main = self._main_editor
        if main and hasattr(main, '_save_drive_tabs'):
            pass  # tabs auto-saved by _save_drive_tabs below
        self._save_drive_tabs()
        try:
            watch_exprs = self._config_page.get_watch_exprs()
            cond_bps = self._config_page.get_cond_breakpoints()
            write_debug_files(self._drive, all_files, debug_files,
                              watch_exprs, cond_bps)
        except Exception:
            pass

        self._debug_history   = []
        self._history_index   = 0
        self._serial_buf      = ""
        self._debugger_halted = False
        self._debugger_running = True
        self._watch_display.clear()
        self._code_view.clear_view()
        has_code_py = "code.py" in all_files
        entry = "ide_debug_code" if has_code_py else "ide_debug_main"
        self._send_start_sequence(entry)

    def _on_stop(self):
        if self._repl and self._repl.is_connected:
            self._repl._write_bytes(b"\x03")
        self._debugger_running = False
        self._debugger_halted  = False
        self._toolbar.set_status("Stopped", _C_STOP)
        self._update_toolbar_state()

        main = self._main_editor
        if main:
            if hasattr(main, '_clear_all_debug_highlights'):
                main._clear_all_debug_highlights()
            if hasattr(main, '_debug_bar'):
                main._debug_bar.setVisible(False)

        if self._drive:
            cleanup_debug_files(self._drive)
        if self._repl and self._repl.is_connected:
            QTimer.singleShot(300, lambda: self._repl._write_bytes(b"\x04"))

        self._stack.setCurrentIndex(0)

    def _on_step(self):
        self._debugger_halted = False
        self._toolbar.set_status("Running", _C_START)
        self._update_toolbar_state()
        self._send(DEBUG_SIGNAL_S)

    def _on_continue_log(self):
        self._debugger_halted = False
        self._toolbar.set_status("Running (logging)", _C_START)
        self._update_toolbar_state()
        self._send(DEBUG_SIGNAL_CW)

    def _on_continue(self):
        self._debugger_halted = False
        self._toolbar.set_status("Running", _C_START)
        self._update_toolbar_state()
        self._send(DEBUG_SIGNAL_CO)

    def _on_rewind_all(self):
        if self._debug_history:
            self._history_index = 0
            self._refresh_debug_view()
            self._update_toolbar_state()

    def _on_rewind(self):
        if self._history_index > 0:
            self._history_index -= 1
            self._refresh_debug_view()
            self._update_toolbar_state()

    def _on_forward(self):
        if self._history_index < len(self._debug_history) - 1:
            self._history_index += 1
            self._refresh_debug_view()
            self._update_toolbar_state()

    def _on_forward_all(self):
        if self._debug_history:
            self._history_index = len(self._debug_history) - 1
            self._refresh_debug_view()
            self._update_toolbar_state()

    def _refresh_debug_view(self):
        if not self._debug_history:
            return
        frame = self._debug_history[self._history_index]

        filename   = frame.get("f", "")
        line_num   = frame.get("l", 1)
        watches    = frame.get("w", {})
        mem_bytes  = frame.get("m", 0)
        elapsed_ms = frame.get("t", 0)

        self._file_label.setText(f"{filename}  line {line_num}")
        # If the board sent watch values, show them. If not but the user
        # has configured watches, show them with a restart hint.
        if watches:
            self._watch_display.update_watches(watches)
        else:
            configured = self._config_page.get_watch_exprs()
            all_exprs = []
            for scope_exprs in configured.values():
                all_exprs.extend(scope_exprs)
            if all_exprs:
                hint = {e: "(restart debugger)" for e in all_exprs}
                self._watch_display.update_watches(hint)
            else:
                self._watch_display.update_watches({})
        self._toolbar.set_memory(f"  {_fmt_bytes(mem_bytes)}")
        self._toolbar.set_time(f"  {elapsed_ms:.1f} ms")

        if self._drive and filename:
            filepath = os.path.join(self._drive, filename)
            if not os.path.exists(filepath):
                filepath = filename
        else:
            filepath = filename

        if os.path.exists(filepath):
            self._code_view.show_line(filepath, line_num)

        # Highlight the executing line in the editor tab using the
        main = self._main_editor
        if main and hasattr(main, 'highlight_debug_line'):
            main.highlight_debug_line(filename, line_num)
        if main and hasattr(main, 'update_debug_info'):
            main.update_debug_info(filename, line_num, watches)

    def _update_toolbar_state(self):
        has_history    = bool(self._debug_history)
        viewing_latest = self._history_index == len(self._debug_history) - 1
        self._toolbar.update_enabled(
            running        = self._debugger_running,
            halted         = self._debugger_halted,
            viewing_latest = viewing_latest,
            has_history    = has_history,
        )

    def _highlight_editor_debug_line(self, filename: str, line_num: int):
        """Highlight line_num in the matching editor tab."""
        main = self._main_editor
        if not main or not hasattr(main, 'editor_tab_widget'):
            return
        tab_widget = main.editor_tab_widget
        for i in range(tab_widget.count()):
            widget = tab_widget.widget(i)
            fp = getattr(widget, '_file_path', None) or getattr(widget, 'current_file', None)
            if fp and os.path.basename(fp) == filename:
                if hasattr(widget, 'highlight_debug_line'):
                    widget.highlight_debug_line(line_num)
                return

    def _clear_editor_debug_lines(self):
        """Clear debug highlights from all open editor tabs."""
        main = self._main_editor
        if not main or not hasattr(main, 'editor_tab_widget'):
            return
        tab_widget = main.editor_tab_widget
        for i in range(tab_widget.count()):
            widget = tab_widget.widget(i)
            if hasattr(widget, 'clear_debug_highlight'):
                widget.clear_debug_highlight()