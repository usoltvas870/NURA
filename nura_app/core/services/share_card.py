"""
Генератор share-карточки NURA.
PNG 1080×1080, тёмный фон, золотой акцент.
Возвращает bytes для отправки через aiogram.
"""
from __future__ import annotations

import io
import math
import os
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── Цвета бренда ──
BG_COLOR        = (10, 14, 12)       # #0A0E0C
BG2_COLOR       = (14, 20, 16)       # #0E1410
ACCENT_COLOR    = (201, 165, 92)     # #C9A55C — золото
ACCENT_DIM      = (201, 165, 92, 40) # прозрачный золотой
GREEN_COLOR     = (151, 197, 161)    # #97C5A1
INK_COLOR       = (232, 224, 208)    # #E8E0D0
INK_DIM_COLOR   = (232, 224, 208, 140)
BORDER_COLOR    = (151, 197, 161, 30)

SIZE = 1080
PADDING = 72


def _find_font(name_hints: list[str], size: int) -> ImageFont.FreeTypeFont:
    """Найти шрифт по подсказкам или вернуть дефолтный."""
    project_fonts = Path(__file__).parent.parent / "static" / "fonts"
    search_dirs = [
        project_fonts,
        Path("/usr/share/fonts/truetype/ubuntu"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/noto"),
        Path("/usr/share/fonts"),
    ]

    for hint in name_hints:
        for d in search_dirs:
            if not d.exists():
                continue
            for f in d.rglob("*.ttf"):
                if hint.lower() in f.name.lower():
                    try:
                        return ImageFont.truetype(str(f), size)
                    except Exception:
                        continue

    logger.warning("TTF font not found, using PIL default")
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int,
               draw: ImageDraw.ImageDraw) -> list[str]:
    """Разбить текст на строки по max_width пикселей."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_rounded_rect(draw: ImageDraw.ImageDraw, xy: tuple,
                        radius: int, fill: tuple) -> None:
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def _draw_star(draw: ImageDraw.ImageDraw, cx: int, cy: int,
               r_outer: int, r_inner: int, points: int,
               fill: tuple, alpha: int = 255) -> None:
    """Нарисовать звезду."""
    coords = []
    for i in range(points * 2):
        angle = math.pi / points * i - math.pi / 2
        r = r_outer if i % 2 == 0 else r_inner
        coords.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    color = fill[:3] + (alpha,) if len(fill) == 3 else fill[:3] + (alpha,)
    draw.polygon(coords, fill=color)


def generate_compat_card(
    sender_name: str,
    partner_name: str,
    user_arcana_name: str,
    user_arcana_number: int,
    partner_arcana_name: str,
    partner_arcana_number: int,
    compatibility_line: str,
) -> bytes:
    """
    Генерирует share-карточку совместимости.
    Возвращает PNG bytes.
    """
    # ── Шрифты ──
    font_logo    = _find_font(["Ubuntu-B", "DejaVuSans-Bold", "LiberationSans-Bold"], 36)
    font_title   = _find_font(["Ubuntu-B", "DejaVuSans-Bold", "LiberationSans-Bold"], 52)
    font_arcana  = _find_font(["Ubuntu-B", "DejaVuSans-Bold", "LiberationSans-Bold"], 38)
    font_name    = _find_font(["Ubuntu-R", "DejaVuSans", "LiberationSans-Regular"], 30)
    font_number  = _find_font(["Ubuntu-R", "DejaVuSans", "LiberationSans-Regular"], 22)
    font_tagline = _find_font(["Ubuntu-R", "DejaVuSans", "LiberationSans-Regular"], 28)
    font_url     = _find_font(["Ubuntu-R", "DejaVuSans", "LiberationSans-Regular"], 24)

    # ── Canvas ──
    img  = Image.new("RGBA", (SIZE, SIZE), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img, "RGBA")

    content_w = SIZE - PADDING * 2

    # ── Фоновый градиент (имитация через полосы) ──
    for y in range(SIZE):
        alpha = int(18 * (1 - y / SIZE))
        draw.line([(0, y), (SIZE, y)], fill=(14, 26, 18, alpha))

    # ── Декоративные звёзды на фоне ──
    _draw_star(draw, 900, 150, 60, 25, 4, ACCENT_COLOR, 18)
    _draw_star(draw, 180, 880, 40, 16, 4, ACCENT_COLOR, 14)
    _draw_star(draw, 60,  200, 25, 10, 4, GREEN_COLOR,  20)
    _draw_star(draw, 980, 700, 35, 14, 4, GREEN_COLOR,  15)

    # ── Горизонтальные разделители (тонкие линии) ──
    draw.line([(PADDING, 155), (SIZE - PADDING, 155)],
              fill=BORDER_COLOR[:3] + (50,), width=1)
    draw.line([(PADDING, SIZE - 155), (SIZE - PADDING, SIZE - 155)],
              fill=BORDER_COLOR[:3] + (50,), width=1)

    y = 0

    # ── HEADER: логотип + слоган ──
    y = 56
    draw.text((PADDING, y), "NURA", font=font_logo, fill=ACCENT_COLOR)
    tagline = "Матрица Судьбы · AI-анализ"
    tb = draw.textbbox((0, 0), tagline, font=font_url)
    draw.text((SIZE - PADDING - (tb[2] - tb[0]), y + 8),
              tagline, font=font_url, fill=INK_DIM_COLOR[:3] + (120,))

    # ── TITLE ──
    y = 190
    title = "Совместимость архетипов"
    tb = draw.textbbox((0, 0), title, font=font_title)
    title_w = tb[2] - tb[0]
    draw.text(((SIZE - title_w) // 2, y), title, font=font_title, fill=INK_COLOR)

    # ── COMPATIBILITY LINE ──
    y += 70
    comp_lines = _wrap_text(compatibility_line, font_tagline, content_w, draw)
    for line in comp_lines[:2]:
        lb = draw.textbbox((0, 0), line, font=font_tagline)
        lw = lb[2] - lb[0]
        draw.text(((SIZE - lw) // 2, y), line, font=font_tagline,
                  fill=ACCENT_COLOR + (180,) if len(ACCENT_COLOR) == 3
                  else ACCENT_COLOR)
        y += 40

    # ── ARCANA CARDS: два блока рядом ──
    y += 40
    card_w   = 420
    card_h   = 300
    gap      = SIZE - PADDING * 2 - card_w * 2
    card1_x  = PADDING
    card2_x  = SIZE - PADDING - card_w

    def draw_arcana_card(cx: int, cy: int, name: str, number: int,
                         person: str, is_left: bool) -> None:
        _draw_rounded_rect(draw, (cx, cy, cx + card_w, cy + card_h),
                           radius=24,
                           fill=BG2_COLOR + (255,))
        draw.rounded_rectangle([cx, cy, cx + card_w, cy + card_h],
                                radius=24,
                                outline=ACCENT_COLOR + (60,) if len(ACCENT_COLOR)==3
                                else ACCENT_COLOR,
                                width=1)

        num_str = str(number)
        nb = draw.textbbox((0, 0), num_str, font=font_title)
        nw = nb[2] - nb[0]
        num_x = cx + (card_w - nw) // 2
        draw.text((num_x, cy + 28), num_str, font=font_title,
                  fill=ACCENT_COLOR + (40,) if len(ACCENT_COLOR)==3 else ACCENT_COLOR)

        ab = draw.textbbox((0, 0), name, font=font_arcana)
        aw = ab[2] - ab[0]
        draw.text((cx + (card_w - aw) // 2, cy + 110), name,
                  font=font_arcana, fill=INK_COLOR)

        sub = f"Аркан {number}"
        sb = draw.textbbox((0, 0), sub, font=font_number)
        sw = sb[2] - sb[0]
        draw.text((cx + (card_w - sw) // 2, cy + 168), sub,
                  font=font_number, fill=INK_DIM_COLOR[:3] + (160,))

        person_short = person[:14] + "…" if len(person) > 15 else person
        pb = draw.textbbox((0, 0), person_short, font=font_name)
        pw = pb[2] - pb[0]

        badge_h = 44
        badge_y = cy + card_h - badge_h - 16
        badge_x = cx + (card_w - pw - 32) // 2
        _draw_rounded_rect(draw,
                           (badge_x - 4, badge_y,
                            badge_x + pw + 36, badge_y + badge_h),
                           radius=22,
                           fill=ACCENT_COLOR[:3] + (25,))
        draw.text((badge_x + 16, badge_y + 8), person_short,
                  font=font_name, fill=ACCENT_COLOR)

    draw_arcana_card(card1_x, y, user_arcana_name, user_arcana_number,
                     sender_name, is_left=True)

    plus_x = card1_x + card_w + gap // 2
    plus_y = y + card_h // 2 - 20
    _draw_star(draw, plus_x, plus_y, 22, 9, 4, ACCENT_COLOR)

    draw_arcana_card(card2_x, y, partner_arcana_name, partner_arcana_number,
                     partner_name, is_left=False)

    # ── FOOTER ──
    y_footer = SIZE - 110
    draw.line([(PADDING, y_footer - 20), (SIZE - PADDING, y_footer - 20)],
              fill=(151, 197, 161, 30), width=1)

    footer_text = "nura-ai.ru · Матрица Судьбы · AI-самопознание"
    fb = draw.textbbox((0, 0), footer_text, font=font_url)
    fw = fb[2] - fb[0]
    draw.text(((SIZE - fw) // 2, y_footer),
              footer_text, font=font_url,
              fill=INK_DIM_COLOR[:3] + (100,))

    # ── Конвертация в bytes ──
    output = io.BytesIO()
    img.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output.read()
