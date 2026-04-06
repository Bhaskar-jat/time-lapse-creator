from __future__ import annotations


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


def is_valid_hex_color(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def mix_color(start_hex: str, end_hex: str, fraction: float) -> str:
    start = tuple(int(start_hex[index : index + 2], 16) for index in (1, 3, 5))
    end = tuple(int(end_hex[index : index + 2], 16) for index in (1, 3, 5))
    blended = tuple(int(start[channel] + (end[channel] - start[channel]) * fraction) for channel in range(3))
    return f"#{blended[0]:02x}{blended[1]:02x}{blended[2]:02x}"


def is_dark_color(color_hex: str) -> bool:
    red, green, blue = (int(color_hex[index : index + 2], 16) for index in (1, 3, 5))
    luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
    return luminance < 160


def resolve_theme_colors(theme_name: str, overrides: dict[str, str]) -> dict[str, str]:
    base = THEME_PRESETS.get(theme_name, THEME_PRESETS[DEFAULT_THEME_NAME]).copy()
    bg = overrides.get("bg", base["bg"])
    accent = overrides.get("accent", base["accent"])
    accent_2 = overrides.get("accent_2", base["accent_2"])

    dark_background = is_dark_color(bg)
    text = "#f8fafc" if dark_background else "#0f172a"
    surface = mix_color(bg, text, 0.08)
    surface_alt = mix_color(bg, text, 0.05)
    border = mix_color(bg, text, 0.18)
    muted = mix_color(text, bg, 0.46)

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

