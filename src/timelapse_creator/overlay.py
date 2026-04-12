from __future__ import annotations

import platform
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def format_timer_mmss(total_seconds: float) -> str:
    seconds = max(int(total_seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def is_valid_hex_color(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if not value.startswith("#") or len(value) != 7:
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


@lru_cache(maxsize=32)
def load_overlay_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # Pillow commonly ships DejaVu fonts; keep a robust fallback.
    candidates: list[str] = [
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
    ]

    try:
        import PIL  # noqa: PLC0415

        pil_fonts_dir = Path(PIL.__file__).resolve().parent / "fonts"
        for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            candidates.append(str(pil_fonts_dir / name))
    except Exception:
        pass

    system = platform.system()
    if system == "Darwin":
        candidates.extend(
            [
                "/System/Library/Fonts/SFNS.ttf",
                "/System/Library/Fonts/SFNSDisplay.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
            ]
        )
    elif system == "Windows":
        candidates.extend(
            [
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\arialbd.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ]
        )

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _overlay_text_bitmap_fallback(
    target_size: tuple[int, int],
    text: str,
    color: tuple[int, int, int, int],
) -> Image.Image:
    font = ImageFont.load_default()
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)
    bbox = probe_draw.textbbox((0, 0), text, font=font)
    text_width = max(1, bbox[2] - bbox[0])
    text_height = max(1, bbox[3] - bbox[1])

    base = Image.new("RGBA", (text_width, text_height), (0, 0, 0, 0))
    base_draw = ImageDraw.Draw(base)
    base_draw.text((0, 0), text, font=font, fill=color)

    scale = min(target_size[0] / text_width, target_size[1] / text_height)
    scaled = base.resize(
        (max(1, int(text_width * scale)), max(1, int(text_height * scale))),
        Image.Resampling.LANCZOS,
    )
    return scaled


def apply_timer_overlay(
    base_image: Image.Image,
    *,
    seconds: float,
    enabled: bool,
    overlay_width_px: int,
    color_hex: str,
) -> Image.Image:
    if not enabled:
        return base_image

    timestamp = format_timer_mmss(seconds)

    image = base_image.convert("RGBA")
    draw = ImageDraw.Draw(image)

    margin = 28
    box_width = max(220, min(int(overlay_width_px), image.width - (margin * 2)))
    box_height = max(90, min(int(box_width * 0.28), image.height - (margin * 2)))

    pad_x = max(18, int(box_width * 0.06))
    pad_y = max(14, int(box_height * 0.14))
    inner_width = max(1, box_width - pad_x * 2)
    inner_height = max(1, box_height - pad_y * 2)

    font_probe = load_overlay_font(32)
    scalable_font = isinstance(font_probe, ImageFont.FreeTypeFont)
    if scalable_font:

        def _fits(size: int) -> bool:
            font = load_overlay_font(size)
            stroke = max(2, size // 14)
            bbox = draw.textbbox((0, 0), timestamp, font=font, stroke_width=stroke)
            text_w = max(1, bbox[2] - bbox[0])
            text_h = max(1, bbox[3] - bbox[1])
            return text_w <= inner_width and text_h <= inner_height

        lo, hi = 12, 1600
        best = lo
        while lo <= hi:
            mid = (lo + hi) // 2
            if _fits(mid):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1

        font_size = best
        font = load_overlay_font(font_size)
        stroke_width = max(2, font_size // 14)

        text_bbox = draw.textbbox((0, 0), timestamp, font=font, stroke_width=stroke_width)
        text_width = max(1, text_bbox[2] - text_bbox[0])
        text_height = max(1, text_bbox[3] - text_bbox[1])
        text_offset_x = -text_bbox[0]
        text_offset_y = -text_bbox[1]
        rendered_text_image: Image.Image | None = None
    else:
        stroke_width = 0
        rendered_text_image = _overlay_text_bitmap_fallback(
            (inner_width, inner_height),
            timestamp,
            (255, 255, 255, 255),
        )
        text_width, text_height = rendered_text_image.size
        text_offset_x = 0
        text_offset_y = 0

    box_left = margin
    box_bottom = image.height - margin
    box_top = box_bottom - box_height
    box_right = box_left + box_width

    radius = max(18, int(box_height * 0.22))
    draw.rounded_rectangle(
        (box_left, box_top, box_right, box_bottom),
        radius=radius,
        fill=(0, 0, 0, 165),
        outline=(255, 255, 255, 45),
        width=1,
    )

    r, g, b = hex_to_rgb(color_hex) if is_valid_hex_color(color_hex) else (236, 72, 153)
    text_x = box_left + (box_width - text_width) / 2 + text_offset_x
    text_y = box_top + (box_height - text_height) / 2 + text_offset_y

    if rendered_text_image is not None:
        tinted = Image.new("RGBA", rendered_text_image.size, (r, g, b, 255))
        mask = rendered_text_image.split()[-1]
        tinted.putalpha(mask)
        shadow = Image.new("RGBA", tinted.size, (0, 0, 0, 140))
        shadow.putalpha(mask)
        shadow_offset = max(2, int(min(inner_width, inner_height) * 0.06))
        image.alpha_composite(shadow, (int(text_x + shadow_offset), int(text_y + shadow_offset)))
        image.alpha_composite(tinted, (int(text_x), int(text_y)))
    else:
        shadow_offset = max(2, font_size // 22)
        draw.text((text_x + shadow_offset, text_y + shadow_offset), timestamp, font=font, fill=(0, 0, 0, 140))
        draw.text(
            (text_x, text_y),
            timestamp,
            font=font,
            fill=(r, g, b, 255),
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0, 230),
        )

    # Top-left date box (today), matching the timer treatment.
    date_text = datetime.now().strftime("%Y-%m-%d")
    date_font_probe = load_overlay_font(20)
    date_scalable = isinstance(date_font_probe, ImageFont.FreeTypeFont)
    if date_scalable:
        date_font_size = max(16, int(box_height * 0.32))
        date_font = load_overlay_font(date_font_size)
        date_stroke = max(1, date_font_size // 18)
        date_bbox = draw.textbbox((0, 0), date_text, font=date_font, stroke_width=date_stroke)
        date_text_width = max(1, date_bbox[2] - date_bbox[0])
        date_text_height = max(1, date_bbox[3] - date_bbox[1])
        date_offset_x = -date_bbox[0]
        date_offset_y = -date_bbox[1]
        date_rendered_image: Image.Image | None = None
    else:
        date_stroke = 0
        date_rendered_image = _overlay_text_bitmap_fallback((240, 64), date_text, (255, 255, 255, 255))
        date_text_width, date_text_height = date_rendered_image.size
        date_offset_x = 0
        date_offset_y = 0

    date_pad_x = max(12, int(box_width * 0.04))
    date_pad_y = max(8, int(box_height * 0.09))
    date_box_width = date_text_width + (date_pad_x * 2)
    date_box_height = date_text_height + (date_pad_y * 2)
    date_left = margin
    date_top = margin
    date_right = date_left + date_box_width
    date_bottom = date_top + date_box_height
    date_radius = max(10, int(date_box_height * 0.28))

    draw.rounded_rectangle(
        (date_left, date_top, date_right, date_bottom),
        radius=date_radius,
        fill=(0, 0, 0, 150),
        outline=(255, 255, 255, 35),
        width=1,
    )

    date_x = date_left + ((date_box_width - date_text_width) / 2) + date_offset_x
    date_y = date_top + ((date_box_height - date_text_height) / 2) + date_offset_y
    if date_rendered_image is not None:
        date_shadow = Image.new("RGBA", date_rendered_image.size, (0, 0, 0, 120))
        date_mask = date_rendered_image.split()[-1]
        date_shadow.putalpha(date_mask)
        date_text_img = Image.new("RGBA", date_rendered_image.size, (255, 255, 255, 255))
        date_text_img.putalpha(date_mask)
        image.alpha_composite(date_shadow, (int(date_x + 2), int(date_y + 2)))
        image.alpha_composite(date_text_img, (int(date_x), int(date_y)))
    else:
        draw.text((date_x + 1, date_y + 1), date_text, font=date_font, fill=(0, 0, 0, 120))
        draw.text(
            (date_x, date_y),
            date_text,
            font=date_font,
            fill=(255, 255, 255, 235),
            stroke_width=date_stroke,
            stroke_fill=(0, 0, 0, 180),
        )

    return image.convert("RGB")
