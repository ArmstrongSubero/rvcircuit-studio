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
        # Stays None on the no-pyqtgraph fallback UI, which does not build
        # a plot to hang a placeholder on.
        self._placeholder = None
        self._window = _DEFAULT_WINDOW
        # Start live. Starting paused made the panel look broken until the
        # user noticed the Resume button.
        self._paused = False
        self._line_buf = ""                  # partial line accumulator
        self._sample_counter = 0
        self._recording = False
        self._xy_mode = False
        self._record_data: dict[str, list] = {}  # name -> [(sample, value)]

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

        self._btn_record = QPushButton("Record")
        self._btn_record.setFixedWidth(80)
        self._btn_record.setStyleSheet(
            f"QPushButton {{ background:{CS_ACCENT_SOFT}; color:{CS_TEXT}; "
            f"border:none; border-radius:3px; padding:3px 8px; }}"
            f"QPushButton:hover {{ background:{CS_DANGER}; color:#fff; }}"
        )
        self._btn_record.clicked.connect(self._on_record_toggle)

        self._btn_analyze = QPushButton("Analyze")
        self._btn_analyze.setFixedWidth(80)
        self._btn_analyze.setEnabled(False)
        self._btn_analyze.setStyleSheet(
            f"QPushButton {{ background:{CS_ACCENT_SOFT}; color:{CS_TEXT}; "
            f"border:none; border-radius:3px; padding:3px 8px; }}"
            f"QPushButton:hover {{ background:{CS_ACCENT}; color:#fff; }}"
        )
        self._btn_analyze.clicked.connect(self._on_analyze)

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
        ctrl_layout.addWidget(self._btn_record)
        ctrl_layout.addWidget(self._btn_analyze)

        self._btn_open_csv = QPushButton("Open CSV")
        self._btn_open_csv.setFixedWidth(80)
        self._btn_open_csv.setStyleSheet(
            f"QPushButton {{ background:{CS_ACCENT_SOFT}; color:{CS_TEXT}; "
            f"border:none; border-radius:3px; padding:3px 8px; }}"
            f"QPushButton:hover {{ background:{CS_ACCENT}; color:#fff; }}"
        )
        self._btn_open_csv.clicked.connect(self._on_open_csv)

        self._btn_xy = QPushButton("XY")
        self._btn_xy.setFixedWidth(40)
        self._btn_xy.setCheckable(True)
        self._btn_xy.setToolTip("XY mode: first column = X axis (for parametric/phase plots)")
        self._btn_xy.setStyleSheet(
            f"QPushButton {{ background:{CS_ACCENT_SOFT}; color:{CS_TEXT}; "
            f"border:none; border-radius:3px; padding:3px 6px; }}"
            f"QPushButton:checked {{ background:{CS_ACCENT}; color:#fff; }}"
            f"QPushButton:hover {{ background:{CS_ACCENT}; color:#fff; }}"
        )
        self._btn_xy.toggled.connect(self._on_xy_toggle)

        ctrl_layout.addWidget(self._btn_open_csv)
        ctrl_layout.addWidget(self._btn_xy)
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
        """Feed raw serial text to the plotter."""
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
        if self._placeholder is not None:
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

        # Tuple format: the #1 format in every Adafruit CircuitPython
        # plotting tutorial.  print((light.value,)) outputs "(23456,)";
        # print((x, y, z)) outputs "(1.2, -3.4, 0.5)".
        # Try this BEFORE plain CSV so that parenthesized lines are handled
        # correctly instead of failing float("(42") silently.
        tupled = self._try_parse_tuple(line)
        if tupled is not None:
            named = {f"Ch {i+1}": v for i, v in enumerate(tupled)}
            self._push_values(named)
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
        # Accept scientific notation and a leading dot: 1e-3 used to parse as
        # 1 and .5 was rejected outright.
        tokens = re.findall(
            r"([A-Za-z_]\w*)\s*=\s*"
            r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", line)
        if not tokens:
            return None
        try:
            return {k: float(v) for k, v in tokens}
        except ValueError:
            return None

    def _try_parse_tuple(self, line: str):
        """
        Parse Python tuple output from print().

        Adafruit's canonical CircuitPython plotting format:
          print((light.value,))    -> serial outputs "(23456,)"
          print((x, y, z))         -> serial outputs "(1.2, -3.4, 0.5)"
          print((True, False))     -> serial outputs "(True, False)"

        Returns list[float] or None.
        """
        # Must start with ( and end with ) to be a tuple line.
        if not line.startswith("(") or not line.endswith(")"):
            return None

        # Strip outer parens: "(42,)" -> "42,"
        inner = line[1:-1].strip()
        if not inner:
            return None

        # Split on comma, strip whitespace from each part.
        parts = [p.strip() for p in inner.split(",")]

        # Convert each part to float. Handle:
        #   - trailing comma in single-value tuples: (42,) -> ["42", ""]
        #   - True/False from button tutorials: (True, False) -> [1.0, 0.0]
        #   - integers and floats, positive and negative
        values = []
        for p in parts:
            if not p:
                continue  # trailing comma in (42,) produces empty string
            if p == "True":
                values.append(1.0)
            elif p == "False":
                values.append(0.0)
            elif p == "None":
                continue  # skip None values
            else:
                try:
                    values.append(float(p))
                except ValueError:
                    return None  # non-numeric content, not a data tuple

        return values if values else None

    def _try_parse_csv(self, line: str):
        """
        Accept   42   or   1.5,-3.2,100   or   0.314 0.309 -0.309
        Handles comma-separated AND space-separated numbers.
        Returns list[float] or None.
        """
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
            try:
                values = [float(p) for p in parts if p]
                if values:
                    return values
            except ValueError:
                pass
        parts = line.split()
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
        if self._placeholder is not None:
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

        # Update curves: XY mode or normal time mode
        names = list(self._traces.keys())
        if self._xy_mode and len(names) >= 2:
            x_buf = list(self._traces[names[0]]["buf"])
            self._traces[names[0]]["curve"].setData([], [])  # hide X trace
            for name in names[1:]:
                info = self._traces[name]
                y_buf = list(info["buf"])
                n = min(len(x_buf), len(y_buf))
                if n > 0:
                    info["curve"].setData(x_buf[-n:], y_buf[-n:])
        else:
            for name, info in self._traces.items():
                y = list(info["buf"])
                x = list(range(self._sample_counter - len(y), self._sample_counter))
                info["curve"].setData(x, y)

        if self._sample_counter % 10 == 0:
            self._plot_widget.enableAutoRange(axis="y")

        # Store data when recording
        if self._recording:
            for name, val in values.items():
                if name not in self._record_data:
                    self._record_data[name] = []
                self._record_data[name].append((self._sample_counter, val))

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

    def _on_xy_toggle(self, checked):
        """Toggle XY mode."""
        self._xy_mode = checked
        # Force a redraw of all traces
        if self._traces:
            names = list(self._traces.keys())
            if len(names) >= 2 and checked:
                x_name = names[0]
                x_buf = list(self._traces[x_name]["buf"])
                # Hide the X trace, show others against it
                self._traces[x_name]["curve"].setData([], [])
                for name in names[1:]:
                    info = self._traces[name]
                    y_buf = list(info["buf"])
                    n = min(len(x_buf), len(y_buf))
                    if n > 0:
                        info["curve"].setData(x_buf[-n:], y_buf[-n:])
                self._plot_widget.setLabel("bottom", x_name)
            else:
                # Back to time mode - redraw all normally
                for name, info in self._traces.items():
                    y = list(info["buf"])
                    x = list(range(self._sample_counter - len(y), self._sample_counter))
                    info["curve"].setData(x, y)
                self._plot_widget.setLabel("bottom", "Samples")
            self._plot_widget.enableAutoRange()

    def _on_record_toggle(self):
        self._recording = not self._recording
        if self._recording:
            self._record_data.clear()
            self._btn_record.setText("Stop Rec")
            self._btn_record.setStyleSheet(
                f"QPushButton {{ background:{CS_DANGER}; color:#fff; "
                f"border:none; border-radius:3px; padding:3px 8px; }}"
                f"QPushButton:hover {{ background:#da3633; color:#fff; }}"
            )
            self._btn_analyze.setEnabled(False)
            # Auto-resume if paused
            if self._paused:
                self._on_pause_toggle()
        else:
            self._btn_record.setText("Record")
            self._btn_record.setStyleSheet(
                f"QPushButton {{ background:{CS_ACCENT_SOFT}; color:{CS_TEXT}; "
                f"border:none; border-radius:3px; padding:3px 8px; }}"
                f"QPushButton:hover {{ background:{CS_DANGER}; color:#fff; }}"
            )
            self._btn_analyze.setEnabled(bool(self._record_data))
            # Auto-save recorded data to host
            if self._record_data:
                self._auto_save_recording()

    def _on_open_csv(self):
        """Open a CSV file in the analysis view."""
        from PySide6.QtWidgets import QFileDialog
        # Try to start in the CIRCUITPY drive if available
        start_dir = ""
        try:
            from .circuitpython_mode import detect_circuitpy
            cp = detect_circuitpy()
            if cp:
                start_dir = cp
        except Exception:
            pass
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV Data File", start_dir,
            "CSV Files (*.csv *.txt *.log);;All Files (*)"
        )
        if not path:
            return
        dataset = self._load_csv_file(path)
        if dataset:
            try:
                self._analyze_dataset(dataset, title=f"Analysis - {os.path.basename(path)}")
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Analysis Error", str(e))

    def _load_csv_file(self, path: str) -> dict:
        """Load CSV into dataset format. First column used as X if it looks like an index."""
        import csv as csv_mod
        dataset = {}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv_mod.reader(f)
                rows = list(reader)
            if not rows:
                return {}
            # Detect header
            first = rows[0]
            has_header = False
            for cell in first:
                cell = cell.strip()
                if cell:
                    try:
                        float(cell)
                    except ValueError:
                        has_header = True
                        break
            if has_header:
                headers = [c.strip() or f"col{i}" for i, c in enumerate(first)]
                data_rows = rows[1:]
            else:
                headers = [f"col{i}" for i in range(len(first))]
                data_rows = rows

            # Detect if the first column is an index/time column that should
            # be the X axis, not a data trace.
            _INDEX_NAMES = {"sample", "index", "time", "timestamp", "t",
                            "seconds", "ms", "elapsed", "col0"}
            x_col = None
            if headers and headers[0].lower() in _INDEX_NAMES:
                x_col = 0
            data_headers = [h for i, h in enumerate(headers) if i != x_col]

            # Parse the X values if we have an index column
            x_values = []
            if x_col is not None:
                for row in data_rows:
                    try:
                        x_values.append(float(row[x_col].strip()))
                    except (ValueError, IndexError):
                        x_values.append(None)

            # Initialize dataset for data columns only
            for h in data_headers:
                dataset[h] = []

            # Parse rows
            for idx, row in enumerate(data_rows):
                x = x_values[idx] if (x_col is not None and idx < len(x_values)
                                       and x_values[idx] is not None) else idx
                for col_idx, cell in enumerate(row):
                    if col_idx >= len(headers) or col_idx == x_col:
                        continue
                    h = headers[col_idx]
                    cell = cell.strip()
                    try:
                        val = float(cell)
                        dataset[h].append((x, val))
                    except (ValueError, IndexError):
                        pass
            # Remove empty columns
            dataset = {k: v for k, v in dataset.items() if v}
        except Exception:
            return {}
        return dataset

    def _auto_save_recording(self):
        """Save recording to ~/CircuitStudioData/."""
        import datetime
        try:
            home = os.path.expanduser("~")
            save_dir = os.path.join(home, "CircuitStudioData")
            os.makedirs(save_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(save_dir, f"recording_{ts}.csv")
            names = list(self._record_data.keys())
            all_samples = set()
            for data in self._record_data.values():
                for s, _ in data:
                    all_samples.add(s)
            rows = sorted(all_samples)
            lookup = {}
            for name, data in self._record_data.items():
                for s, v in data:
                    lookup[(name, s)] = v
            with open(path, "w", encoding="utf-8") as f:
                f.write("sample," + ",".join(names) + "\n")
                for s in rows:
                    vals = [str(lookup.get((n, s), "")) for n in names]
                    f.write(f"{s}," + ",".join(vals) + "\n")
        except Exception:
            pass

    def _analyze_dataset(self, dataset: dict, title: str = "Data Analysis"):
        """Open dataset in the analysis view."""
        if not dataset:
            return
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                        QHBoxLayout, QPushButton, QCheckBox)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Plotter - {title}")
        dlg.setMinimumSize(900, 560)
        dlg.setStyleSheet(f"QDialog {{ background: {CS_BG_DEEP}; }}")
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # --- Stats bar ---
        stats_parts = []
        names_list = list(dataset.keys())
        for name in names_list:
            data = dataset[name]
            vals = [v for _, v in data]
            if vals:
                mn, mx, avg = min(vals), max(vals), sum(vals) / len(vals)
                std = (sum((v - avg) ** 2 for v in vals) / len(vals)) ** 0.5
                stats_parts.append(
                    f'<b>{name}</b>: '
                    f'min={mn:.2f}  max={mx:.2f}  avg={avg:.2f}  '
                    f'std={std:.2f}  ({len(vals)} pts)'
                )
        stats = QLabel("  |  ".join(stats_parts))
        stats.setStyleSheet(f"color:{CS_TEXT}; font-size:10px; padding:4px;")
        stats.setWordWrap(True)
        layout.addWidget(stats)

        legend_row = QHBoxLayout()
        legend_row.setSpacing(12)
        legend_row.addWidget(QLabel("Traces:"))
        trace_curves = {}

        # --- Plot ---
        plot = pg.PlotWidget()
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setLabel("bottom", "Sample")
        plot.setLabel("left", "Value")
        plot.setMouseEnabled(x=True, y=True)

        # Crosshair + coordinate readout
        vline = pg.InfiniteLine(angle=90, movable=False,
                                pen=pg.mkPen(CS_TEXT_MUTED, width=1))
        hline = pg.InfiniteLine(angle=0, movable=False,
                                pen=pg.mkPen(CS_TEXT_MUTED, width=1))
        plot.addItem(vline, ignoreBounds=True)
        plot.addItem(hline, ignoreBounds=True)
        cursor_label = pg.TextItem("", color=CS_TEXT, anchor=(0, 1))
        plot.addItem(cursor_label, ignoreBounds=True)

        # Per-point hover: find nearest point and show its value
        all_curve_data = []
        import bisect as _bisect

        def _mouse_moved(evt):
            pos = evt if hasattr(evt, "x") else evt[0]
            if not plot.sceneBoundingRect().contains(pos):
                return
            mp = plot.plotItem.vb.mapSceneToView(pos)
            vline.setPos(mp.x())
            hline.setPos(mp.y())
            # Find nearest point across all visible traces
            best = None
            best_dist = float("inf")
            for cname, cx, cy, curve in all_curve_data:
                if not curve.isVisible():
                    continue
                if not cx:
                    continue
                # Binary search for nearest x
                idx = _bisect.bisect_left(cx, mp.x())
                for check in (max(0, idx - 1), min(idx, len(cx) - 1)):
                    dx = abs(cx[check] - mp.x())
                    if dx < best_dist:
                        best_dist = dx
                        best = (cname, cx[check], cy[check])
            if best:
                cursor_label.setText(
                    f"x={mp.x():.1f}  y={mp.y():.3f}\n"
                    f"{best[0]}: ({best[1]:.0f}, {best[2]:.3f})"
                )
            else:
                cursor_label.setText(f"x={mp.x():.1f}  y={mp.y():.3f}")
            cursor_label.setPos(mp.x(), mp.y())
        plot.scene().sigMouseMoved.connect(_mouse_moved)

        # Draw traces + build clickable legend checkboxes
        colour_idx = 0
        for name in names_list:
            data = dataset[name]
            x = [s for s, _ in data]
            y = [v for _, v in data]
            col = _TRACE_COLOURS[colour_idx % len(_TRACE_COLOURS)]
            colour_idx += 1
            curve = plot.plot(x, y, pen=pg.mkPen(color=col, width=1.5), name=name)
            trace_curves[name] = curve
            all_curve_data.append((name, x, y, curve))

            # Clickable legend checkbox
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.setStyleSheet(
                f"QCheckBox {{ color: {col}; font-weight: bold; font-size: 10px; }}"
            )
            _curve_ref = curve
            cb.toggled.connect(lambda checked, c=_curve_ref: c.setVisible(checked))
            legend_row.addWidget(cb)

        legend_row.addStretch()

        # XY mode toggle for parametric/phase plots
        if len(names_list) >= 2:
            xy_cb = QCheckBox("XY")
            xy_cb.setToolTip("Use first column as X axis (parametric/phase plots)")
            xy_cb.setStyleSheet(f"QCheckBox {{ color: {CS_ACCENT}; font-weight: bold; font-size: 10px; }}")
            def _toggle_xy(checked):
                if checked and len(names_list) >= 2:
                    x_name = names_list[0]
                    x_data = [v for _, v in dataset[x_name]]
                    # Hide the first trace, replot others against it
                    trace_curves[x_name].setData([], [])
                    for i, name in enumerate(names_list[1:]):
                        y_data = [v for _, v in dataset[name]]
                        n = min(len(x_data), len(y_data))
                        trace_curves[name].setData(x_data[:n], y_data[:n])
                        # Update all_curve_data for hover
                        all_curve_data[i + 1] = (name, x_data[:n], y_data[:n], trace_curves[name])
                    plot.setLabel("bottom", x_name)
                    plot.enableAutoRange()
                else:
                    # Restore normal index-based plotting
                    for i, name in enumerate(names_list):
                        x = [s for s, _ in dataset[name]]
                        y = [v for _, v in dataset[name]]
                        trace_curves[name].setData(x, y)
                        all_curve_data[i] = (name, x, y, trace_curves[name])
                    plot.setLabel("bottom", "Sample")
                    plot.enableAutoRange()
            xy_cb.toggled.connect(_toggle_xy)
            legend_row.addWidget(xy_cb)

        # Sample count label
        total = sum(len(d) for d in dataset.values())
        count_lbl = QLabel(f"{total} samples")
        count_lbl.setStyleSheet(f"color:{CS_TEXT_MUTED}; font-size:10px;")
        legend_row.addWidget(count_lbl)

        layout.addLayout(legend_row)
        layout.addWidget(plot, stretch=1)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        # Auto-fit button
        fit_btn = QPushButton("Auto Fit")
        fit_btn.setFixedWidth(80)
        fit_btn.clicked.connect(lambda: plot.enableAutoRange())
        btn_row.addWidget(fit_btn)
        btn_row.addStretch()
        export_btn = QPushButton("Export CSV")
        export_btn.setFixedWidth(100)
        export_btn.clicked.connect(lambda: self._export_dataset_csv(dlg, dataset))
        btn_row.addWidget(export_btn)
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dlg.exec()

    def _export_dataset_csv(self, parent, dataset):
        """Export any dataset to CSV."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            parent, "Export CSV", "plotter_data.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        names = list(dataset.keys())
        all_samples = set()
        for data in dataset.values():
            for s, _ in data:
                all_samples.add(s)
        rows = sorted(all_samples)
        lookup = {}
        for name, data in dataset.items():
            for s, v in data:
                lookup[(name, s)] = v
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("sample," + ",".join(names) + "\n")
                for s in rows:
                    vals = [str(lookup.get((n, s), "")) for n in names]
                    f.write(f"{s}," + ",".join(vals) + "\n")
        except Exception:
            pass

    def _on_analyze(self):
        """Open recorded data in the analysis view."""
        if not self._record_data:
            return
        try:
            self._analyze_dataset(self._record_data, title="Recorded Data Analysis")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Analysis Error", str(e))

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