from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from timelapse_creator.recorder import (
    AppConfig,
    CameraFeed,
    CaptureMode,
    RecorderState,
    SessionInfo,
    SettingsStore,
    TimeLapseRecorder,
)


DEFAULT_THEME_NAME = "Pink Silk"
THEME_PRESETS: dict[str, dict[str, str]] = {
    "Pink Silk": {
        "bg": "#120612",
        "accent": "#ec4899",
        "accent_2": "#fb7185",
        "success": "#34d399",
        "warning": "#f59e0b",
        "danger": "#fb7185",
    },
    "Aurora Violet": {
        "bg": "#070b16",
        "accent": "#8b5cf6",
        "accent_2": "#06b6d4",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "danger": "#f97316",
    },
    "Ocean Glass": {
        "bg": "#06121c",
        "accent": "#38bdf8",
        "accent_2": "#14b8a6",
        "success": "#10b981",
        "warning": "#f59e0b",
        "danger": "#fb7185",
    },
    "Emerald Night": {
        "bg": "#07140d",
        "accent": "#10b981",
        "accent_2": "#22c55e",
        "success": "#4ade80",
        "warning": "#f59e0b",
        "danger": "#f97316",
    },
    "Solar Amber": {
        "bg": "#160b05",
        "accent": "#f59e0b",
        "accent_2": "#f97316",
        "success": "#22c55e",
        "warning": "#fbbf24",
        "danger": "#ef4444",
    },
}
ACCENT_SWATCHES: list[tuple[str, str]] = [
    ("#ec4899", "#fb7185"),
    ("#8b5cf6", "#06b6d4"),
    ("#38bdf8", "#14b8a6"),
    ("#10b981", "#22c55e"),
    ("#f59e0b", "#f97316"),
]


def format_duration(total_seconds: float) -> str:
    seconds = max(int(total_seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class TimeLapseApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Time Lapse Creator")
        self.root.geometry("860x760")
        self.root.minsize(780, 680)

        self.settings_store = SettingsStore()
        self.theme_name = DEFAULT_THEME_NAME
        self.theme_overrides: dict[str, str] = {}
        self._load_theme_preferences()
        self.colors = self._resolve_theme_colors(self.theme_name, self.theme_overrides)

        self.config = AppConfig(preview_size=168)
        self.camera_feed = CameraFeed()
        self.recorder = TimeLapseRecorder(self.config, self.camera_feed, self.settings_store)
        self.camera_feed.start()

        self.closing = False
        self.rendering = False
        self.container_frame: tk.Frame | None = None
        self.scroll_canvas: tk.Canvas | None = None
        self.scrollbar: ttk.Scrollbar | None = None
        self._canvas_window_id: int | None = None
        self.main_frame: tk.Frame | None = None
        self._preview_image: ImageTk.PhotoImage | None = None
        self._theme_buttons: list[tk.Button] = []
        self._custom_color_buttons: list[ttk.Button] = []
        self._glow_layers: dict[str, tk.Canvas] = {}

        self._build_ui()
        self._update_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.root.configure(bg=self.colors["bg"])
        self._configure_styles()
        self._glow_layers = {}

        self.status_var = tk.StringVar(value="Ready")
        self.elapsed_var = tk.StringVar(value="Recording time: 00:00:00")
        self.projected_var = tk.StringVar(value="If stopped now: [00:00:00]")
        self.frames_var = tk.StringVar(value="Captured frames: 0")
        self.output_var = tk.StringVar(value=f"Save folder: {self.recorder.get_recordings_dir()}")
        self.capture_mode_var = tk.StringVar()
        self.theme_name_var = tk.StringVar(value=self.theme_name)

        self.container_frame = tk.Frame(self.root, bg=self.colors["bg"])
        self.container_frame.pack(fill=tk.BOTH, expand=True)

        self.scroll_canvas = tk.Canvas(
            self.container_frame,
            bg=self.colors["bg"],
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(self.container_frame, orient=tk.VERTICAL, command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.main_frame = tk.Frame(self.scroll_canvas, bg=self.colors["bg"], padx=24, pady=24)
        self._canvas_window_id = self.scroll_canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        self.main_frame.bind("<Configure>", self._on_main_frame_configure)
        self.scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel()

        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=1)
        self.main_frame.grid_rowconfigure(3, weight=1)

        self.hero_canvas = tk.Canvas(self.main_frame, height=160, highlightthickness=0, bd=0, bg=self.colors["bg"])
        self.hero_canvas.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.hero_canvas.bind("<Configure>", self._draw_header_gradient)

        metrics = tk.Frame(self.main_frame, bg=self.colors["bg"])
        metrics.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(18, 18))
        metrics.grid_columnconfigure(0, weight=1)
        metrics.grid_columnconfigure(1, weight=1)

        self._create_metric_card(metrics, "Status", self.status_var, 0, 0)
        self._create_metric_card(metrics, "Recording Time", self.elapsed_var, 0, 1)
        self._create_metric_card(metrics, "Video If Stopped", self.projected_var, 1, 0)
        self._create_metric_card(metrics, "Captured Frames", self.frames_var, 1, 1)

        controls_card = self._create_card(self.main_frame)
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

        self.start_button = ttk.Button(
            controls_card,
            text="Start",
            command=lambda: self._animate_button_press(self.start_button, "Accent", self._start_or_resume),
            style="Accent.TButton",
        )
        self.pause_button = ttk.Button(
            controls_card,
            text="Pause",
            command=lambda: self._animate_button_press(self.pause_button, "Neutral", self._pause),
            style="Neutral.TButton",
        )
        self.stop_button = ttk.Button(
            controls_card,
            text="Stop",
            command=lambda: self._animate_button_press(self.stop_button, "Danger", self._stop),
            style="Danger.TButton",
        )

        self.start_button.grid(row=2, column=0, sticky="ew", padx=(0, 8))
        self.pause_button.grid(row=2, column=1, sticky="ew", padx=4)
        self.stop_button.grid(row=2, column=2, sticky="ew", padx=(8, 0))

        settings_card = self._create_card(self.main_frame)
        settings_card.grid(row=3, column=0, sticky="nsew", padx=(0, 10))
        settings_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            settings_card,
            text="Options",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("SF Pro Display", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            settings_card,
            text="Save location, capture mode, theme presets, and custom colors are all available here.",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10),
            wraplength=320,
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
            wraplength=320,
            justify=tk.LEFT,
        ).grid(row=3, column=0, sticky="w", pady=(4, 10))

        self.change_folder_button = ttk.Button(
            settings_card,
            text="Change Save Folder",
            command=lambda: self._animate_button_press(self.change_folder_button, "Secondary", self._choose_output_folder),
            style="Secondary.TButton",
        )
        self.change_folder_button.grid(row=4, column=0, sticky="w")

        tk.Label(
            settings_card,
            text="Capture mode",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10, "bold"),
        ).grid(row=5, column=0, sticky="w", pady=(18, 6))
        self.capture_mode_box = ttk.Combobox(
            settings_card,
            state="readonly",
            textvariable=self.capture_mode_var,
            values=("Merged screens + camera", "Camera only"),
            style="Dark.TCombobox",
        )
        self.capture_mode_box.grid(row=6, column=0, sticky="ew")
        self.capture_mode_box.bind("<<ComboboxSelected>>", self._change_capture_mode)

        tk.Label(
            settings_card,
            text="Theme preset",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10, "bold"),
        ).grid(row=7, column=0, sticky="w", pady=(18, 6))
        self.theme_box = ttk.Combobox(
            settings_card,
            state="readonly",
            textvariable=self.theme_name_var,
            values=tuple(THEME_PRESETS.keys()),
            style="Dark.TCombobox",
        )
        self.theme_box.grid(row=8, column=0, sticky="ew")
        self.theme_box.bind("<<ComboboxSelected>>", self._change_theme_preset)

        tk.Label(
            settings_card,
            text="Quick accent colors",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10, "bold"),
        ).grid(row=9, column=0, sticky="w", pady=(18, 8))
        swatch_row = tk.Frame(settings_card, bg=self.colors["surface"])
        swatch_row.grid(row=10, column=0, sticky="w")
        self._theme_buttons = []
        for index, (primary, secondary) in enumerate(ACCENT_SWATCHES):
            swatch_button = tk.Button(
                swatch_row,
                width=3,
                height=1,
                bg=primary,
                activebackground=secondary,
                bd=0,
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=self.colors["border"],
                command=lambda accent=primary, accent_2=secondary: self._apply_accent_pair(accent, accent_2),
            )
            swatch_button.grid(row=0, column=index, padx=(0, 8))
            self._theme_buttons.append(swatch_button)

        tk.Label(
            settings_card,
            text="Custom colors",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10, "bold"),
        ).grid(row=11, column=0, sticky="w", pady=(18, 8))
        custom_row = tk.Frame(settings_card, bg=self.colors["surface"])
        custom_row.grid(row=12, column=0, sticky="w")
        self.custom_bg_button = ttk.Button(
            custom_row,
            text="Background",
            command=lambda: self._animate_button_press(
                self.custom_bg_button, "Secondary", lambda: self._choose_theme_color("bg", "Choose background color")
            ),
            style="Secondary.TButton",
        )
        self.custom_primary_button = ttk.Button(
            custom_row,
            text="Primary",
            command=lambda: self._animate_button_press(
                self.custom_primary_button, "Secondary", lambda: self._choose_theme_color("accent", "Choose primary button color")
            ),
            style="Secondary.TButton",
        )
        self.custom_gradient_button = ttk.Button(
            custom_row,
            text="Gradient",
            command=lambda: self._animate_button_press(
                self.custom_gradient_button, "Secondary", lambda: self._choose_theme_color("accent_2", "Choose gradient accent color")
            ),
            style="Secondary.TButton",
        )
        self.custom_bg_button.grid(row=0, column=0, padx=(0, 8))
        self.custom_primary_button.grid(row=0, column=1, padx=8)
        self.custom_gradient_button.grid(row=0, column=2, padx=(8, 0))
        self._custom_color_buttons = [self.custom_bg_button, self.custom_primary_button, self.custom_gradient_button]

        preview_card = self._create_card(self.main_frame)
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
            wraplength=320,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        self.preview_label = tk.Label(preview_card, bg=self.colors["surface"], bd=0, highlightthickness=0)
        self.preview_label.grid(row=2, column=0, sticky="n", pady=(0, 8))

        tk.Label(
            preview_card,
            text="The theme and colors are stored locally, so the app opens exactly how you left it.",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("SF Pro Text", 10),
            wraplength=320,
            justify=tk.LEFT,
        ).grid(row=3, column=0, sticky="w", pady=(12, 0))

        self._sync_capture_mode_ui()
        self._sync_theme_ui()
        self._draw_header_gradient()

    def _configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        accent_pressed = self._mix_color(self.colors["accent"], self.colors["bg"], 0.28)
        neutral_bg = self._mix_color(self.colors["surface_alt"], self.colors["text"], 0.08)
        neutral_pressed = self._mix_color(neutral_bg, self.colors["bg"], 0.22)
        danger_pressed = self._mix_color(self.colors["danger"], self.colors["bg"], 0.25)
        secondary_bg = self.colors["surface_alt"]
        secondary_pressed = self._mix_color(secondary_bg, self.colors["text"], 0.1)

        self._configure_button_style("Accent.TButton", self.colors["accent"], self.colors["text"], (16, 12))
        self._configure_button_style("AccentPressed.TButton", accent_pressed, self.colors["text"], (15, 11))
        self._configure_button_style("AccentPulse.TButton", self.colors["accent"], self.colors["text"], (18, 14))

        self._configure_button_style("Neutral.TButton", neutral_bg, self.colors["text"], (16, 12))
        self._configure_button_style("NeutralPressed.TButton", neutral_pressed, self.colors["text"], (15, 11))
        self._configure_button_style("NeutralPulse.TButton", neutral_bg, self.colors["text"], (18, 14))

        self._configure_button_style("Danger.TButton", self.colors["danger"], self.colors["text"], (16, 12))
        self._configure_button_style("DangerPressed.TButton", danger_pressed, self.colors["text"], (15, 11))
        self._configure_button_style("DangerPulse.TButton", self.colors["danger"], self.colors["text"], (18, 14))

        self._configure_button_style("Secondary.TButton", secondary_bg, self.colors["text"], (13, 10), borderwidth=1)
        self._configure_button_style("SecondaryPressed.TButton", secondary_pressed, self.colors["text"], (12, 9), borderwidth=1)
        self._configure_button_style("SecondaryPulse.TButton", secondary_bg, self.colors["text"], (15, 12), borderwidth=1)

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
            fieldbackground=[("readonly", self.colors["surface_alt"]), ("disabled", self.colors["bg"])],
            foreground=[("disabled", self.colors["muted"])],
            selectbackground=[("readonly", self.colors["surface_alt"])],
            selectforeground=[("readonly", self.colors["text"])],
        )

    def _configure_button_style(
        self,
        style_name: str,
        background: str,
        foreground: str,
        padding: tuple[int, int],
        borderwidth: int = 0,
    ) -> None:
        style = ttk.Style()
        style.configure(
            style_name,
            font=("SF Pro Text", 10, "bold"),
            foreground=foreground,
            background=background,
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            borderwidth=borderwidth,
            padding=padding,
        )
        style.map(
            style_name,
            background=[("disabled", self._mix_color(background, self.colors["bg"], 0.35))],
            foreground=[("disabled", self.colors["muted"])],
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
            wraplength=300,
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
            canvas.create_line(0, offset, width, offset, fill=self._mix_color(self.colors["accent"], self.colors["bg"], mix))

        for offset in range(width):
            mix = offset / max(width - 1, 1)
            color = self._mix_color(self.colors["accent"], self.colors["accent_2"], mix)
            canvas.create_line(offset, 0, offset, height, fill=color, stipple="gray50")

        canvas.create_oval(width - 200, -48, width + 20, 160, fill=self.colors["accent_2"], outline="", stipple="gray25")
        canvas.create_oval(width - 110, 62, width + 76, 228, fill=self.colors["accent"], outline="", stipple="gray25")

        canvas.create_text(
            28,
            34,
            anchor="nw",
            text="Time Lapse Creator",
            fill=self.colors["text"],
            font=("SF Pro Display", 25, "bold"),
        )
        canvas.create_text(
            28,
            76,
            anchor="nw",
            width=max(width - 240, 240),
            text="Pink-first premium timelapse recorder with saved modes, saved colors, and a cleaner desktop workflow.",
            fill=self._mix_color(self.colors["text"], self.colors["bg"], 0.18),
            font=("SF Pro Text", 11),
        )

        chip_color = self._status_color()
        chip_text = self.status_var.get()
        chip_width = max(118, len(chip_text) * 10 + 28)
        chip_left = width - chip_width - 28
        chip_top = 28
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
            82,
            anchor="ne",
            text=self.theme_name_var.get() or DEFAULT_THEME_NAME,
            fill=self.colors["text"],
            font=("SF Pro Text", 11, "bold"),
        )
        canvas.create_text(
            width - 28,
            108,
            anchor="ne",
            text=self.capture_mode_var.get() or "Merged screens + camera",
            fill=self._mix_color(self.colors["text"], self.colors["bg"], 0.2),
            font=("SF Pro Text", 10),
        )

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
        self._draw_header_gradient()
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

    def _change_theme_preset(self, _event: object | None = None) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            self._sync_theme_ui()
            messagebox.showinfo("Recording active", "Stop the current recording before changing the theme.")
            return

        selected_theme = self.theme_name_var.get()
        if selected_theme not in THEME_PRESETS:
            self._sync_theme_ui()
            return

        self.theme_name = selected_theme
        self.theme_overrides = {}
        self._save_theme_preferences()
        self._apply_theme(rebuild=True)

    def _apply_accent_pair(self, accent: str, accent_2: str) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            messagebox.showinfo("Recording active", "Stop the current recording before changing theme colors.")
            return

        self.theme_overrides["accent"] = accent
        self.theme_overrides["accent_2"] = accent_2
        self._save_theme_preferences()
        self._apply_theme(rebuild=True)

    def _choose_theme_color(self, key: str, title: str) -> None:
        if self.rendering or self.recorder.get_state() != RecorderState.IDLE:
            messagebox.showinfo("Recording active", "Stop the current recording before changing theme colors.")
            return

        initial_color = self.theme_overrides.get(key) or self.colors[key]
        _, selected_hex = colorchooser.askcolor(parent=self.root, title=title, initialcolor=initial_color)
        if not selected_hex:
            return

        self.theme_overrides[key] = selected_hex
        self._save_theme_preferences()
        self._apply_theme(rebuild=True)

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
            self._draw_header_gradient()
            messagebox.showerror("Render failed", str(error))
            return

        assert session is not None
        self.status_var.set(f"Saved: {session.video_path.name}")
        self.output_var.set(f"Save folder: {self.recorder.get_recordings_dir()}")
        self._draw_header_gradient()
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
        self._sync_theme_ui()

        if self.rendering:
            self.start_button.state(["disabled"])
            self.pause_button.state(["disabled"])
            self.stop_button.state(["disabled"])
            self.change_folder_button.state(["disabled"])
            self.capture_mode_box.state(["disabled"])
            self.theme_box.state(["disabled"])
            self._set_theme_buttons_state(tk.DISABLED)
            self._set_custom_color_buttons_state(["disabled"])
        elif state == RecorderState.IDLE:
            self.status_var.set("Ready")
            self.start_button.config(text="Start")
            self.start_button.state(["!disabled"])
            self.pause_button.state(["disabled"])
            self.stop_button.state(["disabled"])
            self.change_folder_button.state(["!disabled"])
            self.capture_mode_box.state(["!disabled", "readonly"])
            self.theme_box.state(["!disabled", "readonly"])
            self._set_theme_buttons_state(tk.NORMAL)
            self._set_custom_color_buttons_state(["!disabled"])
        elif state == RecorderState.RECORDING:
            self.status_var.set("Recording")
            self.start_button.config(text="Resume")
            self.start_button.state(["disabled"])
            self.pause_button.state(["!disabled"])
            self.stop_button.state(["!disabled"])
            self.change_folder_button.state(["disabled"])
            self.capture_mode_box.state(["disabled"])
            self.theme_box.state(["disabled"])
            self._set_theme_buttons_state(tk.DISABLED)
            self._set_custom_color_buttons_state(["disabled"])
        elif state == RecorderState.PAUSED:
            self.status_var.set("Paused")
            self.start_button.config(text="Resume")
            self.start_button.state(["!disabled"])
            self.pause_button.state(["disabled"])
            self.stop_button.state(["!disabled"])
            self.change_folder_button.state(["disabled"])
            self.capture_mode_box.state(["disabled"])
            self.theme_box.state(["disabled"])
            self._set_theme_buttons_state(tk.DISABLED)
            self._set_custom_color_buttons_state(["disabled"])

        self._draw_header_gradient()
        self._refresh_camera_preview()
        self.root.after(250, self._update_ui)

    def _refresh_camera_preview(self) -> None:
        preview_size = self.config.preview_size
        latest_frame = self.camera_feed.get_latest_frame()
        if latest_frame is None:
            preview = Image.new("RGBA", (preview_size, preview_size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(preview)
            draw.ellipse((4, 4, preview_size - 4, preview_size - 4), fill=(40, 40, 40, 255))
            draw.text((preview_size // 2 - 30, preview_size // 2 - 8), "No cam", fill=(220, 220, 220, 255))
        else:
            preview = Image.fromarray(latest_frame)
            crop = min(preview.width, preview.height)
            left = (preview.width - crop) // 2
            top = (preview.height - crop) // 2
            preview = preview.crop((left, top, left + crop, top + crop))
            preview = preview.resize((preview_size, preview_size), Image.Resampling.LANCZOS).convert("RGBA")
            mask = Image.new("L", preview.size, 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, preview.width - 1, preview.height - 1), fill=255)
            preview.putalpha(mask)

        outlined = Image.new("RGBA", (preview_size + 20, preview_size + 20), (0, 0, 0, 0))
        outline_draw = ImageDraw.Draw(outlined)
        outline_draw.ellipse((6, 10, preview_size + 14, preview_size + 18), fill=(0, 0, 0, 90))
        outlined.paste(preview, (10, 0), preview)
        outline_draw.ellipse(
            (10, 0, preview_size + 9, preview_size - 1),
            outline=self.colors["accent"],
            width=4,
        )

        self._preview_image = ImageTk.PhotoImage(outlined)
        self.preview_label.configure(image=self._preview_image)

    def _sync_capture_mode_ui(self) -> None:
        self.capture_mode_var.set(self._capture_mode_label(self.recorder.get_capture_mode()))

    def _sync_theme_ui(self) -> None:
        self.theme_name_var.set(self.theme_name)

    def _capture_mode_label(self, capture_mode: CaptureMode) -> str:
        if capture_mode == CaptureMode.CAMERA_ONLY:
            return "Camera only"
        return "Merged screens + camera"

    def _capture_mode_from_label(self, label: str) -> CaptureMode:
        if label == "Camera only":
            return CaptureMode.CAMERA_ONLY
        return CaptureMode.MERGED_WITH_CAMERA

    def _animate_button_press(self, button: ttk.Button, style_prefix: str, callback: callable) -> None:
        if button.instate(["disabled"]):
            return

        default_style = f"{style_prefix}.TButton"
        pressed_style = f"{style_prefix}Pressed.TButton"
        pulse_style = f"{style_prefix}Pulse.TButton"
        glow_color = self._button_glow_color(style_prefix)

        button.configure(style=pressed_style)
        self._spawn_button_glow(button, glow_color)

        def _pulse_button() -> None:
            if button.winfo_exists():
                button.configure(style=pulse_style)

        def _run_action() -> None:
            callback()

        def _restore_button() -> None:
            if button.winfo_exists():
                button.configure(style=default_style)

        self.root.after(70, _pulse_button)
        self.root.after(120, _run_action)
        self.root.after(190, _restore_button)

    def _button_glow_color(self, style_prefix: str) -> str:
        if style_prefix == "Danger":
            return self.colors["danger"]
        if style_prefix == "Neutral":
            return self._mix_color(self.colors["accent_2"], self.colors["text"], 0.45)
        return self.colors["accent"]

    def _get_glow_layer(self, parent: tk.Widget) -> tk.Canvas:
        layer_key = str(parent)
        existing = self._glow_layers.get(layer_key)
        if existing is not None and existing.winfo_exists():
            return existing

        layer = tk.Canvas(
            parent,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
        )
        layer.place(x=0, y=0, relwidth=1, relheight=1)
        layer.tk.call("lower", layer._w)
        self._glow_layers[layer_key] = layer
        return layer

    def _spawn_button_glow(self, button: ttk.Button, color: str) -> None:
        if not button.winfo_exists():
            return

        parent = button.nametowidget(button.winfo_parent())
        layer = self._get_glow_layer(parent)
        layer.delete("glow")
        parent.update_idletasks()

        center_x = button.winfo_x() + (button.winfo_width() / 2)
        center_y = button.winfo_y() + (button.winfo_height() / 2)
        base_radius = max(button.winfo_width(), button.winfo_height()) * 0.34

        outer = layer.create_oval(0, 0, 0, 0, fill=color, outline="", stipple="gray25", tags="glow")
        inner = layer.create_oval(0, 0, 0, 0, fill=self._mix_color(color, "#ffffff", 0.18), outline="", stipple="gray50", tags="glow")

        def _animate(step: int = 0) -> None:
            if not layer.winfo_exists():
                return
            if step > 8:
                layer.delete("glow")
                return

            growth = step / 8
            outer_radius = base_radius + (base_radius * 1.25 * growth)
            inner_radius = base_radius * 0.72 + (base_radius * 0.68 * growth)

            layer.coords(
                outer,
                center_x - outer_radius,
                center_y - outer_radius,
                center_x + outer_radius,
                center_y + outer_radius,
            )
            layer.coords(
                inner,
                center_x - inner_radius,
                center_y - inner_radius,
                center_x + inner_radius,
                center_y + inner_radius,
            )

            if step >= 6:
                layer.itemconfigure(outer, stipple="gray50")
            if step >= 7:
                layer.itemconfigure(inner, stipple="gray25")

            layer.after(22, lambda: _animate(step + 1))

        _animate()

    def _set_theme_buttons_state(self, state: str) -> None:
        for button in self._theme_buttons:
            if button.winfo_exists():
                button.configure(state=state)

    def _set_custom_color_buttons_state(self, states: list[str]) -> None:
        for button in self._custom_color_buttons:
            if button.winfo_exists():
                button.state(states)

    def _load_theme_preferences(self) -> None:
        settings = self.settings_store.load()
        theme_name = settings.get("theme_name", DEFAULT_THEME_NAME)
        if theme_name not in THEME_PRESETS:
            theme_name = DEFAULT_THEME_NAME

        overrides: dict[str, str] = {}
        for key in ("bg", "accent", "accent_2"):
            value = settings.get(f"theme_{key}", "")
            if self._is_valid_hex_color(value):
                overrides[key] = value

        self.theme_name = theme_name
        self.theme_overrides = overrides

    def _save_theme_preferences(self) -> None:
        self.settings_store.update(
            {
                "theme_name": self.theme_name,
                "theme_bg": self.theme_overrides.get("bg", ""),
                "theme_accent": self.theme_overrides.get("accent", ""),
                "theme_accent_2": self.theme_overrides.get("accent_2", ""),
            }
        )

    def _apply_theme(self, rebuild: bool = False) -> None:
        self.colors = self._resolve_theme_colors(self.theme_name, self.theme_overrides)
        if rebuild:
            self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        self._unbind_mousewheel()
        if self.container_frame is not None and self.container_frame.winfo_exists():
            self.container_frame.destroy()
        self.container_frame = None
        self.scroll_canvas = None
        self.scrollbar = None
        self._canvas_window_id = None
        self.main_frame = None
        self._build_ui()

    def _on_main_frame_configure(self, _event: object | None = None) -> None:
        if self.scroll_canvas is None or not self.scroll_canvas.winfo_exists():
            return
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event[tk.Canvas]) -> None:
        if self.scroll_canvas is None or self._canvas_window_id is None:
            return
        canvas_width = max(event.width, 1)
        self.scroll_canvas.itemconfigure(self._canvas_window_id, width=canvas_width)

    def _bind_mousewheel(self) -> None:
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.bind_all("<Shift-MouseWheel>", self._on_mousewheel)
        self.root.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.root.bind_all("<Button-5>", self._on_mousewheel_linux)

    def _unbind_mousewheel(self) -> None:
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Shift-MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        if self.scroll_canvas is None or not self.scroll_canvas.winfo_exists():
            return
        if abs(event.delta) < 1:
            return
        scroll_units = -1 if event.delta > 0 else 1
        if abs(event.delta) >= 120:
            scroll_units = int(-event.delta / 120)
        self.scroll_canvas.yview_scroll(scroll_units, "units")

    def _on_mousewheel_linux(self, event: tk.Event[tk.Misc]) -> None:
        if self.scroll_canvas is None or not self.scroll_canvas.winfo_exists():
            return
        scroll_units = -1 if event.num == 4 else 1
        self.scroll_canvas.yview_scroll(scroll_units, "units")

    def _resolve_theme_colors(self, theme_name: str, overrides: dict[str, str]) -> dict[str, str]:
        base = THEME_PRESETS.get(theme_name, THEME_PRESETS[DEFAULT_THEME_NAME]).copy()
        bg = overrides.get("bg", base["bg"])
        accent = overrides.get("accent", base["accent"])
        accent_2 = overrides.get("accent_2", base["accent_2"])

        dark_background = self._is_dark_color(bg)
        text = "#f8fafc" if dark_background else "#0f172a"
        surface = self._mix_color(bg, text, 0.08)
        surface_alt = self._mix_color(bg, text, 0.05)
        border = self._mix_color(bg, text, 0.18)
        muted = self._mix_color(text, bg, 0.46)

        return {
            "bg": bg,
            "surface": surface,
            "surface_alt": surface_alt,
            "border": border,
            "text": text,
            "muted": muted,
            "accent": accent,
            "accent_2": accent_2,
            "success": base["success"],
            "warning": base["warning"],
            "danger": base["danger"],
        }

    def _is_dark_color(self, color_hex: str) -> bool:
        red, green, blue = (int(color_hex[index : index + 2], 16) for index in (1, 3, 5))
        luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
        return luminance < 160

    def _is_valid_hex_color(self, value: str) -> bool:
        if len(value) != 7 or not value.startswith("#"):
            return False
        try:
            int(value[1:], 16)
        except ValueError:
            return False
        return True

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
        self._unbind_mousewheel()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    TimeLapseApp(root)
    root.mainloop()
    return 0
