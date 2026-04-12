from __future__ import annotations

import sys
import threading
from pathlib import Path

from timelapse_creator import __version__
from timelapse_creator.recorder import (
    AppConfig,
    CameraFeed,
    CaptureMode,
    OUTPUT_RESOLUTION_PRESETS,
    RecorderState,
    SessionInfo,
    SettingsStore,
    TimeLapseRecorder,
)
from timelapse_creator.theme import DEFAULT_THEME_NAME, mix_color, resolve_theme_colors

try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGraphicsDropShadowEffect,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ImportError as error:  # pragma: no cover - runtime guard
    raise RuntimeError("PySide6 is required for the Qt UI. Install it with: pip install -r requirements-qt.txt") from error


def format_duration(total_seconds: float) -> str:
    seconds = max(int(total_seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class RenderSignals(QObject):
    finished = Signal(object, object)


class TimeLapseQtWindow(QMainWindow):
    CAPTURE_MODE_LABELS: dict[str, CaptureMode] = {
        "Merged screens + camera": CaptureMode.MERGED_WITH_CAMERA,
        "Screens only": CaptureMode.SCREENS_ONLY,
        "Camera only": CaptureMode.CAMERA_ONLY,
    }

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Time Lapse Creator (Qt Preview) v{__version__}")
        self.resize(980, 760)
        self.setMinimumSize(860, 680)

        self.settings_store = SettingsStore()
        self.colors = resolve_theme_colors(DEFAULT_THEME_NAME, {})

        self.config = AppConfig(preview_size=200)
        self.camera_feed = CameraFeed()
        self.recorder = TimeLapseRecorder(self.config, self.camera_feed, self.settings_store)
        if self.recorder.get_state() == RecorderState.IDLE and self.recorder.get_timer_overlay_use_theme():
            try:
                self.recorder.set_timer_overlay_color(self.colors["accent"])
            except RuntimeError:
                pass
        self.camera_feed.start()

        self.rendering = False
        self._closing = False
        self.render_signals = RenderSignals()
        self.render_signals.finished.connect(self._on_render_complete)

        self._build_ui()
        self._apply_styles()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self._update_ui)
        self.refresh_timer.start()
        self._update_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        title = QLabel("Time Lapse Creator")
        title.setObjectName("title")
        subtitle = QLabel("Qt migration preview UI backed by the same recorder engine.")
        subtitle.setObjectName("subtitle")
        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        metrics_box = QFrame()
        metrics_layout = QGridLayout(metrics_box)
        metrics_layout.setContentsMargins(12, 12, 12, 12)
        metrics_layout.setHorizontalSpacing(12)
        metrics_layout.setVerticalSpacing(10)
        self.status_value = self._add_metric(metrics_layout, 0, 0, "Status", "Ready")
        self.elapsed_value = self._add_metric(metrics_layout, 0, 1, "Recording Time", "00:00:00")
        self.projected_value = self._add_metric(metrics_layout, 1, 0, "Video If Stopped", "00:00:00")
        self.frames_value = self._add_metric(metrics_layout, 1, 1, "Captured Frames", "0")
        main_layout.addWidget(metrics_box)

        controls_box = QFrame()
        controls_layout = QHBoxLayout(controls_box)
        controls_layout.setContentsMargins(12, 12, 12, 12)
        controls_layout.setSpacing(10)

        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("startButton")
        self.start_button.clicked.connect(self._start_or_resume)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setObjectName("neutralButton")
        self.pause_button.clicked.connect(self._pause)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.clicked.connect(self._stop)

        for button in (self.start_button, self.pause_button, self.stop_button):
            button.setMinimumHeight(40)
            self._apply_button_shadow(button)
            controls_layout.addWidget(button)
        main_layout.addWidget(controls_box)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(14)
        main_layout.addLayout(content_layout, stretch=1)

        options_box = QFrame()
        options_layout = QVBoxLayout(options_box)
        options_layout.setContentsMargins(12, 12, 12, 12)
        options_layout.setSpacing(12)
        options_title = QLabel("Options")
        options_title.setObjectName("sectionTitle")
        options_layout.addWidget(options_title)

        save_row = QHBoxLayout()
        save_row.setSpacing(8)
        self.save_folder_value = QLabel("")
        self.save_folder_value.setWordWrap(True)
        self.change_folder_button = QPushButton("Change Save Folder")
        self.change_folder_button.clicked.connect(self._choose_output_folder)
        self.change_folder_button.setObjectName("secondaryButton")
        self._apply_button_shadow(self.change_folder_button)
        save_row.addWidget(self.save_folder_value, stretch=1)
        save_row.addWidget(self.change_folder_button)
        options_layout.addLayout(save_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        self.capture_mode_box = QComboBox()
        self.capture_mode_box.addItems(tuple(self.CAPTURE_MODE_LABELS.keys()))
        self.capture_mode_box.currentTextChanged.connect(self._change_capture_mode)
        form.addRow("Capture mode", self.capture_mode_box)

        self.output_resolution_box = QComboBox()
        self.output_resolution_box.addItems(tuple(OUTPUT_RESOLUTION_PRESETS.keys()))
        self.output_resolution_box.currentTextChanged.connect(self._change_output_resolution)
        form.addRow("Output resolution", self.output_resolution_box)

        self.timer_overlay_enabled_check = QCheckBox("Show recording time on video")
        self.timer_overlay_enabled_check.stateChanged.connect(self._toggle_timer_overlay_enabled)
        form.addRow(self.timer_overlay_enabled_check)

        self.timer_overlay_theme_check = QCheckBox("Use theme accent color")
        self.timer_overlay_theme_check.stateChanged.connect(self._toggle_timer_overlay_use_theme)
        form.addRow(self.timer_overlay_theme_check)

        timer_row = QHBoxLayout()
        timer_row.setSpacing(8)
        self.timer_color_button = QPushButton("Timer Color")
        self.timer_color_button.setObjectName("secondaryButton")
        self.timer_color_button.clicked.connect(self._choose_timer_overlay_color)
        self._apply_button_shadow(self.timer_color_button)
        self.timer_size_box = QComboBox()
        self.timer_size_box.addItems(("280", "320", "360", "420", "480", "560", "640", "720", "840", "960", "1200"))
        self.timer_size_box.currentTextChanged.connect(self._change_timer_overlay_size)
        timer_row.addWidget(self.timer_color_button)
        timer_row.addWidget(QLabel("Width (px)"))
        timer_row.addWidget(self.timer_size_box)
        timer_host = QWidget()
        timer_host.setLayout(timer_row)
        form.addRow(timer_host)
        options_layout.addLayout(form)
        options_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(options_box, stretch=3)

        preview_box = QFrame()
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(10)
        preview_title = QLabel("Camera Preview")
        preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(preview_title)
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(self.config.preview_size + 20, self.config.preview_size + 20)
        self.preview_label.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.preview_label, alignment=Qt.AlignHCenter)
        preview_layout.addStretch(1)
        preview_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(preview_box, stretch=2)

    def _apply_styles(self) -> None:
        accent_pressed = mix_color(self.colors["accent"], self.colors["bg"], 0.32)
        neutral_bg = mix_color(self.colors["surface_alt"], self.colors["text"], 0.08)
        neutral_pressed = mix_color(neutral_bg, self.colors["bg"], 0.24)
        danger_pressed = mix_color(self.colors["danger"], self.colors["bg"], 0.3)
        secondary_pressed = mix_color(self.colors["surface_alt"], self.colors["text"], 0.12)

        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: {self.colors["bg"]};
                color: {self.colors["text"]};
                font-family: "SF Pro Text", "Segoe UI", sans-serif;
                font-size: 14px;
            }}
            QLabel#title {{
                font-size: 28px;
                font-weight: 700;
            }}
            QLabel#subtitle {{
                color: {self.colors["muted"]};
                font-size: 13px;
                margin-bottom: 6px;
            }}
            QFrame {{
                background: {self.colors["surface"]};
                border: 1px solid {self.colors["border"]};
                border-radius: 16px;
            }}
            QLabel#sectionTitle {{
                font-size: 16px;
                font-weight: 700;
            }}
            QPushButton {{
                border-radius: 12px;
                padding: 10px 16px;
                border: 1px solid {self.colors["border"]};
                background: {self.colors["surface_alt"]};
                font-weight: 600;
            }}
            QPushButton#startButton {{
                background: {self.colors["accent"]};
                border-color: {self.colors["accent"]};
            }}
            QPushButton#startButton:pressed {{
                background: {accent_pressed};
                border-color: {accent_pressed};
            }}
            QPushButton#neutralButton:pressed {{
                background: {neutral_pressed};
            }}
            QPushButton#dangerButton {{
                background: {self.colors["danger"]};
                border-color: {self.colors["danger"]};
            }}
            QPushButton#dangerButton:pressed {{
                background: {danger_pressed};
                border-color: {danger_pressed};
            }}
            QPushButton#secondaryButton:pressed {{
                background: {secondary_pressed};
            }}
            QPushButton:disabled {{
                color: {self.colors["muted"]};
                background: {mix_color(self.colors["surface_alt"], self.colors["bg"], 0.5)};
            }}
            QComboBox {{
                border-radius: 10px;
                border: 1px solid {self.colors["border"]};
                background: {self.colors["surface_alt"]};
                padding: 8px 10px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QCheckBox {{
                spacing: 8px;
                font-weight: 600;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {self.colors["border"]};
                border-radius: 5px;
                background: {self.colors["surface_alt"]};
            }}
            QCheckBox::indicator:checked {{
                background: {self.colors["accent"]};
                border-color: {self.colors["accent"]};
            }}
            """
        )

    def _apply_button_shadow(self, button: QPushButton) -> None:
        shadow = QGraphicsDropShadowEffect(button)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 120))
        button.setGraphicsEffect(shadow)

    def _add_metric(self, grid: QGridLayout, row: int, column: int, label: str, value: str) -> QLabel:
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        title = QLabel(label)
        title.setStyleSheet(f"color: {self.colors['muted']}; font-size: 12px; font-weight: 600;")
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(value_label)
        grid.addWidget(card, row, column)
        return value_label

    def _sync_capture_mode_ui(self) -> None:
        mode = self.recorder.get_capture_mode()
        for label, mode_value in self.CAPTURE_MODE_LABELS.items():
            if mode_value == mode:
                self._set_combo_value(self.capture_mode_box, label)
                return

    def _sync_output_resolution_ui(self) -> None:
        self._set_combo_value(self.output_resolution_box, self.recorder.get_output_resolution())

    def _sync_timer_overlay_ui(self) -> None:
        self._set_checkbox_value(self.timer_overlay_enabled_check, self.recorder.get_timer_overlay_enabled())
        self._set_checkbox_value(self.timer_overlay_theme_check, self.recorder.get_timer_overlay_use_theme())
        self._set_combo_value(self.timer_size_box, str(self.recorder.get_timer_overlay_size_px()))
        color = self.recorder.get_timer_overlay_color()
        self.timer_color_button.setText(f"Timer Color ({color})")
        self.timer_color_button.setEnabled(not self.recorder.get_timer_overlay_use_theme())
        self.timer_size_box.setEnabled(self.recorder.get_timer_overlay_enabled())

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        combo.blockSignals(True)
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _set_checkbox_value(self, checkbox: QCheckBox, checked: bool) -> None:
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.change_folder_button.setEnabled(enabled)
        self.capture_mode_box.setEnabled(enabled)
        self.output_resolution_box.setEnabled(enabled)
        self.timer_overlay_enabled_check.setEnabled(enabled)
        self.timer_overlay_theme_check.setEnabled(enabled)
        self.timer_color_button.setEnabled(enabled and not self.recorder.get_timer_overlay_use_theme())
        self.timer_size_box.setEnabled(enabled and self.recorder.get_timer_overlay_enabled())

    def _start_or_resume(self) -> None:
        if self.rendering:
            return
        self.recorder.start_or_resume()
        self._update_ui()

    def _pause(self) -> None:
        if self.rendering:
            return
        self.recorder.pause()
        self._update_ui()

    def _stop(self) -> None:
        if self.rendering:
            return
        if self.recorder.get_state() == RecorderState.IDLE:
            return

        try:
            session = self.recorder.stop()
        except RuntimeError as error:
            QMessageBox.critical(self, "Stop failed", str(error))
            return

        self.rendering = True
        self.status_value.setText("Rendering video…")
        self._update_ui()
        thread = threading.Thread(target=self._render_session, args=(session,), daemon=True)
        thread.start()

    def _render_session(self, session: SessionInfo) -> None:
        try:
            rendered = self.recorder.render_video(session)
            self.render_signals.finished.emit(rendered, None)
        except Exception as error:  # noqa: BLE001
            self.render_signals.finished.emit(None, error)

    def _on_render_complete(self, session: SessionInfo | None, error: Exception | None) -> None:
        self.rendering = False
        if error is not None:
            QMessageBox.critical(self, "Render failed", str(error))
            self._update_ui()
            return

        assert session is not None
        video_length = format_duration(session.frame_count / self.config.fps)
        QMessageBox.information(
            self,
            "Timelapse ready",
            (
                f"Video saved to:\n{session.video_path}\n\n"
                f"Recording time: {format_duration(session.elapsed_seconds)}\n"
                f"Video length: {video_length}\n"
                f"Frames: {session.frame_count}"
            ),
        )
        self._update_ui()

    def _choose_output_folder(self) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            QMessageBox.information(self, "Recording active", "Stop recording before changing the save folder.")
            return

        selected = QFileDialog.getExistingDirectory(self, "Choose where to save frames and videos")
        if not selected:
            return

        try:
            self.recorder.set_recordings_dir(Path(selected))
        except RuntimeError as error:
            QMessageBox.critical(self, "Save folder unchanged", str(error))
            return
        self._update_ui()

    def _change_capture_mode(self, label: str) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            self._sync_capture_mode_ui()
            QMessageBox.information(self, "Recording active", "Stop recording before changing capture mode.")
            return
        mode = self.CAPTURE_MODE_LABELS.get(label, CaptureMode.MERGED_WITH_CAMERA)
        try:
            self.recorder.set_capture_mode(mode)
        except RuntimeError as error:
            QMessageBox.critical(self, "Capture mode unchanged", str(error))
        self._sync_capture_mode_ui()

    def _change_output_resolution(self, label: str) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            self._sync_output_resolution_ui()
            QMessageBox.information(self, "Recording active", "Stop recording before changing output resolution.")
            return
        try:
            self.recorder.set_output_resolution(label)
        except RuntimeError as error:
            QMessageBox.critical(self, "Output resolution unchanged", str(error))
        self._sync_output_resolution_ui()

    def _toggle_timer_overlay_enabled(self, _state: int) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            self._sync_timer_overlay_ui()
            QMessageBox.information(self, "Recording active", "Stop recording before changing timer overlay.")
            return
        try:
            self.recorder.set_timer_overlay_enabled(self.timer_overlay_enabled_check.isChecked())
        except RuntimeError as error:
            QMessageBox.critical(self, "Timer overlay unchanged", str(error))
        self._sync_timer_overlay_ui()

    def _toggle_timer_overlay_use_theme(self, _state: int) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            self._sync_timer_overlay_ui()
            QMessageBox.information(self, "Recording active", "Stop recording before changing timer overlay.")
            return
        use_theme = self.timer_overlay_theme_check.isChecked()
        try:
            self.recorder.set_timer_overlay_use_theme(use_theme)
            if use_theme:
                self.recorder.set_timer_overlay_color(self.colors["accent"])
        except RuntimeError as error:
            QMessageBox.critical(self, "Timer overlay unchanged", str(error))
        self._sync_timer_overlay_ui()

    def _choose_timer_overlay_color(self) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            QMessageBox.information(self, "Recording active", "Stop recording before changing timer overlay color.")
            return

        color = QColorDialog.getColor(QColor(self.recorder.get_timer_overlay_color()), self, "Choose timer color")
        if not color.isValid():
            return
        selected = color.name().lower()
        try:
            self.recorder.set_timer_overlay_use_theme(False)
            self.recorder.set_timer_overlay_color(selected)
        except RuntimeError as error:
            QMessageBox.critical(self, "Timer overlay unchanged", str(error))
        self._sync_timer_overlay_ui()

    def _change_timer_overlay_size(self, value: str) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            self._sync_timer_overlay_ui()
            QMessageBox.information(self, "Recording active", "Stop recording before changing timer overlay size.")
            return
        try:
            self.recorder.set_timer_overlay_size_px(int(value))
        except (RuntimeError, ValueError) as error:
            QMessageBox.critical(self, "Timer overlay unchanged", str(error))
        self._sync_timer_overlay_ui()

    def _refresh_preview(self) -> None:
        preview_size = self.config.preview_size
        frame = self.camera_feed.get_latest_frame()
        if frame is None:
            pixmap = QPixmap(preview_size, preview_size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(40, 40, 40))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(2, 2, preview_size - 4, preview_size - 4)
            painter.setPen(QColor(220, 220, 220))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "No cam")
            painter.end()
        else:
            height, width, _ = frame.shape
            image = QImage(frame.data, width, height, frame.strides[0], QImage.Format_RGB888).copy()
            scaled = QPixmap.fromImage(image).scaled(
                preview_size,
                preview_size,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = max(0, (scaled.width() - preview_size) // 2)
            y = max(0, (scaled.height() - preview_size) // 2)
            cropped = scaled.copy(x, y, preview_size, preview_size)

            pixmap = QPixmap(preview_size, preview_size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            clip = QPainterPath()
            clip.addEllipse(0, 0, preview_size, preview_size)
            painter.setClipPath(clip)
            painter.drawPixmap(0, 0, cropped)
            painter.end()

        ring = QPixmap(preview_size + 20, preview_size + 20)
        ring.fill(Qt.transparent)
        painter = QPainter(ring)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(6, 10, preview_size + 8, preview_size + 8)
        painter.drawPixmap(10, 0, pixmap)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor(self.colors["accent"]))
        painter.drawEllipse(10, 0, preview_size, preview_size)
        painter.end()
        self.preview_label.setPixmap(ring)

    def _update_ui(self) -> None:
        if self._closing:
            return

        state = self.recorder.get_state()
        elapsed = self.recorder.get_elapsed_seconds()
        projected = self.recorder.get_estimated_video_seconds()
        frames = self.recorder.get_frame_count()

        if self.rendering:
            status = "Rendering video…"
        elif state == RecorderState.RECORDING:
            status = "Recording"
        elif state == RecorderState.PAUSED:
            status = "Paused"
        else:
            status = "Ready"

        self.status_value.setText(status)
        self.elapsed_value.setText(format_duration(elapsed))
        self.projected_value.setText(format_duration(projected))
        self.frames_value.setText(str(frames))
        self.save_folder_value.setText(str(self.recorder.get_recordings_dir()))

        self._sync_capture_mode_ui()
        self._sync_output_resolution_ui()
        self._sync_timer_overlay_ui()
        self._refresh_preview()

        if self.rendering:
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self._set_controls_enabled(False)
        elif state == RecorderState.IDLE:
            self.start_button.setText("Start")
            self.start_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self._set_controls_enabled(True)
        elif state == RecorderState.RECORDING:
            self.start_button.setText("Resume")
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self._set_controls_enabled(False)
        else:
            self.start_button.setText("Resume")
            self.start_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self._set_controls_enabled(False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._closing = True
        self.refresh_timer.stop()
        if self.recorder.get_state() != RecorderState.IDLE and not self.rendering:
            should_stop = QMessageBox.question(
                self,
                "Stop recording?",
                "A recording is active. Stop it and close the app?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if should_stop != QMessageBox.Yes:
                self._closing = False
                self.refresh_timer.start()
                event.ignore()
                return
            try:
                session = self.recorder.stop()
            except RuntimeError:
                session = None
            if session is not None:
                try:
                    self.recorder.render_video(session)
                except Exception:
                    pass

        self.camera_feed.stop()
        event.accept()


def main() -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)

    window = TimeLapseQtWindow()
    window.show()

    if owns_app:
        return app.exec()
    return 0
