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

class REPLWidget(QTextEdit):
    data_received = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(False)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

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
        self._ansi_re    = re.compile(r'\x1b\[([0-9;]*)([A-Za-z])')
        self._cur_fg     = _DEFAULT_FG
        self._cur_bold   = False
        self._paste_mode = False

        self._append_system("RV Circuit Studio — CircuitPython REPL")
        self._append_system("Connect a CircuitPython board to get started.")

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

        if key == Qt.Key.Key_Backspace:
            self._write_bytes(b'\x7f')
            return
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._write_bytes(b'\r\n')
            return
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down,
                     Qt.Key.Key_Left, Qt.Key.Key_Right):
            return
        elif key == Qt.Key.Key_Delete:
            self._write_bytes(b'\x1b[3~')
            return

        text = event.text()
        if text:
            self._write_bytes(text.encode('utf-8', errors='replace'))

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
                try:
                    text = self._utf8_buf.decode('utf-8')
                    self._utf8_buf = b""
                except UnicodeDecodeError:
                    text = self._utf8_buf.decode('utf-8', errors='replace')
                    self._utf8_buf = b""
                self._process_vt100(text)
                self.data_received.emit(text)
        except Exception as e:
            self._append_error(f"Read error: {e}")
            self.disconnect()

    def _process_vt100(self, text: str):
        text = text.replace('\x7f', '')
        import re as _re
        text = _re.sub(r'\x1b\].*?(?:\x07|\x1b\\)', '', text)
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
        fmt.setForeground(QColor(CS_DANGER))
        cursor.mergeCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()