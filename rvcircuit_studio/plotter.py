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
import collections

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from .common import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QCheckBox, QSpinBox, QComboBox, QFrame, Qt, Signal, QTimer,
    CS_BG_DEEP, CS_SURFACE, CS_ACCENT, CS_ACCENT_SOFT,
    CS_TEXT, CS_TEXT_MUTED, CS_PRIMARY, CS_SUCCESS, CS_WARNING, CS_DANGER,
)

try:
    import pyqtgraph as pg
    pg.setConfigOption("background", CS_BG_DEEP)
    pg.setConfigOption("foreground", CS_TEXT)
    pg.setConfigOption("antialias", True)
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

_TRACE_COLOURS = [
    "#58A6FF",   # blue   (accent)
    "#3FB950",   # green  (success)
    "#F0883E",   # orange
    "#BC8CFF",   # purple
    "#FF7B72",   # red
    "#79C0FF",   # sky
    "#D2A679",   # tan
    "#56D364",   # lime
]

_DEFAULT_WINDOW = 200   # samples kept per trace

class SerialPlotter(QWidget):
    """
    Real-time plotter widget.  Drop-in replacement for the placeholder
    QTextEdit that was in _build_plotter_panel().

    Public API
    ----------
    feed(text: str)   - called by main_window via data_received signal
    clear()           - wipe all traces
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._traces: dict[str, dict] = {}   # name → {buf, curve, colour_idx}
        self._window = _DEFAULT_WINDOW
        self._paused = True
        self._line_buf = ""                  # partial line accumulator
        self._sample_counter = 0

        if HAS_PYQTGRAPH:
            self._build_pyqtgraph_ui()
        else:
            self._build_fallback_ui()

    def _build_pyqtgraph_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        ctrl = QWidget()
        ctrl.setFixedHeight(36)
        ctrl.setStyleSheet(f"background:{CS_SURFACE}; border-radius:4px;")
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(8, 2, 8, 2)
        ctrl_layout.setSpacing(8)

        lbl_win = QLabel("Window:")
        lbl_win.setStyleSheet(f"color:{CS_TEXT_MUTED}; background:transparent;")
        self._spin_window = QSpinBox()
        self._spin_window.setRange(20, 2000)
        self._spin_window.setValue(_DEFAULT_WINDOW)
        self._spin_window.setSingleStep(50)
        self._spin_window.setFixedWidth(70)
        self._spin_window.setStyleSheet(
            f"QSpinBox {{ background:{CS_BG_DEEP}; color:{CS_TEXT}; "
            f"border:1px solid {CS_ACCENT_SOFT}; border-radius:3px; padding:2px 4px; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width:14px; }}"
        )
        self._spin_window.valueChanged.connect(self._on_window_changed)

        self._btn_pause = QPushButton("▶  Resume")
        self._btn_pause.setFixedWidth(90)
        self._btn_pause.setStyleSheet(
            f"QPushButton {{ background:{CS_PRIMARY}; color:#fff; "
            f"border:none; border-radius:3px; padding:3px 8px; }}"
            f"QPushButton:hover {{ background:#2EA043; color:#fff; }}"
        )
        self._btn_pause.clicked.connect(self._on_pause_toggle)

        btn_clear = QPushButton("✕  Clear")
        btn_clear.setFixedWidth(80)
        btn_clear.setStyleSheet(
            f"QPushButton {{ background:{CS_ACCENT_SOFT}; color:{CS_TEXT}; "
            f"border:none; border-radius:3px; padding:3px 8px; }}"
            f"QPushButton:hover {{ background:{CS_DANGER}; color:#fff; }}"
        )
        btn_clear.clicked.connect(self.clear)

        self._legend_label = QLabel("")
        self._legend_label.setStyleSheet(
            f"color:{CS_TEXT_MUTED}; background:transparent; font-size:9pt;"
        )
        self._legend_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        ctrl_layout.addWidget(lbl_win)
        ctrl_layout.addWidget(self._spin_window)
        ctrl_layout.addWidget(self._btn_pause)
        ctrl_layout.addWidget(btn_clear)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self._legend_label)

        self._plot_widget = pg.PlotWidget()
        self._plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self._plot_widget.setMenuEnabled(False)
        self._plot_widget.setLabel("bottom", "Samples")
        self._plot_widget.setLabel("left", "Value")
        self._plot_widget.getAxis("bottom").setStyle(tickFont=None)
        self._plot_widget.setStyleSheet(
            f"border: 1px solid {CS_ACCENT_SOFT}; border-radius: 4px;"
        )

        self._placeholder = pg.TextItem(
            "Serial Plotter - no data yet.\n"
            "From your board: print(f\"{x},{y},{z}\")\n"
            "or labelled:     print(f\"temp={t},hum={h}\")",
            color=CS_TEXT_MUTED,
            anchor=(0.5, 0.5),
        )
        self._placeholder.setPos(0, 0)
        self._plot_widget.addItem(self._placeholder)

        root.addWidget(ctrl)
        root.addWidget(self._plot_widget, stretch=1)

    def _build_fallback_ui(self):
        """Shown when pyqtgraph is not installed."""
        from .common import QTextEdit
        layout = QVBoxLayout(self)
        lbl = QLabel(
            "⚠  pyqtgraph not installed.\n"
            "Run:  pip install pyqtgraph"
        )
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color:{CS_WARNING}; font-size:11pt;")
        layout.addWidget(lbl)

    def feed(self, text: str):
        """Accept a raw serial chunk (may contain partial lines)."""
        if not HAS_PYQTGRAPH or self._paused:
            return
        self._line_buf += text
        while "\n" in self._line_buf:
            line, self._line_buf = self._line_buf.split("\n", 1)
            self._process_line(line.strip().rstrip("\r"))
        # Safety: if a stream never sends a newline, _line_buf would grow
        # forever. Cap it so a runaway/binary stream can't exhaust memory.
        if len(self._line_buf) > 65536:
            self._line_buf = self._line_buf[-4096:]

    def clear(self):
        """Remove all traces and reset the plot."""
        if not HAS_PYQTGRAPH:
            return
        for info in self._traces.values():
            self._plot_widget.removeItem(info["curve"])
        self._traces.clear()
        self._sample_counter = 0
        self._line_buf = ""
        self._placeholder.setVisible(True)
        self._update_legend()

    def _process_line(self, line: str):
        if not line:
            return

        line = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line)
        line = re.sub(r"\x1b\][^\x07]*\x07", "", line)
        line = line.strip()
        if not line:
            return

        if line == "---CLEAR---":
            self.clear()
            return

        labelled = self._try_parse_labelled(line)
        if labelled is not None:
            self._push_values(labelled)
            return

        plain = self._try_parse_csv(line)
        if plain is not None:
            named = {f"Ch {i+1}": v for i, v in enumerate(plain)}
            self._push_values(named)
            return

    def _try_parse_labelled(self, line: str):
        """
        Accept  temp=23.4,humidity=61  or  a=1 b=2  (space-separated too).
        Returns dict {name: float} or None if it doesn't look labelled.
        """
        tokens = re.findall(r"([A-Za-z_]\w*)\s*=\s*(-?[0-9]+(?:\.[0-9]*)?)", line)
        if not tokens:
            return None
        try:
            return {k: float(v) for k, v in tokens}
        except ValueError:
            return None

    def _try_parse_csv(self, line: str):
        """
        Accept   42   or   1.5,-3.2,100
        Returns list[float] or None.
        """
        parts = [p.strip() for p in line.split(",")]
        try:
            values = [float(p) for p in parts if p]
            if values:
                return values
        except ValueError:
            pass
        return None

    def _push_values(self, values: dict):
        """Add one sample point per trace name."""
        self._sample_counter += 1
        self._placeholder.setVisible(False)

        colour_idx = len(self._traces)
        # Cap distinct traces so a stream with changing labels can't grow them
        # without bound.
        _MAX_TRACES = 32
        for name, val in values.items():
            if name not in self._traces:
                if len(self._traces) >= _MAX_TRACES:
                    continue  # too many distinct series; ignore further new names
                col = _TRACE_COLOURS[colour_idx % len(_TRACE_COLOURS)]
                colour_idx += 1
                buf = collections.deque(maxlen=self._window)
                curve = self._plot_widget.plot(
                    pen=pg.mkPen(color=col, width=1.5),
                    name=name,
                )
                self._traces[name] = {
                    "buf": buf,
                    "curve": curve,
                    "colour": col,
                }
                self._update_legend()

            info = self._traces[name]
            info["buf"].append(val)
            x = list(range(self._sample_counter - len(info["buf"]), self._sample_counter))
            info["curve"].setData(x, list(info["buf"]))

        if self._sample_counter % 10 == 0:
            self._plot_widget.enableAutoRange(axis="y")

    def _update_legend(self):
        if not self._traces:
            self._legend_label.setText("")
            return
        parts = []
        for name, info in self._traces.items():
            col = info["colour"]
            parts.append(
                f'<span style="color:{col};">■</span> '
                f'<span style="color:{CS_TEXT};">{name}</span>'
            )
        self._legend_label.setText("  ".join(parts))

    def _on_window_changed(self, val: int):
        self._window = val
        for info in self._traces.values():
            old = list(info["buf"])
            info["buf"] = collections.deque(old[-val:], maxlen=val)

    def _on_pause_toggle(self):
        self._paused = not self._paused
        if self._paused:
            self._btn_pause.setText("▶  Resume")
            self._btn_pause.setStyleSheet(
                f"QPushButton {{ background:{CS_PRIMARY}; color:#fff; "
                f"border:none; border-radius:3px; padding:3px 8px; }}"
                f"QPushButton:hover {{ background:#2EA043; color:#fff; }}"
            )
        else:
            self._btn_pause.setText("⏸  Pause")
            self._btn_pause.setStyleSheet(
                f"QPushButton {{ background:{CS_ACCENT_SOFT}; color:{CS_TEXT}; "
                f"border:none; border-radius:3px; padding:3px 8px; }}"
                f"QPushButton:hover {{ background:{CS_ACCENT}; color:#fff; }}"
            )