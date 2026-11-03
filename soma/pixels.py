"""Pixel art for the world's widget: the inhabitant's scene and figure on a grid of big, crisp pixels.

Her owner chose pixel art: moody, cinematic scenes with a small palette, skies
in colour bands and small living details (falling snow, passing birds,
lamplight). So:

* every world she shows (a scene a brain painted as SVG, a selfie from the
  GPU) is reduced to the grid by area
  averaging and a small palette without dithering. Gradients fall into bands,
  as hand-made pixel art paints them;
* her figure is a person with human proportions (about seven heads tall),
  built pixel by pixel from her own build, hair, skin, clothes and colours,
  posed by a small skeleton (shoulder and elbow angles, lean, head, sitting or
  seen from behind), lit from the left, shaded on the right and outlined as
  pixel art draws people. Seen whole in the wide view, as a portrait (head
  and shoulders) in the small one;
* small ambient life moves over her world (stars, snow, rain, fireflies,
  petals, dust, birds), and emote balloons show what is inside her.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

SCENE_COLORS = 20
PICTURE_COLORS = 40  # a painting keeps its richness, as hand-made pixel scenes do
SUPERSAMPLE = 4
INK_DARK, INK_LIGHT = QColor("#1d1626"), QColor("#f8f5ff")

# Pixel patterns ('.' is see-through): k ink, r red, g/G leaf, t tear blue.
ICONS ={"?": ["kk.", "..k", ".k.", "...", ".k."], "!": ["r", "r", "r", ".", "r"],
         "note": ["..kk", "..k.", "..k.", "kkk.", "kk.."], "heart": [".r.r.", "rrrrr", "rrrrr", ".rrr.", "..r.."]}
LETTER_Z = ["kkk", ".k.", "kkk"]
BIRD = (["k.k", ".k."], ["kkk"])  # wings up, wings level
LEAF = ["..gg", ".ggG", "G..."]
DROP = [".t", "tt", "tt"]


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def luma(color: QColor) -> float:
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def noise(index: int, salt: int) -> float:
    """A fixed pseudo-random number in 0..1: the same particle is in the same place every frame."""
    value = (index * 374761393 + salt * 668265263) & 0xFFFFFFFF
    value = ((value ^ (value >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((value ^ (value >> 16)) & 0xFFFF) / 0xFFFF


# ---------------------------------------------------------------- worlds to pixels

def cover(width: float, height: float, target_w: float, target_h: float, anchor_y=0.5) -> QRectF:
    """Where to draw a width×height image so that it covers the target, keeping its proportions."""
    scale = max(target_w / max(width, 1e-6), target_h / max(height, 1e-6))
    w, h = width * scale, height * scale
    return QRectF((target_w - w) / 2, (target_h - h) * anchor_y, w, h)


def quantize(image: QImage, colors: int) -> QImage:
    """A palette of `colors` by median cut, without dithering: gradients become bands."""
    from PIL import Image
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height, line = rgba.width(), rgba.height(), rgba.bytesPerLine()
    data = bytes(rgba.constBits())[:line * height]
    picture = Image.frombuffer("RGBA", (width, height), data, "raw", "RGBA", line, 1).convert("RGB")
    reduced = picture.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw = reduced.convert("RGB").tobytes()
    return QImage(raw, width, height, width * 3, QImage.Format.Format_RGB888).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied)


def _reduce(canvas: QImage, width: int, height: int, colors: int) -> QImage:
    small = canvas.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)  # area average
    return quantize(small, colors)


def scene_pixels(renderer, width: int, height: int, colors=SCENE_COLORS) -> QImage:
    """A painted SVG world as a width×height pixel image."""
    canvas = QImage(width * SUPERSAMPLE, height * SUPERSAMPLE, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor("#000000"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = renderer.viewBoxF()
    renderer.render(painter, cover(box.width(), box.height(), canvas.width(), canvas.height(), 0.62))
    painter.end()
    return _reduce(canvas, width, height, colors)


def picture_pixels(picture: QImage, width: int, height: int, colors=PICTURE_COLORS) -> QImage:
    """A painting of her (her selfie from the GPU) as a width×height pixel image."""
    canvas = QImage(width * SUPERSAMPLE, height * SUPERSAMPLE, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor("#000000"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(cover(picture.width(), picture.height(), canvas.width(), canvas.height(), 0.5), picture)
    painter.end()
    return _reduce(canvas, width, height, colors)


def bands(top: QColor, bottom: QColor, width: int, height: int, count=6) -> QImage:
    """A sky of colour bands, for a world not painted yet."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    for index in range(count):
        y0, y1 = round(index * height / count), round((index + 1) * height / count)
        painter.fillRect(0, y0, width, y1 - y0, mix(top, bottom, index / max(1, count - 1)))
    painter.end()
    return image


# ---------------------------------------------------------------- her figure: a person

# Build: width and height factors.
BUILDS = {"slim": (0.88, 1.0), "average": (1.0, 1.0), "sturdy": (1.22, 0.98), "petite": (0.95, 0.88),
          "tall": (0.94, 1.08)}
SHOES = QColor("#2a2230")
OUTLINE = QColor(20, 14, 28, 235)


@dataclass(frozen=True)
class Figure:
    """Who she is to look at: her own choices."""
    build: str = "average"
    hair: str = "hood"
    hair_color: str = "#3b2f4a"
    skin: str = "#e0b89a"
    outfit: str = "hoodie"
    body: str = "#9d93c9"
    legs: str = "#46445e"
    glow: str = "#e4e1f7"
    accent: str = "none"


@dataclass(frozen=True)
class Pose:
    """How she stands now: body language from what she does and feels.

    Arms are (shoulder angle, elbow bend) in degrees: 0 hangs straight down,
    positive turns outward and up, a negative bend folds the forearm inward."""
    facing: str = "front"          # front | back (looking into her world)
    sit: bool = False
    lean: int = 0
    head: tuple = (0, 0)           # head offset: dx, dy (dy 1 = bowed, -1 = looking up)
    left: tuple = (5, 0)           # the arm on the screen's left
    right: tuple = (5, 0)
    stance: int = 3                # legs apart, degrees
    hold: str = ""                 # "book"
    breath: int = 0                # 1: chest risen
    eyes: str = "open"             # open | wide | half | down | closed | happy
    mouth: str = "none"            # smile | small | open | frown | none
    gaze: int = 0                  # -1 | 0 | 1
    blush: bool = False


def _limb(painter, x0, y0, x1, y1, width, color):
    """A thick pixel line: squares stepped along it, no smoothing."""
    steps = max(1, round(max(abs(x1 - x0), abs(y1 - y0))))
    for i in range(steps + 1):
        x = round(x0 + (x1 - x0) * i / steps)
        y = round(y0 + (y1 - y0) * i / steps)
        painter.fillRect(x, y, width, width, color)


def _finish(image: QImage) -> QImage:
    """Pixel-art light and line: a shadow column on the right of every form, a
    lit column on the left, and a dark outline around her silhouette."""
    import numpy as np
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height, line = rgba.width(), rgba.height(), rgba.bytesPerLine()
    pixels_ = np.frombuffer(bytes(rgba.constBits())[:line * height], np.uint8).reshape(height, line)
    a = pixels_[:, :width * 4].reshape(height, width, 4).astype(np.float32)
    solid = a[..., 3] > 0
    pad = np.pad(solid, 1)
    open_right, open_left = ~pad[1:-1, 2:], ~pad[1:-1, :-2]
    shade = solid & open_right
    lit = solid & open_left & ~open_right
    a[shade, :3] *= 0.78
    a[lit, :3] = np.minimum(255, a[lit, :3] * 1.1 + 8)
    near = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    a[~solid & near] = (OUTLINE.red(), OUTLINE.green(), OUTLINE.blue(), OUTLINE.alpha())
    raw = a.astype(np.uint8).tobytes()
    return QImage(raw, width, height, width * 4, QImage.Format.Format_RGBA8888).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied)


@lru_cache(maxsize=192)
def person(figure: Figure, pose: Pose, height: int):
    """Her figure, about `height` pixels tall: (image, feet (x, y), head (x, top, width, rows))."""
    widen, taller = BUILDS.get(figure.build, BUILDS["average"])
    tall = max(16, round(height * taller))
    width_px, height_px = tall + 12, tall + 12
    image = QImage(width_px, height_px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    cx, feet = width_px // 2, height_px - 2
    hh = max(4, round(tall * 0.155))                # head rows: about seven heads tall
    hw = max(4, hh - 1)                             # head width
    sw = max(5, round(tall * 0.24 * widen))         # shoulders
    hip_w = max(4, sw - 2)
    th = max(5, round(tall * 0.315))                # torso; the legs take the rest, about half
    leg_len = tall - hh - 1 - th
    lt = max(2, round(tall * 0.06 * widen))         # leg thickness
    at = 2 if tall >= 26 else 1                     # arm thickness
    upper = fore = max(3, round(tall * 0.17))
    hip_y = feet - 3 if pose.sit else feet - leg_len
    sh_y = hip_y - th - pose.breath
    lean = pose.lean
    ht = sh_y - hh + pose.head[1]                    # head top
    hx = cx - hw // 2 + lean + pose.head[0]
    back = pose.facing == "back"
    top, skin, hair = QColor(figure.body), QColor(figure.skin), QColor(figure.hair_color)
    legs, glow = QColor(figure.legs), QColor(figure.glow)
    sleeve = top.darker(118)
    torso_x = cx - sw // 2 + lean

    # Long hair falls behind her shoulders.
    if figure.hair in {"long", "curly"} and not back:
        painter.fillRect(hx - 1, ht + 1, hw + 2, sh_y - ht + round(th * (0.45 if figure.hair == "long" else 0.15)), hair)
    # Legs: standing apart, or crossed on the ground.
    if pose.sit:
        for row in range(4):
            span = hip_w + 2 + row
            painter.fillRect(cx - span // 2, hip_y + row - 1, span, 1, legs)
        painter.fillRect(cx - (hip_w + 6) // 2, feet - 1, 2, 2, SHOES)
        painter.fillRect(cx + (hip_w + 6) // 2 - 1, feet - 1, 2, 2, SHOES)
    else:
        hips = cx - hip_w // 2
        for side in (-1, 1):
            start = hips if side < 0 else hips + hip_w - lt
            slope = math.tan(math.radians(pose.stance)) * side
            for y in range(hip_y, feet + 1):
                x = start + round(slope * (y - hip_y))
                shoe = y >= feet - 1
                painter.fillRect(x - (1 if shoe and side < 0 else 0), y, lt + (1 if shoe else 0), 1,
                                 SHOES if shoe else legs)
    # Clothes below the waist.
    if figure.outfit in {"coat", "dress"}:
        length = round(leg_len * (0.42 if figure.outfit == "coat" else 0.48))
        if pose.sit:
            length = 2
        for row in range(length):
            span = hip_w + (1 if figure.outfit == "coat" else 1 + round(4 * row / max(1, length)))
            painter.fillRect(cx - span // 2, hip_y + row, span, 1, top if figure.outfit == "dress" else top.darker(108))
        if figure.outfit == "coat":
            painter.fillRect(cx, hip_y, 1, length, top.darker(140))
    # Torso, narrowing from shoulders to hips; leaning shifts the shoulders.
    for y in range(sh_y, hip_y + 1):
        f = (y - sh_y) / max(1, hip_y - sh_y)
        span = round(sw + (hip_w - sw) * f)
        painter.fillRect(cx - span // 2 + round(lean * (1 - f)), y, span, 1, top)
    if not back:
        if figure.outfit == "hoodie":
            painter.fillRect(cx - (hip_w - 3) // 2, hip_y - max(2, th // 4), max(2, hip_w - 3), 2, top.darker(115))
            painter.fillRect(cx - 1 + lean, sh_y + 1, 1, 2, top.lighter(150))
            painter.fillRect(cx + 1 + lean, sh_y + 1, 1, 2, top.lighter(150))
        elif figure.outfit == "jacket":
            painter.fillRect(cx - 1 + lean, sh_y + 1, 2, th - 1, QColor("#e7e5ef"))
        elif figure.outfit == "coat":
            for y in range(sh_y + 2, hip_y, 3):
                painter.fillRect(cx + lean, y, 1, 1, top.darker(150))
        elif figure.outfit == "sweater":
            painter.fillRect(cx - hip_w // 2, hip_y, hip_w, 1, top.darker(120))
    if figure.outfit == "hoodie":
        painter.fillRect(hx - 1, sh_y - 1, hw + 2, 1, top.darker(112))   # the hood at her neck
    if figure.accent == "backpack":
        if back:
            painter.fillRect(torso_x + 1, sh_y + 2, sw - 2, max(3, round(th * 0.6)), glow.darker(125))
            painter.fillRect(torso_x + 1, sh_y + 2, sw - 2, 1, glow.darker(160))
        else:
            for x in (torso_x + 1, torso_x + sw - 2):
                painter.fillRect(x, sh_y, 1, max(3, round(th * 0.6)), glow.darker(150))
    # Arms: from the shoulders, by their angles.
    hands = []
    for side, (shoulder, bend) in ((-1, pose.left), (1, pose.right)):
        sx = torso_x - 1 if side < 0 else torso_x + sw - 1
        sy = sh_y + 1
        a1, a2 = math.radians(shoulder), math.radians(shoulder + bend)
        ex, ey = sx + side * math.sin(a1) * upper, sy + math.cos(a1) * upper
        hand_x, hand_y = ex + side * math.sin(a2) * fore, ey + math.cos(a2) * fore
        _limb(painter, sx, sy, ex, ey, at, sleeve)
        _limb(painter, ex, ey, hand_x, hand_y, at, skin if figure.outfit in {"tshirt", "dress"} else sleeve)
        painter.fillRect(round(hand_x), round(hand_y), at, at, skin)
        hands.append((round(hand_x), round(hand_y)))
    if pose.hold == "book":
        bx = cx - 3 + lean
        by = min(y for _, y in hands) - 1
        painter.fillRect(bx, by, 7, 5, glow.darker(135))
        painter.fillRect(bx, by, 7, 1, QColor("#f5f0e6"))
        painter.fillRect(bx + 3, by, 1, 5, glow.darker(175))
    # Neck and head.
    painter.fillRect(cx - 1 + lean + pose.head[0], ht + hh, 2, max(0, sh_y - ht - hh), skin.darker(112))
    painter.fillRect(hx, ht, hw, hh, hair if back else skin)
    if not back:  # a jaw: the lower corners of the head cut away
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(hx, ht + hh - 1, 1, 1, QColor(0, 0, 0, 0))
        painter.fillRect(hx + hw - 1, ht + hh - 1, 1, 1, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    _hair(painter, figure, pose, hx, ht, hw, hh, sh_y, th, hair, top, back)
    if not back:
        _face(painter, figure, pose, hx, ht, hw, hh, skin)
    _headwear(painter, figure, hx, ht, hw, hh, sh_y, glow, back)
    painter.end()
    return _finish(image), (cx, feet), (hx, ht - (2 if figure.hair in {"bun", "hood"} else 1), hw, hh)


def _hair(painter, figure, pose, hx, ht, hw, hh, sh_y, th, hair, top, back):
    style = figure.hair
    if style == "hood":
        hood = top.darker(108)
        painter.fillRect(hx + 1, ht - 2, hw - 2, 1, hood)
        painter.fillRect(hx, ht - 1, hw, 1, hood)
        painter.fillRect(hx - 1, ht, hw + 2, 1, hood)
        painter.fillRect(hx - 1, ht, 1, hh + 1, hood)
        painter.fillRect(hx + hw, ht, 1, hh + 1, hood)
        if back:
            painter.fillRect(hx, ht, hw, hh + 1, hood)
            painter.fillRect(hx + hw // 2, ht + 1, 1, hh - 1, hood.darker(118))   # the hood's seam
        else:
            painter.fillRect(hx + 1, ht + 1, hw - 2, 1, hair)                     # a fringe under the hood
        return
    if style == "buzz":
        painter.fillRect(hx, ht, hw, 1 if not back else max(2, hh // 2), hair)
        return
    painter.fillRect(hx + 1, ht - 1, hw - 2, 1, hair)                             # the crown
    painter.fillRect(hx, ht, hw, 1, hair)
    if back:
        painter.fillRect(hx, ht, hw, hh, hair)
    else:
        painter.fillRect(hx, ht + 1, hw, 1, hair)                                  # fringe
        painter.fillRect(hx, ht + 1, 1, 2, hair)
        painter.fillRect(hx + hw - 1, ht + 1, 1, 2, hair)
    painter.fillRect(hx + 1, ht, 1, 1, hair.lighter(130))                          # a sheen
    if style in {"bob", "long", "curly"}:
        down = hh if style == "bob" else (sh_y - ht + round(th * (0.45 if style == "long" else 0.15)))
        painter.fillRect(hx - 1, ht, 1, down, hair)
        painter.fillRect(hx + hw, ht, 1, down, hair)
        if back:
            painter.fillRect(hx - 1, ht, hw + 2, down, hair)
        if style == "curly":
            for dy in range(1, down, 2):
                painter.fillRect(hx - 2, ht + dy, 1, 1, hair)
                painter.fillRect(hx + hw + 1, ht + dy, 1, 1, hair)
            for dx in range(0, hw, 2):
                painter.fillRect(hx + dx, ht - 2, 1, 1, hair)
    elif style == "ponytail":
        tail_x = hx + hw // 2 if back else hx + hw
        painter.fillRect(tail_x, ht + 1, 2, hh - 1, hair)
        painter.fillRect(tail_x + (0 if back else 1), ht + hh, 1, 2, hair)
    elif style == "bun":
        painter.fillRect(hx + hw // 2 - 1, ht - 3, 3, 2, hair)


def _face(painter, figure, pose, hx, ht, hw, hh, skin):
    ink, lid = INK_DARK, skin.darker(150)
    centre = hx + hw // 2
    offset = max(1, round(hw * 0.28))
    ey = ht + (round(hh * 0.45) if hh >= 8 else max(2, round(hh * 0.5)))
    tall_eyes = hh >= 8
    for x in (centre - offset + pose.gaze, centre + offset + pose.gaze):
        if figure.accent == "glasses":
            painter.fillRect(x - 1, ey - 1, 3, 1, ink)
        if pose.eyes in {"closed", "happy"}:
            painter.fillRect(x, ey + (1 if tall_eyes else 0), 1, 1, lid)
        elif pose.eyes in {"half", "down"}:
            painter.fillRect(x, ey, 1, 1, lid)
            if tall_eyes:
                painter.fillRect(x, ey + 1, 1, 1, ink)
        else:
            painter.fillRect(x, ey, 1, 2 if tall_eyes else 1, QColor("#dbeafe") if figure.accent == "glasses" and not tall_eyes else ink)
            if tall_eyes and pose.eyes == "wide":
                painter.fillRect(x, ey - 1, 1, 1, ink)
        if pose.blush or figure.accent == "blush":
            painter.fillRect(x + (-1 if x < centre else 1), ey + (2 if tall_eyes else 1), 1, 1, mix(skin, QColor("#fb7185"), 0.55))
        if figure.accent == "freckles":
            painter.fillRect(x, ey + (2 if tall_eyes else 1) + (1 if tall_eyes else 0), 1, 1, skin.darker(130))
    my = min(ht + hh - 1, ey + (3 if tall_eyes else 2))
    mouth = QColor("#7a3340")
    if pose.mouth == "smile":
        if tall_eyes:
            painter.fillRect(centre - 1, my, 3, 1, mouth)
            painter.fillRect(centre - 2, my - 1, 1, 1, mouth)
            painter.fillRect(centre + 2, my - 1, 1, 1, mouth)
        else:
            painter.fillRect(centre - (1 if hw % 2 == 0 else 0), my, 2 if hw % 2 == 0 else 1, 1, mouth)
    elif pose.mouth == "open":
        painter.fillRect(centre, my - (1 if tall_eyes else 0), 1, 2 if tall_eyes else 1, QColor("#3b1d2a"))
    elif pose.mouth == "frown":
        if tall_eyes:
            painter.fillRect(centre - 1, my - 1, 3, 1, mouth)
            painter.fillRect(centre - 2, my, 1, 1, mouth)
            painter.fillRect(centre + 2, my, 1, 1, mouth)
        else:
            painter.fillRect(centre, my, 1, 1, skin.darker(140))
    elif pose.mouth == "small":
        painter.fillRect(centre, my, 1, 1, skin.darker(140))


def _headwear(painter, figure, hx, ht, hw, hh, sh_y, glow, back):
    accent = figure.accent
    if accent == "beanie":
        painter.fillRect(hx + 1, ht - 2, hw - 2, 1, glow)
        painter.fillRect(hx - 1, ht - 1, hw + 2, 1, glow)
        painter.fillRect(hx - 1, ht, hw + 2, 1, glow.darker(125))
    elif accent == "headphones":
        painter.fillRect(hx, ht - 2, hw, 1, QColor("#27272a"))
        painter.fillRect(hx - 1, ht - 1, 1, 1, QColor("#27272a"))
        painter.fillRect(hx + hw, ht - 1, 1, 1, QColor("#27272a"))
        painter.fillRect(hx - 2, ht + hh // 2 - 1, 2, 3, glow)
        painter.fillRect(hx + hw, ht + hh // 2 - 1, 2, 3, glow)
    elif accent == "scarf":
        painter.fillRect(hx - 2, sh_y, hw + 4, 2, glow)
        painter.fillRect(hx + (0 if back else hw - 1), sh_y + 2, 2, 3, glow.darker(112))


def draw(painter: QPainter, rows, x: int, y: int, colors: dict, flip=False):
    """One pixel pattern at x, y (its top left)."""
    for dy, row in enumerate(rows):
        for dx, key in enumerate(reversed(row) if flip else row):
            if key != ".":
                painter.fillRect(x + dx, y + dy, 1, 1, colors[key])


def centred(painter: QPainter, rows, cx: int, cy: int, colors: dict, flip=False):
    if rows:
        draw(painter, rows, cx - len(rows[0]) // 2, cy - len(rows) // 2, colors, flip)


def balloon(painter: QPainter, icon, x: int, y: int, colors: dict) -> tuple[int, int]:
    """An emote balloon around a pixel icon, with its tail at the lower left; returns its size."""
    width, height = len(icon[0]) + 4, len(icon) + 4
    edge, fill = colors["k"], QColor("#fffdf6")
    painter.fillRect(x + 1, y + 1, width - 2, height - 2, fill)
    painter.fillRect(x + 2, y, width - 4, 1, edge)
    painter.fillRect(x + 2, y + height - 1, width - 4, 1, edge)
    painter.fillRect(x, y + 2, 1, height - 4, edge)
    painter.fillRect(x + width - 1, y + 2, 1, height - 4, edge)
    for cx, cy in ((x + 1, y + 1), (x + width - 2, y + 1), (x + 1, y + height - 2), (x + width - 2, y + height - 2)):
        painter.fillRect(cx, cy, 1, 1, edge)
    painter.fillRect(x + 2, y + height - 1, 1, 1, fill)   # the tail leaves the balloon here…
    painter.fillRect(x + 1, y + height, 1, 1, edge)        # …and points down to her
    painter.fillRect(x + 2, y + height, 1, 1, edge)
    painter.fillRect(x, y + height + 1, 1, 1, edge)
    draw(painter, icon, x + 2, y + 2, colors)
    return width, height


# ---------------------------------------------------------------- ambient life

def ambient(painter: QPainter, kind: str, t: float, width: int, height: int):
    """Small life over her world; every particle has its own fixed path."""
    area = width * height
    if kind == "stars":
        for i in range(max(8, area // 120)):
            x, y = int(noise(i, 1) * width), int(noise(i, 2) * height * 0.6)
            shine = math.sin(t * (0.8 + 2.2 * noise(i, 3)) + 6.3 * noise(i, 4))
            if shine > 0.55:
                painter.fillRect(x, y, 1, 1, QColor("#ffffff"))
                if i % 11 == 0 and shine > 0.9:  # a bright one glints in a cross
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        painter.fillRect(x + dx, y + dy, 1, 1, QColor(254, 240, 138, 190))
            elif shine > -0.3:
                painter.fillRect(x, y, 1, 1, QColor(199, 210, 254, 150))
    elif kind in {"snow", "petals"}:
        count = area // (40 if kind == "snow" else 110)
        for i in range(count):
            near = noise(i, 3) > 0.6
            speed = (5 if kind == "snow" else 3.5) * (1.8 if near else 1) * (0.7 + 0.6 * noise(i, 4))
            drift = 0.6 * t if kind == "snow" else 2.2 * t
            x = int(noise(i, 1) * width + drift + 1.6 * math.sin(t * 0.9 + 6 * noise(i, 5))) % width
            y = int(noise(i, 2) * height + t * speed) % height
            if kind == "snow":
                color = QColor("#ffffff") if near else QColor(203, 213, 225, 200)
            else:
                color = QColor("#f9a8d4") if near else QColor(251, 207, 232, 210)
            painter.fillRect(x, y, 1, 1, color)
    elif kind == "rain":
        for i in range(area // 110):
            speed = 45 + 25 * noise(i, 3)
            x = int(noise(i, 1) * width - t * speed * 0.2) % width
            y = int(noise(i, 2) * height + t * speed) % height
            near = noise(i, 4) > 0.6
            painter.fillRect(x, y, 1, 3 if near else 2, QColor(165, 210, 255, 130 if near else 80))
    elif kind == "fireflies":
        for i in range(max(5, area // 260)):
            speed = 0.5 + noise(i, 3)
            x = int(noise(i, 1) * width + 4 * math.sin(t * 0.45 * speed + 6 * noise(i, 4)))
            y = int(height * (0.35 + 0.55 * noise(i, 2)) + 3 * math.cos(t * 0.35 * speed + 6 * noise(i, 5)))
            glow = math.sin(t * 1.6 * speed + 6 * noise(i, 6))
            if glow > 0.1:
                painter.fillRect(x, y, 1, 1, QColor("#fef08a") if glow > 0.6 else QColor(190, 242, 100, 200))
    elif kind == "dust":
        for i in range(max(6, area // 150)):
            x = int(noise(i, 1) * width + 2 * math.sin(t * 0.3 + 6 * noise(i, 3))) % width
            y = int(noise(i, 2) * height - t * (0.6 + noise(i, 4))) % height
            painter.fillRect(x, y, 1, 1, QColor(254, 243, 199, 120))
    elif kind == "birds":
        colors = {"k": QColor(30, 27, 46, 220)}
        for i in range(3):
            x = int(noise(i, 1) * width - t * (4 + 2 * i)) % (width + 12) - 6
            y = int(2 + noise(i, 2) * height * 0.3 + math.sin(t * 0.8 + i))
            draw(painter, BIRD[int(t * 3 + i) % 2], x, y, colors)
