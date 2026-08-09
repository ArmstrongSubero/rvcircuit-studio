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
import re

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

def _block_at(qpart, margin_widget, event):
    """
    Map a click on a margin widget to the text block under the pointer.

    Margins are siblings of the viewport, not ancestors, so mapFrom() cannot
    be used between them. Round trip through global coordinates instead.
    cursorForPosition() is wrap aware, which is what makes this correct on
    wrapped lines.

    Returns a QTextBlock, or None if the click landed below the last line.
    """
    from PySide6.QtCore import QPoint
    try:
        y = int(event.position().y())
    except AttributeError:
        y = int(event.y())

    viewport = qpart.viewport()
    try:
        pos = viewport.mapFromGlobal(margin_widget.mapToGlobal(QPoint(0, y)))
        pos.setX(0)
    except Exception:
        pos = QPoint(0, y)

    block = qpart.cursorForPosition(pos).block()
    if not block.isValid():
        return None
    rect = qpart.blockBoundingGeometry(block).translated(qpart.contentOffset())
    if rect.bottom() < pos.y():
        return None
    return block


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

    _SCOPE_RE = re.compile(r"^([A-Za-z0-9_.\-]+\.py)\s*:\s*(.+)$")

    @staticmethod
    def _validate(expr: str):
        """Return None if expr is a usable Python expression, else a reason."""
        # Expressions are injected inline into generated code, so a comment or
        # a line break would swallow the rest of the statement even though
        # compile() accepts both on their own.
        if "#" in expr:
            return "cannot contain a comment"
        if "\n" in expr or "\r" in expr or "\\" in expr:
            return "cannot contain a line break"
        try:
            compile(expr, "<watch>", "eval")
            return None
        except SyntaxError as exc:
            return exc.msg
        except (ValueError, RecursionError) as exc:
            return str(exc)

    def _parse_expr_lines(self, text: str, scoped: bool):
        """
        Split a config text box into {scope: [expr, ...]} plus a list of
        (line, reason) for anything that will not compile.
        """
        result: dict[str, list] = {"": []}
        bad: list = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            scope, expr = "", line
            if scoped:
                # Only treat a colon as a scope separator when the prefix is a
                # filename. Slices, dict literals, lambdas and f-string format
                # specs all contain colons and are not scopes.
                m = self._SCOPE_RE.match(line)
                if m:
                    scope, expr = m.group(1), m.group(2).strip()
            if not expr:
                continue
            reason = self._validate(expr)
            if reason:
                bad.append((line, reason))
                continue
            result.setdefault(scope, []).append(expr)
        return result, bad

    def get_watch_exprs(self) -> dict:
        """Parse the watch text into {scope: [expr, ...]}."""
        return self._parse_expr_lines(self._watch_edit.toPlainText(), True)[0]

    def get_cond_breakpoints(self) -> dict:
        """Parse conditional breakpoints into {scope: [expr, ...]}."""
        return self._parse_expr_lines(self._cbp_edit.toPlainText(), False)[0]

    def get_invalid_exprs(self) -> list:
        """Return [(label, line, reason)] for every unusable expression."""
        bad = []
        for label, text, scoped in (
            ("Watch", self._watch_edit.toPlainText(), True),
            ("Conditional breakpoint", self._cbp_edit.toPlainText(), False),
        ):
            for line, reason in self._parse_expr_lines(text, scoped)[1]:
                bad.append((label, line, reason))
        return bad

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
    sig_session_ended = Signal()
    sig_status        = Signal(str, str)
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

        # Handshake state. _raw_buf accumulates serial regardless of session
        # state, so the start sequence can wait on real board output.
        self._raw_buf:      str  = ""
        self._wait_pattern       = None
        self._wait_cb            = None
        self._wait_timer         = None
        self._start_attempts     = 0
        self._pending_start      = None

        self._gutter_connections: dict = {}

        self._build_ui()

    def set_main_editor(self, editor):
        """Store reference to the main editor (survives widget reparenting)."""
        self._main_editor = editor

    def _status(self, text: str, color: str = CS_TEXT_MUTED):
        """Set the status on the panel toolbar and mirror it somewhere the
        user can actually see. DebuggerPanel is never added to a layout, so
        _toolbar.set_status() alone goes to a hidden widget."""
        self._toolbar.set_status(text, color)
        self.sig_status.emit(text, color)

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
        # The handshake matcher must see every chunk, including the output the
        # board produces before a session is running.
        self._raw_feed(text)

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
                self._status("Halted", CS_WARNING)
            else:
                self._status("Running", _C_START)

            self._refresh_debug_view()
            self._update_toolbar_state()
            return

        if self._debug_history and self._serial_buf.endswith("\n>>> "):
            self._debugger_running = False
            self._debugger_halted  = False
            self._status("Stopped", _C_STOP)
            self._update_toolbar_state()
            # The program finished on its own. Without this the debug bar stays
            # live and the next Step writes [S] into a bare REPL, which the
            # board evaluates as a name and rejects.
            self.sig_session_ended.emit()

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

        # qutepart's own Bookmarks class connects MarkArea.blockClicked to its
        # bookmark toggle, and bookmarks share the same one bit margin value we
        # use for breakpoints. Two handlers writing the same bit is why clicks
        # sometimes appeared to do nothing. Take sole ownership of the click.
        try:
            mark_area.blockClicked.disconnect()
        except (RuntimeError, TypeError):
            pass

        def _on_gutter_click(block):
            self._toggle_breakpoint(qpart, block, filename)

        from PySide6.QtCore import QObject, QEvent

        class _MarginClickFilter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.MouseButtonPress:
                    from PySide6.QtCore import Qt as _Qt
                    if event.button() == _Qt.MouseButton.LeftButton:
                        block = _block_at(qpart, obj, event)
                        if block is not None:
                            _on_gutter_click(block)
                            # Consume it. Letting it through would also run
                            # MarginBase.mousePressEvent and re-emit
                            # blockClicked, giving a second toggle.
                            return True
                return False

        filters = []
        for idx in (0, 1):   # LineNumberArea, MarkArea
            try:
                area = qpart._margins[idx]
            except (AttributeError, IndexError):
                continue
            flt = _MarginClickFilter(area)
            area.installEventFilter(flt)
            filters.append((area, flt))

        self._gutter_connections[qpart_id] = (qpart, filename, _on_gutter_click, filters)

        self._sync_breakpoint_marks(qpart)      # legacy '# BULLET' comments
        self._restore_breakpoints(qpart, filename)

    # ------------------------------------------------------------------ #
    #  Breakpoint persistence                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bp_key(path: str) -> str:
        """Config key for a file. Absolute and case-normalised so the same
        file opened by two routes maps to one entry."""
        try:
            return os.path.normcase(os.path.abspath(path))
        except Exception:
            return path

    def _load_saved_breakpoints(self) -> dict:
        try:
            from .app import _load_config
            return _load_config().get("breakpoints", {}) or {}
        except Exception:
            return {}

    def save_breakpoints(self):
        """Write current gutter marks to the config, keyed by file path.

        Marks live in the block user state, which does not survive closing a
        tab or restarting the app.
        """
        try:
            from .app import _load_config, _save_config
        except Exception:
            return
        try:
            cfg = _load_config()
            stored = cfg.get("breakpoints", {}) or {}
            for entry in list(self._gutter_connections.values()):
                qpart, path = entry[0], entry[1]
                if not path or path == "untitled.py":
                    continue
                key = self._bp_key(path)
                lines = sorted(self._marks_of(qpart))
                if lines:
                    stored[key] = lines
                else:
                    stored.pop(key, None)
            cfg["breakpoints"] = stored
            _save_config(cfg)
        except Exception:
            pass

    def _marks_of(self, qpart) -> set:
        """1-based line numbers currently marked in a qpart's gutter."""
        out = set()
        try:
            mark_area = qpart._margins[1]
            block = qpart.document().begin()
            while block.isValid():
                if mark_area.getBlockValue(block):
                    out.add(block.blockNumber() + 1)
                block = block.next()
        except (AttributeError, IndexError, RuntimeError):
            pass
        return out

    def _restore_breakpoints(self, qpart, path: str):
        """Re-apply saved marks for *path*, skipping lines that are no longer
        steppable because the file changed since they were saved."""
        if not path or path == "untitled.py":
            return
        lines = self._load_saved_breakpoints().get(self._bp_key(path))
        if not lines:
            return
        try:
            steppable = identify_steppable_lines(qpart.toPlainText())
            mark_area = qpart._margins[1]
            doc = qpart.document()
            for n in lines:
                if (n - 1) not in steppable:
                    continue
                block = doc.findBlockByNumber(n - 1)
                if block.isValid():
                    mark_area.setBlockValue(block, 1)
            mark_area.update()
        except (AttributeError, IndexError, RuntimeError):
            pass

    def _sync_breakpoint_marks(self, qpart):
        """Import legacy '# BULLET' comment markers into gutter marks.

        Additive on purpose: new breakpoints are stored only in the gutter, so
        this must not clear a mark just because the line has no comment.
        """
        try:
            mark_area = qpart._margins[1]
        except (AttributeError, IndexError):
            return
        doc = qpart.document()
        block = doc.begin()
        while block.isValid():
            if "# \u25cf" in block.text():   # U+25CF
                mark_area.setBlockValue(block, 1)
            block = block.next()
        mark_area.update()

    def collect_breakpoints(self) -> dict:
        """
        Read gutter marks from every open editor and return
        {filename: set(1-based line numbers)}.

        This is the source of truth for breakpoints now. Nothing is written
        into the user's file.
        """
        out: dict[str, set] = {}
        for entry in list(self._gutter_connections.values()):
            qpart, filename = entry[0], entry[1]
            try:
                mark_area = qpart._margins[1]
                doc = qpart.document()
            except (AttributeError, IndexError, RuntimeError):
                continue
            lines = set()
            block = doc.begin()
            while block.isValid():
                try:
                    if mark_area.getBlockValue(block):
                        lines.add(block.blockNumber() + 1)
                except (RuntimeError, AttributeError):
                    break
                block = block.next()
            if lines:
                out.setdefault(os.path.basename(filename), set()).update(lines)
        return out

    def uninstall_gutter(self, qpart):
        """Disconnect the gutter signal for a Qutepart instance being closed."""
        qpart_id = id(qpart)
        if qpart_id not in self._gutter_connections:
            return
        self.save_breakpoints()
        _, _, _slot, filters = self._gutter_connections.pop(qpart_id)
        for area, flt in filters or ():
            try:
                area.removeEventFilter(flt)
            except (AttributeError, RuntimeError):
                pass

    def _toggle_breakpoint(self, qpart, block, filename: str):
        """
        Toggle a # ● breakpoint comment on the clicked block after validating
        that the line is steppable.
        """
        line_num = block.blockNumber()  # 0-based

        steppable = identify_steppable_lines(qpart.toPlainText())
        if line_num not in steppable:
            return  # not a steppable line -- ignore the click

        try:
            mark_area = qpart._margins[1]
        except (AttributeError, IndexError):
            return

        # Breakpoints live in the gutter, never in the user's source.
        marked = bool(mark_area.getBlockValue(block))
        mark_area.setBlockValue(block, 0 if marked else 1)
        mark_area.update()
        self.save_breakpoints()

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

    # ------------------------------------------------------------------ #
    #  Serial handshake                                                   #
    # ------------------------------------------------------------------ #

    _RAW_BUF_CAP  = 8192
    _MAX_INTERRUPT_ATTEMPTS = 6
    _PROMPT       = ">>> "

    def _raw_feed(self, text: str):
        """Accumulate serial output and satisfy any pending _wait_for()."""
        self._raw_buf += text
        if len(self._raw_buf) > self._RAW_BUF_CAP:
            self._raw_buf = self._raw_buf[-2048:]

        if self._wait_pattern and self._wait_pattern in self._raw_buf:
            cb = self._wait_cb
            self._clear_wait()
            if cb:
                cb(True)

    def _wait_for(self, pattern: str, timeout_ms: int, on_done):
        """Call on_done(True) when *pattern* appears, or on_done(False) on
        timeout. Only one wait can be outstanding at a time."""
        self._clear_wait()
        self._raw_buf = ""
        self._wait_pattern = pattern
        self._wait_cb = on_done
        self._wait_timer = QTimer(self)
        self._wait_timer.setSingleShot(True)
        self._wait_timer.timeout.connect(self._on_wait_timeout)
        self._wait_timer.start(timeout_ms)

    def _on_wait_timeout(self):
        cb = self._wait_cb
        self._clear_wait()
        if cb:
            cb(False)

    def _clear_wait(self):
        self._wait_pattern = None
        self._wait_cb = None
        if self._wait_timer is not None:
            try:
                self._wait_timer.stop()
                self._wait_timer.deleteLater()
            except RuntimeError:
                pass
            self._wait_timer = None

    def _tx(self, data: bytes):
        if self._repl and self._repl.is_connected:
            self._repl._write_bytes(data)

    def _start_failed(self, title: str, detail: str):
        from PySide6.QtWidgets import QMessageBox
        self._clear_wait()
        self._pending_start = None
        self._debugger_running = False
        self._debugger_halted = False
        self._status("Failed", _C_STOP)
        self._update_toolbar_state()
        main = self._main_editor
        if main and hasattr(main, "_debug_bar"):
            main._debug_bar.setVisible(False)
        if main and hasattr(main, "repl_panel"):
            main.repl_panel._debug_mode = False
        if self._drive:
            cleanup_debug_files(self._drive)
        self._stack.setCurrentIndex(0)
        QMessageBox.warning(self, title, detail)

    # ------------------------------------------------------------------ #

    def _on_start_clicked(self):
        from PySide6.QtWidgets import QMessageBox

        if not self._drive or not os.path.isdir(self._drive):
            QMessageBox.warning(self, "No Drive", "Please connect a CIRCUITPY board first.")
            return
        if not self._repl or not self._repl.is_connected:
            QMessageBox.warning(self, "No Serial", "Please connect to the REPL serial port first.")
            return

        debug_files = self._config_page.get_debug_files()
        if not debug_files:
            QMessageBox.warning(self, "No Files", "Select at least one file to debug.")
            return

        invalid = self._config_page.get_invalid_exprs()
        if invalid:
            detail = "\n".join(f"  {kind}: {line}\n      {why}"
                               for kind, line, why in invalid)
            QMessageBox.warning(
                self, "Invalid Expression",
                "These expressions are not valid Python and would break the "
                f"instrumented copy:\n\n{detail}\n\nFix or remove them, then "
                "start again."
            )
            return

        self._save_drive_tabs()
        self._begin_start(debug_files)

    def _begin_start(self, debug_files: list):
        """Phase 1: get the board to a REPL prompt before touching the drive.

        Writing the instrumented files first is what the old code did, and on
        a board that is running user code every one of those writes triggers a
        CircuitPython auto reload, restarting code.py in the middle of the
        start sequence. Auto reload is suppressed while the board sits at the
        REPL, so interrupt first, then write.
        """
        self._pending_start = {"debug_files": list(debug_files)}
        self._start_attempts = 0

        self._debug_history   = []
        self._history_index   = 0
        self._serial_buf      = ""
        self._debugger_halted = False
        self._debugger_running = True

        self._watch_display.clear()
        self._code_view.clear_view()
        self._file_label.setText("")
        self._stack.setCurrentIndex(1)
        self._status("Interrupting board...", CS_TEXT_MUTED)
        self._update_toolbar_state()

        self._interrupt_attempt()

    def _interrupt_attempt(self):
        if self._start_attempts >= self._MAX_INTERRUPT_ATTEMPTS:
            self._start_failed(
                "Could Not Reach the REPL",
                "The board never returned a >>> prompt after repeated Ctrl+C.\n\n"
                "This usually means code.py is inside a long blocking call "
                "(display init on a large panel is a common one) or the serial "
                "port is connected to a different device.\n\n"
                "Try again, or temporarily replace code.py with a short program."
            )
            return

        self._start_attempts += 1
        self._status(
            f"Interrupting board ({self._start_attempts})...", CS_TEXT_MUTED
        )
        self._tx(b"\x03")
        # A second Ctrl+C shortly after catches boards that were mid line.
        QTimer.singleShot(80, lambda: self._tx(b"\x03"))
        QTimer.singleShot(160, lambda: self._tx(b"\r"))
        self._wait_for(self._PROMPT, 1500, self._on_prompt_result)

    def _on_prompt_result(self, ok: bool):
        if self._pending_start is None:
            return          # session was cancelled while we waited
        if not ok:
            self._interrupt_attempt()
            return
        self._write_and_import()

    def _write_and_import(self):
        """Phase 2: at the prompt, write instrumentation, then import it."""
        from PySide6.QtWidgets import QMessageBox

        pending = self._pending_start
        if pending is None:
            return
        debug_files = pending["debug_files"]

        all_files   = get_all_python_files(self._drive)
        watch_exprs = self._config_page.get_watch_exprs()
        cond_bps    = self._config_page.get_cond_breakpoints()
        breakpoints = self.collect_breakpoints()

        self._status("Writing instrumentation...", CS_TEXT_MUTED)
        try:
            report = write_debug_files(
                self._drive, all_files, debug_files,
                watch_exprs, cond_bps, breakpoints=breakpoints,
            )
        except Exception as exc:
            self._start_failed("Instrumentation Error", str(exc))
            return

        bad = report.get("unparseable") or {}
        if bad:
            lines = "\n".join(f"  {f}: {why}" for f, why in bad.items())
            self._start_failed(
                "Cannot Instrument",
                "These files could not be compiled, so no debug points were "
                f"inserted:\n\n{lines}\n\nFix the error and start again."
            )
            return

        broken = report.get("broken") or {}
        if broken:
            lines = "\n".join(f"  {f}: {why}" for f, why in broken.items())
            self._start_failed(
                "Instrumentation Produced Invalid Code",
                "Your source compiles, but the instrumented copy does not:\n\n"
                f"{lines}\n\nThis is usually caused by a malformed watch "
                "expression or conditional breakpoint. Check the Watch and "
                "Conditional Breakpoint boxes, then start again."
            )
            return

        if not report.get("breakpoints"):
            # Deliberately not a modal. A dialog here would block the event
            # loop in the middle of the handshake.
            self._status(
                "No breakpoints set - will halt on the first line", CS_WARNING
            )

        pending["entry"] = (
            "ide_debug_code" if "code.py" in all_files else "ide_debug_main"
        )
        # Let the board's filesystem settle before importing.
        QTimer.singleShot(400, self._send_import)

    def _send_import(self):
        pending = self._pending_start
        if pending is None:
            return
        self._status("Clearing module cache...", CS_TEXT_MUTED)
        # A second `from ide_debug_code import *` in the same board session is
        # a no-op, because the module is already in sys.modules. It produces no
        # output and no start marker. Drop the cached copies first.
        # Written as one simple statement so the REPL does not go into
        # continuation mode waiting for a blank line.
        self._tx(
            b"import sys; [sys.modules.pop(k, None) for k in list(sys.modules)"
            b" if k.startswith('ide_debug_')]\r"
        )
        self._wait_for(self._PROMPT, 3000, self._on_purge_result)

    def _on_purge_result(self, ok: bool):
        pending = self._pending_start
        if pending is None:
            return
        # Not fatal if the purge did not confirm; a cold first run has nothing
        # cached anyway, and the import below is the real test.
        entry = pending.get("entry", "ide_debug_code")
        self._status("Starting session...", CS_TEXT_MUTED)
        self._tx(f"from {entry} import *\r".encode())
        self._wait_for(DEBUG_START, 10000, self._on_session_started)

    def _on_session_started(self, ok: bool):
        if self._pending_start is None:
            return
        if not ok:
            self._start_failed(
                "Debug Session Did Not Start",
                "The board accepted the import but never printed the debug "
                "start marker within 10 seconds.\n\n"
                "If the file does a lot of work before its first statement, "
                "give it another try. Otherwise check the REPL for a traceback."
            )
            return
        self._pending_start = None
        self._status("Running", _C_START)
        self._update_toolbar_state()

    def _send(self, signal: str):
        """Send a debug protocol signal over serial."""
        if self._repl and self._repl.is_connected:
            self._repl._write_bytes((signal + "\r").encode())

    def _on_restart(self):
        if not self._drive or not os.path.isdir(self._drive):
            return
        if not self._repl or not self._repl.is_connected:
            return

        all_files = get_all_python_files(self._drive)
        debug_files = self._config_page.get_debug_files()
        if not debug_files:
            debug_files = [f for f in all_files if f == "code.py"] or all_files[:1]

        self._save_drive_tabs()
        self._begin_start(debug_files)

    def _on_stop(self):
        self._clear_wait()
        self._pending_start = None
        if self._repl and self._repl.is_connected:
            self._repl._write_bytes(b"\x03")
        self._debugger_running = False
        self._debugger_halted  = False
        self._status("Stopped", _C_STOP)
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
        self._status("Running", _C_START)
        self._update_toolbar_state()
        self._send(DEBUG_SIGNAL_S)

    def _on_continue_log(self):
        self._debugger_halted = False
        self._status("Running (logging)", _C_START)
        self._update_toolbar_state()
        self._send(DEBUG_SIGNAL_CW)

    def _on_continue(self):
        self._debugger_halted = False
        self._status("Running", _C_START)
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