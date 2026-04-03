from __future__ import annotations

import json
import platform
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

import cv2
import mss
import numpy as np
from PIL import Image, ImageDraw


class RecorderState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"


class CaptureMode(str, Enum):
    MERGED_WITH_CAMERA = "merged_with_camera"
    CAMERA_ONLY = "camera_only"


def default_recordings_dir() -> Path:
    downloads_dir = Path.home() / "Downloads"
    base_dir = downloads_dir if downloads_dir.exists() else Path.home()
    return base_dir / "Time Lapse Creator"


def settings_file_path() -> Path:
    settings_dir = Path.home() / ".time-lapse-creator"
    settings_dir.mkdir(parents=True, exist_ok=True)
    return settings_dir / "settings.json"


@dataclass(slots=True)
class AppConfig:
    output_width: int = 1920
    output_height: int = 1080
    fps: int = 30
    timelapse_speedup: int = 60
    webcam_diameter: int = 180
    webcam_margin: int = 24
    preview_size: int = 110
    recordings_dir: Path = field(default_factory=default_recordings_dir)
    capture_mode: CaptureMode = CaptureMode.MERGED_WITH_CAMERA

    @property
    def capture_interval_seconds(self) -> float:
        return self.timelapse_speedup / self.fps

    @property
    def output_size(self) -> tuple[int, int]:
        return self.output_width, self.output_height


@dataclass(slots=True)
class SessionInfo:
    session_dir: Path
    frames_dir: Path
    video_path: Path
    started_at: datetime
    ended_at: datetime
    elapsed_seconds: float
    frame_count: int


class SettingsStore:
    def __init__(self, settings_path: Path | None = None) -> None:
        self.settings_path = settings_path or settings_file_path()

    def load(self) -> dict[str, str]:
        if not self.settings_path.exists():
            return {}

        try:
            with self.settings_path.open("r", encoding="utf-8") as settings_file:
                data = json.load(settings_file)
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict):
            return {}

        settings: dict[str, str] = {}
        for key, value in data.items():
            if isinstance(value, str):
                settings[key] = value
        return settings

    def save(self, settings: dict[str, str]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        with self.settings_path.open("w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, indent=2)

    def update(self, updates: dict[str, str]) -> None:
        settings = self.load()
        settings.update(updates)
        self.save(settings)


class CameraFeed:
    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self._latest_frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._available = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="camera-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def is_available(self) -> bool:
        return self._available

    def get_latest_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def _open_capture(self) -> cv2.VideoCapture:
        if platform.system() == "Windows":
            return cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        return cv2.VideoCapture(self.camera_index)

    def _run(self) -> None:
        capture: cv2.VideoCapture | None = None
        while not self._stop_event.is_set():
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                capture = self._open_capture()
                if not capture.isOpened():
                    self._available = False
                    time.sleep(2)
                    continue

            ok, frame = capture.read()
            if not ok:
                self._available = False
                capture.release()
                capture = None
                time.sleep(1)
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            with self._lock:
                self._latest_frame = rgb_frame
            self._available = True
            time.sleep(1 / 15)

        if capture is not None and capture.isOpened():
            capture.release()


class TimeLapseRecorder:
    def __init__(self, config: AppConfig, camera_feed: CameraFeed, settings_store: SettingsStore | None = None) -> None:
        self.config = config
        self.camera_feed = camera_feed
        self.settings_store = settings_store or SettingsStore()
        self._load_settings()
        self.recordings_dir = self.config.recordings_dir
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._capture_stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._state = RecorderState.IDLE
        self._started_at: datetime | None = None
        self._session_dir: Path | None = None
        self._frames_dir: Path | None = None
        self._video_path: Path | None = None
        self._frame_count = 0
        self._accumulated_seconds = 0.0
        self._active_segment_started_monotonic: float | None = None

    def _load_settings(self) -> None:
        settings = self.settings_store.load()

        saved_recordings_dir = settings.get("recordings_dir")
        if saved_recordings_dir:
            self.config.recordings_dir = Path(saved_recordings_dir).expanduser()

        saved_capture_mode = settings.get("capture_mode")
        if saved_capture_mode:
            try:
                self.config.capture_mode = CaptureMode(saved_capture_mode)
            except ValueError:
                self.config.capture_mode = CaptureMode.MERGED_WITH_CAMERA

    def _save_settings(self) -> None:
        self.settings_store.update(
            {
                "recordings_dir": str(self.config.recordings_dir),
                "capture_mode": self.config.capture_mode.value,
            }
        )

    def get_recordings_dir(self) -> Path:
        with self._lock:
            return self.recordings_dir

    def set_recordings_dir(self, recordings_dir: Path) -> Path:
        target_dir = recordings_dir.expanduser().resolve()
        with self._lock:
            if self._state != RecorderState.IDLE:
                raise RuntimeError("Save location can only be changed while recording is stopped.")
            target_dir.mkdir(parents=True, exist_ok=True)
            self.recordings_dir = target_dir
            self.config.recordings_dir = target_dir
            self._save_settings()
            return target_dir

    def get_capture_mode(self) -> CaptureMode:
        with self._lock:
            return self.config.capture_mode

    def set_capture_mode(self, capture_mode: CaptureMode) -> CaptureMode:
        with self._lock:
            if self._state != RecorderState.IDLE:
                raise RuntimeError("Capture mode can only be changed while recording is stopped.")
            self.config.capture_mode = capture_mode
            self._save_settings()
            return self.config.capture_mode

    def get_state(self) -> RecorderState:
        with self._lock:
            return self._state

    def get_elapsed_seconds(self) -> float:
        with self._lock:
            elapsed = self._accumulated_seconds
            if self._state == RecorderState.RECORDING and self._active_segment_started_monotonic is not None:
                elapsed += time.monotonic() - self._active_segment_started_monotonic
            return max(elapsed, 0.0)

    def get_estimated_video_seconds(self) -> float:
        return self.get_elapsed_seconds() / self.config.timelapse_speedup

    def get_frame_count(self) -> int:
        with self._lock:
            return self._frame_count

    def start_or_resume(self) -> None:
        with self._lock:
            if self._state == RecorderState.RECORDING:
                return

            if self._state == RecorderState.IDLE:
                self._start_new_session_locked()
            else:
                self._active_segment_started_monotonic = time.monotonic()
                self._state = RecorderState.RECORDING

    def pause(self) -> None:
        with self._lock:
            if self._state != RecorderState.RECORDING:
                return
            self._accumulate_active_time_locked()
            self._state = RecorderState.PAUSED

    def stop(self) -> SessionInfo:
        with self._lock:
            if self._state == RecorderState.IDLE:
                raise RuntimeError("There is no active recording session.")
            self._accumulate_active_time_locked()
            self._state = RecorderState.IDLE
            self._capture_stop_event.set()
            capture_thread = self._capture_thread

        if capture_thread and capture_thread.is_alive():
            capture_thread.join(timeout=5)

        with self._lock:
            if self._session_dir is None or self._frames_dir is None or self._video_path is None or self._started_at is None:
                raise RuntimeError("Session data was not initialized.")
            session = SessionInfo(
                session_dir=self._session_dir,
                frames_dir=self._frames_dir,
                video_path=self._video_path,
                started_at=self._started_at,
                ended_at=datetime.now(),
                elapsed_seconds=self._accumulated_seconds,
                frame_count=self._frame_count,
            )
            self._reset_session_locked()
            return session

    def render_video(self, session: SessionInfo) -> SessionInfo:
        frame_paths = sorted(session.frames_dir.glob("frame_*.jpg"))
        if not frame_paths:
            raise RuntimeError("No frames were captured, so no video could be created.")

        video_path, writer = self._create_video_writer(session.video_path)
        render_succeeded = False
        try:
            for frame_path in frame_paths:
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    continue
                writer.write(frame)
            render_succeeded = True
        finally:
            writer.release()

        if render_succeeded:
            self._delete_session_frames(session.frames_dir)

        return SessionInfo(
            session_dir=session.session_dir,
            frames_dir=session.frames_dir,
            video_path=video_path,
            started_at=session.started_at,
            ended_at=session.ended_at,
            elapsed_seconds=session.elapsed_seconds,
            frame_count=len(frame_paths),
        )

    def _delete_session_frames(self, frames_dir: Path) -> None:
        if not frames_dir.exists():
            return
        shutil.rmtree(frames_dir, ignore_errors=True)

    def _start_new_session_locked(self) -> None:
        timestamp = datetime.now()
        session_name = timestamp.strftime("session-%Y%m%d-%H%M%S")
        session_dir = self.recordings_dir / session_name
        frames_dir = session_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        self._session_dir = session_dir
        self._frames_dir = frames_dir
        self._video_path = session_dir / "timelapse.mp4"
        self._started_at = timestamp
        self._frame_count = 0
        self._accumulated_seconds = 0.0
        self._active_segment_started_monotonic = time.monotonic()
        self._state = RecorderState.RECORDING
        self._capture_stop_event.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, name="screen-capture", daemon=True)
        self._capture_thread.start()

    def _reset_session_locked(self) -> None:
        self._session_dir = None
        self._frames_dir = None
        self._video_path = None
        self._started_at = None
        self._frame_count = 0
        self._accumulated_seconds = 0.0
        self._active_segment_started_monotonic = None
        self._capture_thread = None
        self._capture_stop_event.clear()

    def _accumulate_active_time_locked(self) -> None:
        if self._active_segment_started_monotonic is not None:
            self._accumulated_seconds += time.monotonic() - self._active_segment_started_monotonic
            self._active_segment_started_monotonic = None

    def _capture_loop(self) -> None:
        next_capture_at = time.monotonic()
        with mss.mss() as screen_capture:
            while not self._capture_stop_event.is_set():
                with self._lock:
                    state = self._state
                    frames_dir = self._frames_dir
                    frame_number = self._frame_count + 1

                if state != RecorderState.RECORDING:
                    next_capture_at = time.monotonic() + self.config.capture_interval_seconds
                    time.sleep(0.2)
                    continue

                now = time.monotonic()
                if now < next_capture_at:
                    time.sleep(min(0.2, next_capture_at - now))
                    continue

                if frames_dir is None:
                    time.sleep(0.2)
                    continue

                try:
                    frame_image = self._build_frame(screen_capture)
                    frame_path = frames_dir / f"frame_{frame_number:06d}.jpg"
                    frame_image.save(frame_path, format="JPEG", quality=92)
                except Exception:
                    next_capture_at = time.monotonic() + self.config.capture_interval_seconds
                    time.sleep(0.2)
                    continue

                with self._lock:
                    self._frame_count = frame_number

                next_capture_at = time.monotonic() + self.config.capture_interval_seconds

    def _build_frame(self, screen_capture: mss.mss) -> Image.Image:
        if self.config.capture_mode == CaptureMode.CAMERA_ONLY:
            return self._build_camera_only_frame()

        monitors = screen_capture.monitors[1:] or [screen_capture.monitors[0]]
        left = min(monitor["left"] for monitor in monitors)
        top = min(monitor["top"] for monitor in monitors)
        right = max(monitor["left"] + monitor["width"] for monitor in monitors)
        bottom = max(monitor["top"] + monitor["height"] for monitor in monitors)
        virtual_width = right - left
        virtual_height = bottom - top

        desktop = Image.new("RGB", (virtual_width, virtual_height), (12, 12, 12))
        for monitor in monitors:
            screenshot = screen_capture.grab(monitor)
            image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            x_pos = monitor["left"] - left
            y_pos = monitor["top"] - top
            desktop.paste(image, (x_pos, y_pos))

        fitted = self._fit_to_output(desktop)
        webcam_frame = self.camera_feed.get_latest_frame()
        if webcam_frame is not None:
            fitted = self._overlay_webcam(fitted, webcam_frame, self.config.webcam_diameter)
        return fitted

    def _build_camera_only_frame(self) -> Image.Image:
        webcam_frame = self.camera_feed.get_latest_frame()
        if webcam_frame is None:
            return self._build_placeholder_frame("Camera not available")

        webcam_image = Image.fromarray(webcam_frame)
        return self._fit_to_output(webcam_image)

    def _build_placeholder_frame(self, message: str) -> Image.Image:
        base_image = Image.new("RGB", self.config.output_size, (24, 24, 24))
        draw = ImageDraw.Draw(base_image)
        box_width = max(320, len(message) * 10)
        box_height = 80
        left = (base_image.width - box_width) // 2
        top = (base_image.height - box_height) // 2
        right = left + box_width
        bottom = top + box_height
        draw.rounded_rectangle((left, top, right, bottom), radius=18, fill=(40, 40, 40))
        draw.text((left + 24, top + 28), message, fill=(230, 230, 230))
        return base_image

    def _fit_to_output(self, image: Image.Image) -> Image.Image:
        target_width, target_height = self.config.output_size
        background = Image.new("RGB", (target_width, target_height), (18, 18, 18))
        scale = min(target_width / image.width, target_height / image.height)
        resized_size = (
            max(1, int(image.width * scale)),
            max(1, int(image.height * scale)),
        )
        resized = image.resize(resized_size, Image.Resampling.LANCZOS)
        offset = ((target_width - resized.width) // 2, (target_height - resized.height) // 2)
        background.paste(resized, offset)
        return background

    def _overlay_webcam(self, base_image: Image.Image, webcam_frame: np.ndarray, diameter: int) -> Image.Image:
        webcam_image = Image.fromarray(webcam_frame)
        crop_size = min(webcam_image.width, webcam_image.height)
        left = (webcam_image.width - crop_size) // 2
        top = (webcam_image.height - crop_size) // 2
        webcam_image = webcam_image.crop((left, top, left + crop_size, top + crop_size))
        webcam_image = webcam_image.resize((diameter, diameter), Image.Resampling.LANCZOS)

        mask = Image.new("L", (diameter, diameter), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=255)

        shadow = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        x_pos = base_image.width - diameter - self.config.webcam_margin
        y_pos = base_image.height - diameter - self.config.webcam_margin
        shadow_draw.ellipse((x_pos - 6, y_pos - 2, x_pos + diameter + 6, y_pos + diameter + 10), fill=(0, 0, 0, 90))

        composed = Image.alpha_composite(base_image.convert("RGBA"), shadow)
        composed.paste(webcam_image, (x_pos, y_pos), mask)

        border = ImageDraw.Draw(composed)
        border.ellipse((x_pos, y_pos, x_pos + diameter - 1, y_pos + diameter - 1), outline=(255, 255, 255, 220), width=4)
        return composed.convert("RGB")

    def _create_video_writer(self, preferred_path: Path) -> tuple[Path, cv2.VideoWriter]:
        codec_candidates = [
            (preferred_path.with_suffix(".mp4"), "mp4v"),
            (preferred_path.with_suffix(".mp4"), "avc1"),
            (preferred_path.with_suffix(".avi"), "XVID"),
            (preferred_path.with_suffix(".avi"), "MJPG"),
        ]

        for path, codec in codec_candidates:
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(str(path), fourcc, self.config.fps, self.config.output_size)
            if writer.isOpened():
                return path, writer
            writer.release()

        raise RuntimeError("OpenCV could not open a video writer on this machine.")
