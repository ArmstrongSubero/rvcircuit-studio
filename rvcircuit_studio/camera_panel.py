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

"""
Live webcam panel for documenting hardware setups.

Frames are converted to QImage and flip/rotate/zoom applied with QTransform, so
behaviour is the same on every platform regardless of the capture backend.
"""

from .common import *

try:
    from PySide6.QtMultimedia import (
        QMediaDevices, QCamera, QMediaCaptureSession, QVideoSink, QVideoFrame
    )
    from PySide6.QtGui import QImage, QPixmap, QTransform
    HAS_MULTIMEDIA = True
except Exception:
    HAS_MULTIMEDIA = False


class _FrameView(QLabel):
    """Paints the latest frame, scaled to fit while keeping aspect ratio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #000;")
        self.setMinimumHeight(180)
        self._pixmap = None

    def set_frame(self, pixmap):
        self._pixmap = pixmap
        self._rescale()

    def _rescale(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def resizeEvent(self, event):
        self._rescale()
        super().resizeEvent(event)


class CameraPanel(QWidget):
    """
    Camera panel: device dropdown, start/stop, flip/rotate/zoom, snapshot,
    pop-out window. All transforms are applied in software so behaviour is
    identical across Windows, macOS and Linux.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._camera = None
        self._session = None
        self._sink = None
        self._popout = None
        self._popout_view = None
        self._last_image = None       # most recent untransformed QImage

        self._flip_h = False
        self._flip_v = False
        self._rotation = 0            # 0/90/180/270
        self._zoom = 1.0              # 1.0 .. 3.0

        self._build_ui()
        if HAS_MULTIMEDIA:
            self._refresh_devices()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        if not HAS_MULTIMEDIA:
            msg = QLabel(
                "Camera support is unavailable.\n"
                "Qt Multimedia could not be loaded on this system."
            )
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 10pt;")
            root.addWidget(msg)
            return

        controls = QHBoxLayout()
        controls.setSpacing(4)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(160)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        controls.addWidget(self.device_combo)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._toggle)
        controls.addWidget(self.start_btn)

        for label, slot, tip in (
            ("Flip H", self._toggle_flip_h, "Flip horizontally"),
            ("Flip V", self._toggle_flip_v, "Flip vertically"),
            ("Rotate", self._rotate, "Rotate 90 degrees"),
            ("Zoom +", self._zoom_in, "Zoom in"),
            ("Zoom -", self._zoom_out, "Zoom out"),
        ):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            controls.addWidget(b)

        self.snapshot_btn = QPushButton("Snapshot")
        self.snapshot_btn.setToolTip("Save the current frame as a PNG")
        self.snapshot_btn.clicked.connect(self._save_snapshot)
        controls.addWidget(self.snapshot_btn)

        self.popout_btn = QPushButton("Pop Out")
        self.popout_btn.setToolTip("Open the camera in a separate window")
        self.popout_btn.clicked.connect(self._popout_window)
        controls.addWidget(self.popout_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Rescan connected cameras")
        self.refresh_btn.clicked.connect(self._refresh_devices)
        controls.addWidget(self.refresh_btn)

        controls.addStretch()
        root.addLayout(controls)

        self.view = _FrameView()
        root.addWidget(self.view, 1)

        self.status = QLabel("Select a camera and press Start.")
        self.status.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        root.addWidget(self.status)

    # ------------------------------------------------------------- devices

    def _refresh_devices(self):
        if not HAS_MULTIMEDIA:
            return
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self._devices = QMediaDevices.videoInputs()
        if not self._devices:
            self.device_combo.addItem("No cameras found")
            self.device_combo.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.status.setText("No cameras detected. Connect one and Refresh.")
        else:
            self.device_combo.setEnabled(True)
            self.start_btn.setEnabled(True)
            for d in self._devices:
                self.device_combo.addItem(d.description())
        self.device_combo.blockSignals(False)

    def _on_device_changed(self, _idx):
        if self._camera is not None:
            self._stop()
            self._start()

    # ------------------------------------------------------------- control

    def _toggle(self):
        if self._camera is None:
            self._start()
        else:
            self._stop()

    def _start(self):
        if not HAS_MULTIMEDIA or not getattr(self, "_devices", None):
            return
        idx = self.device_combo.currentIndex()
        if idx < 0 or idx >= len(self._devices):
            return
        try:
            self._camera = QCamera(self._devices[idx])
            self._sink = QVideoSink()
            self._sink.videoFrameChanged.connect(self._on_frame)
            self._session = QMediaCaptureSession()
            self._session.setCamera(self._camera)
            self._session.setVideoSink(self._sink)
            self._camera.start()
            self.start_btn.setText("Stop")
            self.status.setText(f"Live: {self.device_combo.currentText()}")
        except Exception as e:
            self.status.setText(f"Could not start camera: {e}")
            self._teardown_capture()

    def _stop(self):
        self._teardown_capture()
        self.start_btn.setText("Start")
        self.status.setText("Stopped.")

    def _teardown_capture(self):
        try:
            if self._sink is not None:
                self._sink.videoFrameChanged.disconnect(self._on_frame)
        except Exception:
            pass
        try:
            if self._camera is not None:
                self._camera.stop()
        except Exception:
            pass
        self._camera = None
        self._session = None
        self._sink = None

    # ------------------------------------------------------------- frames

    def _on_frame(self, frame: "QVideoFrame"):
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self._last_image = image
        pixmap = QPixmap.fromImage(self._transform_image(image))
        # Paint into whichever surface is active (pop-out if open, else inline).
        if self._popout_view is not None:
            self._popout_view.set_frame(pixmap)
        else:
            self.view.set_frame(pixmap)

    def _transform_image(self, image: "QImage") -> "QImage":
        """Apply rotation, flips and zoom in software so the result is identical
        on every OS regardless of the capture backend."""
        t = QTransform()
        if self._rotation:
            t.rotate(self._rotation)
        if self._flip_h or self._flip_v:
            t.scale(-1 if self._flip_h else 1, -1 if self._flip_v else 1)
        out = image.transformed(t, Qt.TransformationMode.SmoothTransformation) \
            if (self._rotation or self._flip_h or self._flip_v) else image

        if self._zoom > 1.0:
            w, h = out.width(), out.height()
            cw, ch = int(w / self._zoom), int(h / self._zoom)
            x, y = (w - cw) // 2, (h - ch) // 2
            out = out.copy(x, y, cw, ch)
        return out

    # ---------------------------------------------------------- transforms

    def _toggle_flip_h(self):
        self._flip_h = not self._flip_h

    def _toggle_flip_v(self):
        self._flip_v = not self._flip_v

    def _rotate(self):
        self._rotation = (self._rotation + 90) % 360

    def _zoom_in(self):
        self._zoom = min(self._zoom + 0.25, 3.0)

    def _zoom_out(self):
        self._zoom = max(self._zoom - 0.25, 1.0)

    # ------------------------------------------------------------- snapshot

    def snapshot(self):
        """Return the current frame as a transformed QImage, or None."""
        if self._last_image is None:
            return None
        return self._transform_image(self._last_image)

    def _save_snapshot(self):
        img = self.snapshot()
        if img is None:
            self.status.setText("No frame to capture yet.")
            return
        from PySide6.QtCore import QStandardPaths
        default_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        ) or os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Snapshot",
            os.path.join(default_dir, "rovari_snapshot.png"),
            "PNG Image (*.png);;JPEG Image (*.jpg)"
        )
        if not path:
            return
        if img.save(path):
            self.status.setText(f"Saved {path}")
        else:
            self.status.setText("Could not save snapshot.")

    # ------------------------------------------------------------- pop-out

    def _popout_window(self):
        if not HAS_MULTIMEDIA or self._camera is None:
            self.status.setText("Start the camera before popping out.")
            return
        if self._popout is not None:
            self._popout.raise_()
            self._popout.activateWindow()
            return

        self._popout = QDialog(self)
        self._popout.setWindowTitle("Camera")
        self._popout.setMinimumSize(480, 360)
        lay = QVBoxLayout(self._popout)
        lay.setContentsMargins(0, 0, 0, 0)
        self._popout_view = _FrameView()
        lay.addWidget(self._popout_view)

        def _on_close(ev):
            self._popout_view = None
            self._popout = None
            ev.accept()

        self._popout.closeEvent = _on_close
        self._popout.show()

    def cleanup(self):
        """Stop the camera and close any pop-out (called on app close)."""
        if self._popout is not None:
            try:
                self._popout.close()
            except Exception:
                pass
        self._teardown_capture()
