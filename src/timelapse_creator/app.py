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
        self.root.geometry("780x620")
        self.root.minsize(720, 560)
        self.colors = {
            "bg": "#070b16",
            "surface": "#111827",
            "surface_alt": "#0f172a",
            "border": "#263043",
            "text": "#f8fafc",
            "muted": "#94a3b8",
            "accent": "#8b5cf6",
            "accent_2": "#06b6d4",
            "success": "#22c55e",
            "warning": "#f59e0b",
            "danger": "#f97316",
        }

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
        self.root.configure(bg=self.colors["bg"])
        self._configure_styles()
        self.status_var = tk.StringVar(value="Ready")
        self.elapsed_var = tk.StringVar(value="Recording time: 00:00:00")
        self.projected_var = tk.StringVar(value="If stopped now: [00:00:00]")
        self.frames_var = tk.StringVar(value="Captured frames: 0")
        self.output_var = tk.StringVar(value=f"Save folder: {self.recorder.get_recordings_dir()}")
        self.capture_mode_var = tk.StringVar()
        main = tk.Frame(self.root, bg=self.colors["bg"], padx=24, pady=24)
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(3, weight=1)

        self.hero_canvas = tk.Canvas(main, height=150, highlightthickness=0, bd=0, bg=self.colors["bg"])
        self.hero_canvas.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.hero_canvas.bind("<Configure>", self._draw_header_gradient)

        metrics = tk.Frame(main, bg=self.colors["bg"])
        metrics.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(18, 18))
        metrics.grid_columnconfigure(0, weight=1)
        metrics.grid_columnconfigure(1, weight=1)

        self._create_metric_card(metrics, "Status", self.status_var, 0, 0)
        self._create_metric_card(metrics, "Recording Time", self.elapsed_var, 0, 1)
        self._create_metric_card(metrics, "Video If Stopped", self.projected_var, 1, 0)
        self._create_metric_card(metrics, "Captured Frames", self.frames_var, 1, 1)

        controls_card = self._create_card(main)
        controls_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        controls_card.grid_columnconfigure(0, weight=1)
        controls_card.grid_columnconfigure(1, weight=1)
        controls_card.grid_columnconfigure(2, weight=1)

        tk.Label(
            controls_card,
            text="Session Controls",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("SF Pro Display", 13, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(
            controls_card,
            text="Start, pause, or stop without losing the current recording state.",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 16))

        self.start_button = ttk.Button(controls_card, text="Start", command=self._start_or_resume, style="Accent.TButton")
        self.pause_button = ttk.Button(controls_card, text="Pause", command=self._pause, style="Neutral.TButton")
        self.stop_button = ttk.Button(controls_card, text="Stop", command=self._stop, style="Danger.TButton")
        self.change_folder_button = ttk.Button(main, text="Change Save Folder", command=self._choose_output_folder, style="Secondary.TButton")

        self.start_button.grid(row=2, column=0, sticky="ew", padx=(0, 8))
        self.pause_button.grid(row=2, column=1, sticky="ew", padx=4)
        self.stop_button.grid(row=2, column=2, sticky="ew", padx=(8, 0))

        settings_card = self._create_card(main)
        settings_card.grid(row=3, column=0, sticky="nsew", padx=(0, 10))
        settings_card.grid_columnconfigure(0, weight=1)
        self.capture_mode_box = ttk.Combobox(
            settings_card,
            state="readonly",
            textvariable=self.capture_mode_var,
            values=("Merged screens + camera", "Camera only"),
            style="Dark.TCombobox",
        )
        self.capture_mode_box.bind("<<ComboboxSelected>>", self._change_capture_mode)

        tk.Label(
            settings_card,
            text="Output and Capture",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("SF Pro Display", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            settings_card,
            text=(
                "Choose where sessions are saved and whether the video uses the merged desktop view or only the camera feed."
            ),
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10),
            wraplength=300,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        tk.Label(
            settings_card,
            text="Save folder",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10, "bold"),
        ).grid(row=2, column=0, sticky="w")
        tk.Label(
            settings_card,
            textvariable=self.output_var,
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("SF Pro Text", 10),
            wraplength=300,
            justify=tk.LEFT,
        ).grid(row=3, column=0, sticky="w", pady=(4, 12))
        self.change_folder_button.grid(row=4, column=0, sticky="w")

        tk.Label(
            settings_card,
            text="Capture mode",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10, "bold"),
        ).grid(row=5, column=0, sticky="w", pady=(18, 6))
        self.capture_mode_box.grid(row=6, column=0, sticky="ew")

        preview_card = self._create_card(main)
        preview_card.grid(row=3, column=1, sticky="nsew", padx=(10, 0))
        preview_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            preview_card,
            text="Camera Preview",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("SF Pro Display", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            preview_card,
            text="Live circular preview used for the webcam overlay. In camera-only mode, this becomes the full timelapse frame.",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10),
            wraplength=300,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        self.preview_label = tk.Label(
            preview_card,
            bg=self.colors["surface"],
            bd=0,
            highlightthickness=0,
        )
        self.preview_label.grid(row=2, column=0, sticky="se")
        self._sync_capture_mode_ui()
        self._draw_header_gradient()

    def _configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Accent.TButton",
            font=("SF Pro Text", 11, "bold"),
            foreground=self.colors["text"],
            background=self.colors["accent"],
            borderwidth=0,
            padding=(14, 12),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#7c3aed"), ("disabled", "#4c1d95")],
            foreground=[("disabled", "#d8b4fe")],
        )

        style.configure(
            "Neutral.TButton",
            font=("SF Pro Text", 11, "bold"),
            foreground=self.colors["text"],
            background="#1f2937",
            borderwidth=0,
            padding=(14, 12),
        )
        style.map(
            "Neutral.TButton",
            background=[("active", "#334155"), ("disabled", "#172033")],
            foreground=[("disabled", "#64748b")],
        )

        style.configure(
            "Danger.TButton",
            font=("SF Pro Text", 11, "bold"),
            foreground=self.colors["text"],
            background="#ea580c",
            borderwidth=0,
            padding=(14, 12),
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#f97316"), ("disabled", "#7c2d12")],
            foreground=[("disabled", "#fdba74")],
        )

        style.configure(
            "Secondary.TButton",
            font=("SF Pro Text", 10, "bold"),
            foreground=self.colors["text"],
            background=self.colors["surface_alt"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            borderwidth=1,
            padding=(12, 10),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#172033"), ("disabled", "#0b1120")],
            foreground=[("disabled", "#64748b")],
        )

        style.configure(
            "Dark.TCombobox",
            fieldbackground=self.colors["surface_alt"],
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            arrowcolor=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            insertcolor=self.colors["text"],
            padding=8,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", self.colors["surface_alt"]), ("disabled", "#0b1120")],
            foreground=[("disabled", "#64748b")],
            selectbackground=[("readonly", self.colors["surface_alt"])],
            selectforeground=[("readonly", self.colors["text"])],
        )

    def _create_card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=self.colors["surface"],
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            bd=0,
            padx=18,
            pady=18,
        )

    def _create_metric_card(
        self,
        parent: tk.Widget,
        title: str,
        variable: tk.StringVar,
        row: int,
        column: int,
    ) -> None:
        parent.grid_rowconfigure(row, weight=1)
        card = self._create_card(parent)
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        tk.Label(
            card,
            text=title,
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            card,
            textvariable=variable,
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("SF Pro Display", 13, "bold"),
            wraplength=280,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(10, 0))

    def _draw_header_gradient(self, _event: object | None = None) -> None:
        if not hasattr(self, "hero_canvas"):
            return

        canvas = self.hero_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")

        for offset in range(height):
            mix = offset / max(height - 1, 1)
            canvas.create_line(0, offset, width, offset, fill=self._mix_color("#5b21b6", "#0f172a", mix))

        for offset in range(width):
            mix = offset / max(width - 1, 1)
            color = self._mix_color("#8b5cf6", "#06b6d4", mix)
            canvas.create_line(offset, 0, offset, height, fill=color, stipple="gray50")

        canvas.create_oval(width - 170, -35, width + 40, 150, fill="#38bdf8", outline="", stipple="gray25")
        canvas.create_oval(width - 90, 55, width + 70, 205, fill="#8b5cf6", outline="", stipple="gray25")

        canvas.create_text(
            28,
            34,
            anchor="nw",
            text="Time Lapse Creator",
            fill=self.colors["text"],
            font=("SF Pro Display", 24, "bold"),
        )
        canvas.create_text(
            28,
            74,
            anchor="nw",
            width=max(width - 230, 200),
            text="Premium multi-monitor timelapse capture with a clean desktop recorder workflow.",
            fill="#e2e8f0",
            font=("SF Pro Text", 11),
        )

        chip_color = self._status_color()
        chip_text = self.status_var.get()
        chip_width = max(116, len(chip_text) * 10 + 26)
        chip_left = width - chip_width - 28
        chip_top = 30
        canvas.create_rectangle(chip_left, chip_top, chip_left + chip_width, chip_top + 34, fill=chip_color, outline="")
        canvas.create_text(
            chip_left + chip_width / 2,
            chip_top + 17,
            text=chip_text,
            fill="#ffffff",
            font=("SF Pro Text", 10, "bold"),
        )
        canvas.create_text(
            width - 28,
            80,
            anchor="ne",
            text=self.capture_mode_var.get() or "Merged screens + camera",
            fill="#e2e8f0",
            font=("SF Pro Text", 11, "bold"),
        )
        canvas.create_text(
            width - 28,
            106,
            anchor="ne",
            text="Last selection is saved",
            fill="#cbd5e1",
            font=("SF Pro Text", 10),
        )

    def _mix_color(self, start_hex: str, end_hex: str, fraction: float) -> str:
        start = tuple(int(start_hex[index : index + 2], 16) for index in (1, 3, 5))
        end = tuple(int(end_hex[index : index + 2], 16) for index in (1, 3, 5))
        blended = tuple(int(start[channel] + (end[channel] - start[channel]) * fraction) for channel in range(3))
        return f"#{blended[0]:02x}{blended[1]:02x}{blended[2]:02x}"

    def _status_color(self) -> str:
        if self.rendering:
            return self.colors["warning"]

        state = self.recorder.get_state()
        if state == RecorderState.RECORDING:
            return self.colors["success"]
        if state == RecorderState.PAUSED:
            return self.colors["warning"]
        return self.colors["accent"]

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
