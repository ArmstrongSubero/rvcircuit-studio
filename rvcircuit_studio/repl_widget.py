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

import re

from .common import (
    QTextEdit, QTimer, QColor, QTextCursor, Signal, Qt,
    CS_BG_DEEP, CS_TEXT, CS_SUCCESS, CS_DANGER, CS_WARNING, CS_ACCENT,
)
from PySide6.QtCore import QObject
from PySide6.QtGui import QTextCharFormat, QFont, QKeyEvent

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

_SGR_FG = {
    30: "#000000", 31: CS_DANGER,   32: CS_SUCCESS, 33: CS_WARNING,
    34: CS_ACCENT, 35: "#B794F6",   36: "#79C0FF",  37: CS_TEXT,
    90: "#666666", 91: "#FF7B72",   92: "#56D364",  93: "#E3B341",
    94: "#79C0FF", 95: "#D2A8FF",   96: "#56D364",  97: "#F0F6FC",
}
_DEFAULT_FG = CS_TEXT
_DEFAULT_BG = CS_BG_DEEP


def _decode_keep_incomplete(buf: bytes):
    """Decode as much valid UTF-8 as possible from buf. Returns (text, rest)
    where rest is any trailing bytes that form an incomplete multibyte
    character and should be carried into the next read. Truly invalid bytes
    (not just incomplete) are replaced so we never get permanently stuck."""
    try:
        return buf.decode("utf-8"), b""
    except UnicodeDecodeError as e:
        # If the error is at the very end, it's an incomplete trailing char:
        # decode the good prefix and keep the tail.
        if e.end >= len(buf) and e.start < len(buf):
            good = buf[:e.start].decode("utf-8", errors="replace")
            return good, buf[e.start:]
        # Otherwise it's bad data mid-stream: replace and flush.
        return buf.decode("utf-8", errors="replace"), b""


def _resolve_mono_font(size: int) -> QFont:
    """Return a monospace QFont using whichever family is actually installed,
    so Qt doesn't emit the slow 'missing font family' alias-lookup warning.
    Tries a few common monospace names in order, then falls back to the system
    fixed-pitch font."""
    from PySide6.QtGui import QFontDatabase
    try:
        available = set(QFontDatabase.families())
    except Exception:
        available = set()
    for name in ("JetBrains Mono NL", "JetBrains Mono", "Cascadia Mono",
                 "Consolas", "DejaVu Sans Mono", "Menlo", "Courier New"):
        if name in available:
            f = QFont(name, size)
            f.setStyleHint(QFont.StyleHint.Monospace)
            return f
    # Last resort: ask Qt for its standard fixed-pitch font.
    try:
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(size)
        return f
    except Exception:
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(size)
        return f

class REPLWidget(QTextEdit):
    data_received = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(False)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        # Cap scrollback so a board streaming output for hours can't grow the
        # document until the editor slows to a crawl. Old lines roll off the top.
        self.document().setMaximumBlockCount(5000)

        font = _resolve_mono_font(10)
        self.setFont(font)
        self.document().setDefaultFont(font)
        self._mono_font = font

        palette = self.palette()
        from PySide6.QtGui import QPalette
        palette.setColor(QPalette.ColorRole.Base, QColor(CS_BG_DEEP))
        palette.setColor(QPalette.ColorRole.Text, QColor(CS_TEXT))
        self.setPalette(palette)

        self._serial     = None
        self._port       = None
        self._baud       = 115200
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll_serial)

        self._utf8_buf   = b""
        self._pending_cr = False
        self._ansi_re    = re.compile(r'\x1b\[([0-9;]*)([A-Za-z])')
        self._cur_fg     = _DEFAULT_FG
        self._cur_bold   = False
        self._paste_mode = False
        self._debug_mode = False
        self._alt_screen = False
        self._dbg_hold   = ""   # partial debug frame carried across polls
        self._osc_hold   = ""   # partial OSC title sequence

        self._append_system("RV Circuit Studio - CircuitPython REPL")
        self._append_system("Connect a CircuitPython board to get started.")

    def set_font_size(self, size: int):
        font = _resolve_mono_font(size)
        self._mono_font = font
        self._mono_size = size
        self.setFont(font)
        self.document().setDefaultFont(font)
        # Reformat all existing text
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        fmt.setFontFamilies([font.family()])
        cursor.mergeCharFormat(fmt)
        cursor.clearSelection()
        self.setTextCursor(cursor)

    def connect(self, port: str, baud: int = 115200):
        if not HAS_SERIAL:
            self._append_error("pyserial not installed. Run: pip install pyserial")
            return False
        if self._serial and self._serial.is_open:
            self.disconnect()
        try:
            self._port   = port
            self._baud   = baud
            self._serial = serial.Serial(port, baud, timeout=0)
            self._poll_timer.start()
            self._append_system(f"\nConnected to {port} at {baud} baud\n")
            return True
        except Exception as e:
            self._append_error(f"Connection failed: {e}")
            return False

    def disconnect(self):
        self._poll_timer.stop()
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self._append_system("\nDisconnected.\n")

    @property
    def is_connected(self):
        return self._serial is not None and self._serial.is_open

    def send_interrupt(self):
        self._write_bytes(b'\x03')

    def send_soft_reboot(self):
        self._write_bytes(b'\x04')

    def clear_output(self):
        self.clear()
        self._append_system("REPL cleared.")

    def keyPressEvent(self, event: QKeyEvent):
        key  = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)

        if not self.is_connected:
            if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
                super().keyPressEvent(event)
            return

        if ctrl:
            if key == Qt.Key.Key_C:
                self._write_bytes(b'\x03')
                return
            elif key == Qt.Key.Key_D:
                self._write_bytes(b'\x04')
                return
            elif key == Qt.Key.Key_E:
                self._write_bytes(b'\x05')
                self._paste_mode = True
                return
            elif key == Qt.Key.Key_A:
                self.selectAll()
                return
            elif key == Qt.Key.Key_V:
                self.paste_to_board()
                return
            elif key == Qt.Key.Key_X:
                self.copy()          # never cut the transcript
                return

        if key == Qt.Key.Key_Backspace:
            self._write_bytes(b'\x7f')
            return
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._write_bytes(b'\r\n')
            return
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down,
                     Qt.Key.Key_Left, Qt.Key.Key_Right):
            # Forward to the board's own line editor so the REPL has history
            # and in-line cursor movement. These used to be swallowed.
            self._write_bytes({
                Qt.Key.Key_Up:    b'\x1b[A',
                Qt.Key.Key_Down:  b'\x1b[B',
                Qt.Key.Key_Right: b'\x1b[C',
                Qt.Key.Key_Left:  b'\x1b[D',
            }[key])
            return
        elif key == Qt.Key.Key_Home:
            # NOT Ctrl+A: on an empty line that drops the board into the raw
            # REPL. The board's line editor understands the escape form.
            self._write_bytes(b'\x1b[H')
            return
        elif key == Qt.Key.Key_End:
            # NOT Ctrl+E: that is paste mode, not end-of-line.
            self._write_bytes(b'\x1b[F')
            return
        elif key == Qt.Key.Key_Tab:
            self._write_bytes(b'\t')
            return
        elif key == Qt.Key.Key_Delete:
            self._write_bytes(b'\x1b[3~')
            return

        text = event.text()
        if not text:
            return
        if ctrl:
            # Pass through any other Ctrl combination as its control byte,
            # the way a terminal would. Qt already gives us that in text().
            if len(text) == 1 and ord(text[0]) < 0x20:
                self._write_bytes(text.encode('latin-1'))
            return
        self._write_bytes(text.encode('utf-8', errors='replace'))

    def paste_to_board(self):
        """Send the clipboard to the board.

        Multi-line pastes go through CircuitPython's paste mode (Ctrl+E, body,
        Ctrl+D) so auto-indent does not mangle them. Previously Ctrl+V fell
        through and sent a raw 0x16 byte.
        """
        from PySide6.QtWidgets import QApplication
        data = QApplication.clipboard().text()
        if not data or not self.is_connected:
            return
        data = data.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" in data.rstrip("\n"):
            self._write_bytes(b'\x05')                     # enter paste mode
            self._write_bytes(data.encode('utf-8', errors='replace'))
            self._write_bytes(b'\x04')                     # execute
        else:
            self._write_bytes(data.rstrip("\n").encode('utf-8', errors='replace'))

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_copy  = menu.addAction("Copy")
        act_paste = menu.addAction("Paste to Board")
        act_clear = menu.addAction("Clear")
        act_copy.setEnabled(self.textCursor().hasSelection())
        act_paste.setEnabled(self.is_connected)
        chosen = menu.exec(event.globalPos())
        if chosen is act_copy:
            self.copy()
        elif chosen is act_paste:
            self.paste_to_board()
        elif chosen is act_clear:
            self.clear()

    def _write_bytes(self, data: bytes):
        if self._serial and self._serial.is_open:
            try:
                self._serial.write(data)
            except Exception as e:
                self._append_error(f"Write error: {e}")
                self.disconnect()

    def _poll_serial(self):
        if not self._serial or not self._serial.is_open:
            return
        try:
            waiting = self._serial.in_waiting
            if waiting > 0:
                raw = self._serial.read(waiting)
                self._utf8_buf += raw
                # Decode as much as possible; if the chunk ends mid-multibyte
                # character, keep the incomplete tail in the buffer for the next
                # poll instead of corrupting it with replacement chars.
                text, self._utf8_buf = _decode_keep_incomplete(self._utf8_buf)
                if not text:
                    return
                # CircuitPython ends lines with \r\n. A poll boundary can land
                # between the \r and \n, and a lone \r reads as its own line
                # break, producing a stray blank line. Collapse \r\n to \n, turn
                # any lone \r into \n, but hold a trailing \r in case its \n
                # its \n arrives in the next chunk.
                pending_cr = getattr(self, "_pending_cr", False)
                if pending_cr:
                    text = "\r" + text
                    self._pending_cr = False
                if text.endswith("\r"):
                    self._pending_cr = True
                    text = text[:-1]
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                if not text:
                    return
                # Always emit raw text to the debugger panel / plotter.
                self.data_received.emit(text)
                if self._debug_mode:
                    # Hide the protocol frames, keep user output and tracebacks.
                    shown = self._strip_debug_frames(text)
                    if shown:
                        self._process_vt100(shown)
                else:
                    self._process_vt100(text)
        except Exception as e:
            self._append_error(f"Read error: {e}")
            self.disconnect()

    def _process_vt100(self, text: str):
        text = text.replace('\x7f', '')
        import re as _re
        # CircuitPython sets the terminal title with an OSC sequence. If the
        # terminator lands in the next poll the old single-shot regex missed
        # it and the payload printed, so carry an unterminated one forward.
        text = self._osc_hold + text
        self._osc_hold = ""
        text = _re.sub(r'\x1b\].*?(?:\x07|\x1b\\)', '', text)
        osc = text.rfind('\x1b]')
        if osc != -1:
            tail = text[osc:]
            if '\x07' not in tail and '\x1b\\' not in tail:
                if len(tail) < 512:      # cap so a lost terminator can't stall
                    self._osc_hold = tail
                text = text[:osc]
        if not text:
            return
        pos = 0
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        while pos < len(text):
            ch = text[pos]

            if ch == '\x08':
                cursor.movePosition(QTextCursor.MoveOperation.Left,
                                    QTextCursor.MoveMode.MoveAnchor, 1)
                cursor.deleteChar()
                pos += 1
                continue

            next_special = len(text)
            esc_idx = text.find('\x1b', pos)
            bs_idx  = text.find('\x08', pos)
            if esc_idx >= 0:
                next_special = min(next_special, esc_idx)
            if bs_idx >= 0:
                next_special = min(next_special, bs_idx)

            if next_special == len(text):
                self._insert_text(cursor, text[pos:])
                break

            if next_special > pos:
                self._insert_text(cursor, text[pos:next_special])
                pos = next_special
                continue

            if text[pos] == '\x1b':
                m = self._ansi_re.match(text, pos)
                if m:
                    self._handle_csi(cursor, m.group(1), m.group(2))
                    pos = m.end()
                else:
                    pos += 1

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _handle_csi(self, cursor: QTextCursor, params_str: str, cmd: str):
        params = [int(p) if p else 0 for p in params_str.split(';')] if params_str else [0]
        n = params[0] if params else 0

        if cmd == 'm':
            self._handle_sgr(params)
        elif cmd == 'K':
            if n == 0:
                cursor.movePosition(QTextCursor.MoveOperation.EndOfLine,
                                    QTextCursor.MoveMode.KeepAnchor)
            elif n == 1:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine,
                                    QTextCursor.MoveMode.KeepAnchor)
            elif n == 2:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfLine,
                                    QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        elif cmd == 'J':
            if n == 2:
                self.clear()

    def _handle_sgr(self, params):
        if not params or params == [0]:
            self._cur_fg   = _DEFAULT_FG
            self._cur_bold = False
            return
        for code in params:
            if code == 0:
                self._cur_fg   = _DEFAULT_FG
                self._cur_bold = False
            elif code == 1:
                self._cur_bold = True
            elif code == 22:
                self._cur_bold = False
            elif code in _SGR_FG:
                self._cur_fg = _SGR_FG[code]

    def _insert_text(self, cursor: QTextCursor, text: str):
        if not text:
            return
        fmt = QTextCharFormat()
        fmt.setFont(self._mono_font)
        fmt.setForeground(QColor(self._cur_fg))
        if self._cur_bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        else:
            fmt.setFontWeight(QFont.Weight.Normal)
        cursor.mergeCharFormat(fmt)
        cursor.insertText(text)

    def _append_system(self, text: str):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setFont(self._mono_font)
        fmt.setForeground(QColor(CS_ACCENT))
        fmt.setFontItalic(True)
        cursor.mergeCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _append_error(self, text: str):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setFont(self._mono_font)
        fmt.setForeground(QColor(CS_DANGER))
        cursor.mergeCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    _ALT_ON  = "\x1b[?1049h"
    _ALT_OFF = "\x1b[?1049l"
    _SIG_RE  = re.compile(r"\[(?:S|CW|CO)\][ \t]*\r?\n?")
    # Tokens that must never be split across a poll boundary. _ALT_ON is in
    # here because it begins with ESC-[, so a naive hold of a trailing "["
    # would strand the ESC and break frame detection entirely.
    _WHOLE_TOKENS = ("\x1b[?1049h", "[S]\r\n", "[CW]\r\n", "[CO]\r\n")

    @classmethod
    def _partial_tail(cls, s: str) -> int:
        """Length of the longest suffix of *s* that is a proper prefix of a
        token we need to see whole."""
        best = 0
        for tok in cls._WHOLE_TOKENS:
            for n in range(min(len(tok) - 1, len(s)), best, -1):
                if s.endswith(tok[:n]):
                    best = n
                    break
        return best

    def _strip_debug_frames(self, text: str) -> str:
        """
        Remove the alternate screen blocks the debugger uses to carry its JSON
        state, plus the signal tokens the board echoes back from input(),
        leaving everything else (user prints, tracebacks) visible.

        Frames and signals can straddle a poll boundary, so an incomplete one
        is held back rather than printed. The holdback is capped so a lost
        terminator cannot stall output permanently.
        """
        buf = self._dbg_hold + text
        out = []
        while True:
            start = buf.find(self._ALT_ON)
            if start == -1:
                out.append(buf)
                buf = ""
                break
            end = buf.find(self._ALT_OFF, start)
            if end == -1:
                out.append(buf[:start])
                buf = buf[start:]        # incomplete frame, wait for the rest
                break
            out.append(buf[:start])
            buf = buf[end + len(self._ALT_OFF):]

        shown = "".join(out)

        n = self._partial_tail(shown)
        if n:
            buf = shown[-n:] + buf
            shown = shown[:-n]

        self._dbg_hold = buf
        if len(self._dbg_hold) > 4096:
            self._dbg_hold = ""

        # Consume the whole echoed line, not just the token, or every signal
        # leaves a blank line behind.
        return self._SIG_RE.sub("", shown)

    def _filter_debug_noise(self, text: str) -> str:
        """Strip debug protocol noise from display."""
        import re as _re
        # Strip alternate screen buffer blocks (the debug JSON).
        text = _re.sub(r'\x1b\[\?1049h.*?\x1b\[\?1049l', '', text, flags=_re.DOTALL)
        # Strip protocol signals.
        text = text.replace('[S]', '').replace('[CW]', '').replace('[CO]', '')
        # Strip debug session markers.
        text = text.replace('==== Start Debugging ====', '')
        text = text.replace('==== End Debugging ====', '')
        # Strip the debug import command.
        text = _re.sub(r'from ide_debug_\w+ import \*', '', text)
        # Strip Ctrl-C/Ctrl-D echo artifacts.
        text = text.replace('\x03', '').replace('\x04', '')
        # Collapse all blank lines and leading/trailing whitespace.
        text = _re.sub(r'\n\s*\n', '\n', text)
        text = text.strip()
        # If nothing meaningful remains, return empty.
        if not text or text == '>>>' or text == '>>> ':
            return ''
        return text