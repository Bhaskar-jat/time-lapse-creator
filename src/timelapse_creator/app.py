from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from timelapse_creator.recorder import (
    AppConfig,
    CameraFeed,
    CaptureMode,
    RecorderState,
    SessionInfo,
    TimeLapseRecorder,
)


def format_duration(total_seconds: float) -> str:
    seconds = max(int(total_seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class TimeLapseApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Time Lapse Creator")
        self.root.geometry("460x340")
        self.root.minsize(440, 320)

        self.config = AppConfig()
        self.camera_feed = CameraFeed()
        self.recorder = TimeLapseRecorder(self.config, self.camera_feed)
        self.camera_feed.start()

        self.closing = False
        self.rendering = False
        self._preview_image: ImageTk.PhotoImage | None = None
        self._build_ui()
        self._update_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)

        title = ttk.Label(main, text="Cross-platform Time Lapse Recorder", font=("TkDefaultFont", 13, "bold"))
        title.grid(row=0, column=0, sticky="w")

        self.status_var = tk.StringVar(value="Ready")
        self.elapsed_var = tk.StringVar(value="Recording time: 00:00:00")
        self.projected_var = tk.StringVar(value="If stopped now: [00:00:00]")
        self.frames_var = tk.StringVar(value="Captured frames: 0")
        self.output_var = tk.StringVar(value=f"Save folder: {self.recorder.get_recordings_dir()}")
        self.capture_mode_var = tk.StringVar()

        info_frame = ttk.Frame(main, padding=(0, 14, 0, 14))
        info_frame.grid(row=1, column=0, sticky="ew")
        info_frame.columnconfigure(0, weight=1)

        ttk.Label(info_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, textvariable=self.elapsed_var).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, textvariable=self.projected_var).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, textvariable=self.frames_var).grid(row=3, column=0, sticky="w", pady=2)
        ttk.Label(info_frame, textvariable=self.output_var, wraplength=410).grid(row=4, column=0, sticky="w", pady=2)

        controls = ttk.Frame(main)
        controls.grid(row=2, column=0, sticky="ew")
        controls.columnconfigure((0, 1, 2), weight=1)

        self.start_button = ttk.Button(controls, text="Start", command=self._start_or_resume)
        self.pause_button = ttk.Button(controls, text="Pause", command=self._pause)
        self.stop_button = ttk.Button(controls, text="Stop", command=self._stop)
        self.change_folder_button = ttk.Button(main, text="Change Save Folder", command=self._choose_output_folder)
        self.capture_mode_box = ttk.Combobox(
            main,
            state="readonly",
            textvariable=self.capture_mode_var,
            values=("Merged screens + camera", "Camera only"),
        )
        self.capture_mode_box.bind("<<ComboboxSelected>>", self._change_capture_mode)

        self.start_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.pause_button.grid(row=0, column=1, padx=4, sticky="ew")
        self.stop_button.grid(row=0, column=2, padx=(8, 0), sticky="ew")
        self.change_folder_button.grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Label(main, text="Capture mode").grid(row=4, column=0, sticky="w", pady=(10, 2))
        self.capture_mode_box.grid(row=5, column=0, sticky="ew")

        preview_row = ttk.Frame(main)
        preview_row.grid(row=6, column=0, sticky="nsew", pady=(18, 0))
        preview_row.columnconfigure(0, weight=1)

        helper = ttk.Label(
            preview_row,
            text=(
                "Choose between desktop capture with camera overlay or camera-only recording. The last selection is saved."
            ),
            wraplength=295,
            justify=tk.LEFT,
        )
        helper.grid(row=0, column=0, sticky="nw")

        self.preview_label = ttk.Label(preview_row)
        self.preview_label.grid(row=0, column=1, sticky="se", padx=(16, 0))
        self._sync_capture_mode_ui()

    def _start_or_resume(self) -> None:
        if self.rendering:
            return
        self.recorder.start_or_resume()

    def _pause(self) -> None:
        if self.rendering:
            return
        self.recorder.pause()

    def _stop(self) -> None:
        if self.rendering:
            return
        if self.recorder.get_state() == RecorderState.IDLE:
            return

        try:
            session = self.recorder.stop()
        except RuntimeError as error:
            messagebox.showerror("Stop failed", str(error))
            return

        self.rendering = True
        self.status_var.set("Rendering video...")
        render_thread = threading.Thread(target=self._render_session, args=(session,), daemon=True)
        render_thread.start()

    def _choose_output_folder(self) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            messagebox.showinfo("Recording active", "Stop the current recording before changing the save folder.")
            return

        selected_dir = filedialog.askdirectory(
            parent=self.root,
            initialdir=str(self.recorder.get_recordings_dir()),
            mustexist=False,
            title="Choose where to save frames and videos",
        )
        if not selected_dir:
            return

        try:
            target_dir = self.recorder.set_recordings_dir(Path(selected_dir))
        except RuntimeError as error:
            messagebox.showerror("Save folder unchanged", str(error))
            return

        self.output_var.set(f"Save folder: {target_dir}")

    def _change_capture_mode(self, _event: object | None = None) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            self._sync_capture_mode_ui()
            messagebox.showinfo("Recording active", "Stop the current recording before changing the capture mode.")
            return

        try:
            capture_mode = self._capture_mode_from_label(self.capture_mode_var.get())
            self.recorder.set_capture_mode(capture_mode)
        except RuntimeError as error:
            self._sync_capture_mode_ui()
            messagebox.showerror("Capture mode unchanged", str(error))
            return

        self._sync_capture_mode_ui()

    def _render_session(self, session: SessionInfo) -> None:
        try:
            rendered_session = self.recorder.render_video(session)
            if not self.closing:
                self.root.after(0, lambda: self._on_render_complete(rendered_session, None))
        except Exception as error:  # noqa: BLE001
            if not self.closing:
                self.root.after(0, lambda: self._on_render_complete(None, error))

    def _on_render_complete(self, session: SessionInfo | None, error: Exception | None) -> None:
        self.rendering = False
        if error is not None:
            self.status_var.set("Render failed")
            messagebox.showerror("Render failed", str(error))
            return

        assert session is not None
        self.status_var.set(f"Saved: {session.video_path.name}")
        self.output_var.set(f"Save folder: {self.recorder.get_recordings_dir()}")
        video_length = format_duration(session.frame_count / self.config.fps)
        messagebox.showinfo(
            "Timelapse ready",
            (
                f"Video saved to:\n{session.video_path}\n\n"
                f"Recording time: {format_duration(session.elapsed_seconds)}\n"
                f"Video length: {video_length}\n"
                f"Frames: {session.frame_count}"
            ),
        )

    def _update_ui(self) -> None:
        if self.closing:
            return

        state = self.recorder.get_state()
        elapsed_seconds = self.recorder.get_elapsed_seconds()
        projected_seconds = self.recorder.get_estimated_video_seconds()
        frame_count = self.recorder.get_frame_count()

        self.elapsed_var.set(f"Recording time: {format_duration(elapsed_seconds)}")
        self.projected_var.set(f"If stopped now: [{format_duration(projected_seconds)}]")
        self.frames_var.set(f"Captured frames: {frame_count}")
        self._sync_capture_mode_ui()

        if self.rendering:
            self.start_button.state(["disabled"])
            self.pause_button.state(["disabled"])
            self.stop_button.state(["disabled"])
            self.change_folder_button.state(["disabled"])
            self.capture_mode_box.state(["disabled"])
        elif state == RecorderState.IDLE:
            self.status_var.set("Ready")
            self.start_button.config(text="Start")
            self.start_button.state(["!disabled"])
            self.pause_button.state(["disabled"])
            self.stop_button.state(["disabled"])
            self.change_folder_button.state(["!disabled"])
            self.capture_mode_box.state(["!disabled", "readonly"])
        elif state == RecorderState.RECORDING:
            self.status_var.set("Recording")
            self.start_button.config(text="Resume")
            self.start_button.state(["disabled"])
            self.pause_button.state(["!disabled"])
            self.stop_button.state(["!disabled"])
            self.change_folder_button.state(["disabled"])
            self.capture_mode_box.state(["disabled"])
        elif state == RecorderState.PAUSED:
            self.status_var.set("Paused")
            self.start_button.config(text="Resume")
            self.start_button.state(["!disabled"])
            self.pause_button.state(["disabled"])
            self.stop_button.state(["!disabled"])
            self.change_folder_button.state(["disabled"])
            self.capture_mode_box.state(["disabled"])

        self._refresh_camera_preview()
        self.root.after(250, self._update_ui)

    def _refresh_camera_preview(self) -> None:
        latest_frame = self.camera_feed.get_latest_frame()
        if latest_frame is None:
            preview = Image.new("RGBA", (self.config.preview_size, self.config.preview_size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(preview)
            draw.ellipse((1, 1, self.config.preview_size - 2, self.config.preview_size - 2), fill=(45, 45, 45, 255))
            draw.text((26, 44), "No cam", fill=(220, 220, 220, 255))
        else:
            preview = Image.fromarray(latest_frame)
            crop = min(preview.width, preview.height)
            left = (preview.width - crop) // 2
            top = (preview.height - crop) // 2
            preview = preview.crop((left, top, left + crop, top + crop))
            preview = preview.resize((self.config.preview_size, self.config.preview_size), Image.Resampling.LANCZOS).convert("RGBA")
            mask = Image.new("L", preview.size, 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, preview.width - 1, preview.height - 1), fill=255)
            preview.putalpha(mask)

        self._preview_image = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self._preview_image)

    def _sync_capture_mode_ui(self) -> None:
        self.capture_mode_var.set(self._capture_mode_label(self.recorder.get_capture_mode()))

    def _capture_mode_label(self, capture_mode: CaptureMode) -> str:
        if capture_mode == CaptureMode.CAMERA_ONLY:
            return "Camera only"
        return "Merged screens + camera"

    def _capture_mode_from_label(self, label: str) -> CaptureMode:
        if label == "Camera only":
            return CaptureMode.CAMERA_ONLY
        return CaptureMode.MERGED_WITH_CAMERA

    def _on_close(self) -> None:
        self.closing = True
        if self.recorder.get_state() != RecorderState.IDLE and not self.rendering:
            should_stop = messagebox.askyesno(
                "Stop recording?",
                "A recording is active. Stop it and close the app?",
            )
            if not should_stop:
                self.closing = False
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
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    TimeLapseApp(root)
    root.mainloop()
    return 0
