"""Her living avatar in pixel art: her world behind, her in it, life over both.

Everything is painted on a coarse grid (one art pixel = 2 logical pixels, a
whole number of screen pixels) and scaled up without smoothing, so every pixel
stays crisp at any Windows scale. Her world is a painted scene, a picture of
her own or a selfie, reduced to a small palette (see soma.pixels). She is a
person with human proportions, dressed as she chose. Her body speaks: seen
from behind looking up into her sky when dreamy, a hand to her chin while
thinking, a book while learning, reaching towards where her hand acts, arms
up in a hop of joy, hands on hips when proud, head bowed when sad, sitting
while she rests. She breathes, blinks and looks around; a new feeling pops in
on a spring. Emote balloons say what is inside (… while thinking, ? ! ♪ ♥
for feelings, z while asleep), and small ambient life moves over her world.
The frame takes the colour of what she is doing. Opaque: it is part of the
screen she reads, so nothing shows through it.
"""

from __future__ import annotations

import base64
import math
import time

from PySide6.QtCore import QByteArray, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from soma import pixels
from soma.appearance import PLACEHOLDER, ambient_of, expression

ACTIVITY_COLORS = {"thinking": "#7c5cff", "acting": "#16a34a", "resting": "#3b82f6", "learning": "#e11d48",
                   "asleep": "#94a3b8", "recovering": "#f59e0b", "waking": "#a78bfa"}
BOUNCY = {"joyful", "excited", "playful", "grateful"}
EMOTES = {"curious": "?", "confused": "?", "excited": "!", "proud": "!", "joyful": "note", "playful": "note",
          "grateful": "heart"}
BLUSHING = {"joyful", "grateful", "playful", "proud"}
# Her chosen face, in the few pixels a person's face has here.
EYE_STYLES = {"dots": "open", "round": "open", "wide": "wide", "bright": "happy", "sleepy": "half", "closed": "closed"}
MOUTH_STYLES = {"smile": "smile", "smirk": "smile", "small": "small", "open": "open", "frown": "frown",
                "wavy": "small", "none": "none"}


def pose_for(look: dict, activity: str, face: dict, t: float, gaze: tuple, hopping: bool) -> pixels.Pose:
    """Body language: what she does first, then what she feels, then rest or simply standing."""
    feeling = look.get("feeling", "")
    breath = 1 if math.sin(2 * math.pi * t * face["breaths_per_minute"] / 60) > 0.3 else 0
    period = 3.1 if activity == "thinking" else 4.3
    eyes = EYE_STYLES.get(face["eyes"], "open")
    if (t % period) > period - 0.14 and eyes in {"open", "wide", "half"}:
        eyes = "closed"  # a blink
    look_x = max(-1, min(1, round(gaze[0] * 1.2)))
    common = {"breath": breath, "eyes": eyes, "mouth": MOUTH_STYLES.get(face["mouth"], "none"), "gaze": look_x,
              "blush": feeling in BLUSHING}
    if activity == "asleep":
        return pixels.Pose(sit=True, head=(0, 1), left=(15, -40), right=(15, -40), breath=breath, eyes="closed")
    if activity == "thinking":
        return pixels.Pose(**common, right=(-35, -145), left=(10, -90))            # a hand to her chin
    if activity == "learning":
        return pixels.Pose(**{**common, "eyes": "down"}, head=(0, 1), left=(5, -100), right=(5, -100), hold="book")
    if activity == "acting":
        reach = (70, 10)                                                            # towards where she acts
        return pixels.Pose(**common, left=reach if look_x < 0 else (5, 0), right=reach if look_x >= 0 else (5, 0))
    if activity == "recovering":
        return pixels.Pose(**common, right=(160, 125))                              # a hand on her head
    if activity == "waking" and t % 6 < 2.5:
        return pixels.Pose(**{**common, "eyes": "closed"}, left=(170, 5), right=(170, 5))   # a stretch
    if feeling in {"dreamy", "lonely"} or look.get("placeholder"):
        # Seen from behind, looking into her world — up at its sky when dreaming.
        return pixels.Pose(facing="back", head=(0, -1 if feeling != "lonely" else 1), left=(3, -10), right=(3, -10),
                           breath=breath)
    if feeling in {"joyful", "excited"}:
        arms = (150, 10) if hopping else (25, 20)
        return pixels.Pose(**common, left=arms, right=arms)
    if feeling == "playful":
        return pixels.Pose(**common, right=(135, 35 if int(t * 4) % 2 else 5))     # a wave
    if feeling == "proud":
        return pixels.Pose(**common, left=(35, -95), right=(35, -95))               # hands on hips
    if feeling == "anxious":
        return pixels.Pose(**common, left=(-10, -135), right=(-10, -135), lean=int(t * 10) % 2)
    if feeling == "confused":
        return pixels.Pose(**common, right=(160, 125))                              # scratching her head
    if feeling == "grateful":
        return pixels.Pose(**common, right=(0, -150))                               # a hand on her heart
    if feeling in {"sad", "tired"}:
        return pixels.Pose(**{**common, "eyes": "down" if feeling == "sad" else eyes}, head=(0, 1),
                           left=(2, 0), right=(2, 0), sit=feeling == "tired")
    if feeling == "curious":
        return pixels.Pose(**common, head=(look_x, 0), lean=look_x, left=(10, -90), right=(-35, -145))
    if feeling == "focused":
        return pixels.Pose(**common, left=(20, -70), right=(20, -70))
    if activity == "resting":
        return pixels.Pose(**common, sit=True, left=(15, -40), right=(15, -40))     # sitting, hands in her lap
    return pixels.Pose(**common, left=(3, -10), right=(3, -10))                     # standing, hands in pockets


def figure_of(look: dict) -> pixels.Figure:
    defaults = pixels.Figure()
    values = {name: look.get(name) or getattr(defaults, name) for name in
              ("build", "hair", "hair_color", "skin", "outfit", "body", "legs", "glow", "accent")}
    return pixels.Figure(**values)


class Spring:
    """A damped spring: values that move like things in the world, with a little overshoot."""

    def __init__(self, value=0.0, stiffness=140.0, damping=14.0):
        self.value, self.velocity, self.target = value, 0.0, value
        self.stiffness, self.damping = stiffness, damping

    def step(self, dt: float) -> float:
        for _ in range(max(1, int(dt / 0.008))):  # small steps keep it stable
            h = min(dt, 0.008)
            force = -self.stiffness * (self.value - self.target) - self.damping * self.velocity
            self.velocity += force * h
            self.value += self.velocity * h
        return self.value

    def kick(self, impulse: float):
        self.velocity += impulse


class AvatarView(QWidget):
    def __init__(self, parent=None, size=64, height=None):
        super().__init__(parent)
        self.setFixedSize(size, height or size)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.look = dict(PLACEHOLDER, placeholder=True)
        self.activity, self.focus = "waking", None
        self._scene_svg, self._scene = None, None
        self._picture_data, self._picture = None, None
        self._world_key, self._world = None, None
        self._frame_key, self._frame = None, None
        self._started = self._last = time.monotonic()
        # Springs: gaze (x, y), pop (size), bounce (a hop), activity colour blend.
        self._gaze = (Spring(0, 180, 13), Spring(0, 180, 13))
        self._pop, self._bounce = Spring(1.0, 220, 11), Spring(0.0, 260, 9)
        self._tint_from, self._tint_to, self._tint = QColor("#a78bfa"), QColor("#a78bfa"), Spring(1.0, 70, 13)
        self._next_hop = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 frames per second while visible

    # ------------------------------------------------------------------ state

    def set_size(self, width: int, height: int | None = None):
        self.setFixedSize(width, height or width)
        self._pop.value = 0.86  # springs back to full size
        self._pop.target = 1.0

    def set_look(self, look: dict):
        previous = self.look.get("feeling")
        self.look = look or dict(PLACEHOLDER, placeholder=True)
        if self.look.get("feeling") != previous:
            self._pop.kick(2.2)  # a new feeling shows with a little spring
        svg = self.look.get("scene_svg") if self.look.get("scene_theme") == self.look.get("theme") else None
        if svg != self._scene_svg:
            self._scene_svg = svg
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8"))) if svg else None
            self._scene = renderer if renderer is not None and renderer.isValid() else None
        if self.look.get("style") == "picture":
            data = self.look.get("picture")
        else:  # the painting of her in her world, while it is of the world she lives in now
            data = self.look.get("selfie") if self.look.get("selfie_theme") == self.look.get("theme") else None
        if data != self._picture_data:
            self._picture_data, self._picture = data, None
            if data:
                image = QImage()
                if image.loadFromData(base64.b64decode(data)):  # PNG pictures, JPEG paintings
                    self._picture = image
        self.update()

    def set_activity(self, activity: str, focus=None):
        activity = activity or "waking"
        if activity != self.activity:
            self._tint_from = self._current_tint()
            self._tint_to = QColor(ACTIVITY_COLORS.get(activity, "#a78bfa"))
            self._tint.value, self._tint.target = 0.0, 1.0
            self._pop.kick(1.4)
        self.activity, self.focus = activity, focus

    def _current_tint(self) -> QColor:
        return pixels.mix(self._tint_from, self._tint_to, self._tint.value)

    def _shows_picture(self) -> bool:
        return self._picture is not None

    # ------------------------------------------------------------------ motion

    def _tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        face = expression(self.look, self.activity)
        gx, gy = self._gaze_target(face, now - self._started)
        self._gaze[0].target, self._gaze[1].target = gx, gy
        for spring in (*self._gaze, self._pop, self._bounce, self._tint):
            spring.step(dt)
        if self.look.get("feeling") in BOUNCY and self.activity != "asleep" and now >= self._next_hop:
            self._bounce.kick(-3.2)  # a little hop of joy
            self._next_hop = now + (1.6 if self.look.get("feeling") == "excited" else 3.4)
        self.update()

    def _gaze_target(self, face: dict, t: float):
        """Toward her hand's target while acting, else where her mood takes her eyes."""
        if self.activity == "acting" and self.focus and self.isVisible():
            screen = self.screen().virtualGeometry() if self.screen() else None
            if screen is not None and screen.width() and screen.height():
                centre = self.mapToGlobal(self.rect().center())
                dx = self.focus[0] - (centre.x() - screen.x()) / screen.width()
                dy = self.focus[1] - (centre.y() - screen.y()) / screen.height()
                length = math.hypot(dx, dy) or 1
                return dx / length, dy / length
        bias_x, bias_y = face["gaze"]
        if self.activity == "thinking":
            bias_x, bias_y = bias_x - 0.35, bias_y - 0.6
        # Saccades: the eyes rest, then jump to a new spot every few seconds.
        slot = int(t / 2.7)
        return (bias_x + 0.35 * math.sin(slot * 2.39), bias_y + 0.2 * math.sin(slot * 1.71))

    # ------------------------------------------------------------------ painting

    def grid(self) -> tuple[int, int, int]:
        """Screen pixels per art pixel, and the grid's width and height in art pixels."""
        ratio = self.devicePixelRatioF()
        pixel = max(2, round(1.5 * ratio))  # 2 screen pixels at 100–150 %: 228 art pixels across at 150 %
        return pixel, max(12, int(self.width() * ratio) // pixel), max(12, int(self.height() * ratio) // pixel)

    def paintEvent(self, event):
        pixel, width, height = self.grid()
        image = self.compose(width, height, time.monotonic() - self._started)
        painter = QPainter(self)
        ratio = self.devicePixelRatioF()
        painter.scale(1 / ratio, 1 / ratio)  # screen pixels: every art pixel the same whole size
        left = (int(self.width() * ratio) - width * pixel) // 2
        top = (int(self.height() * ratio) - height * pixel) // 2
        painter.drawImage(QRect(left, top, width * pixel, height * pixel), image)  # no smoothing
        painter.end()

    def compose(self, width: int, height: int, t: float) -> QImage:
        """One frame of her avatar on a width×height grid."""
        image = QImage(self._world_pixels(width, height))
        face = expression(self.look, self.activity)
        painter = QPainter(image)
        pixels.ambient(painter, ambient_of(self.look), t, width, height)
        if self._shows_picture():
            head = (width - 12, 9, 3)  # balloons from the top right corner of her picture
        else:
            head = self._paint_figure(painter, image, width, height, face, t)
        self._paint_emote(painter, head, face, t, width)
        mask, frame = self._frame_pixels(width, height)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, mask)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawImage(0, 0, frame)
        painter.end()
        return image

    def _world_pixels(self, width: int, height: int) -> QImage:
        if self._shows_picture():
            key = ("picture", id(self._picture), width, height)
        elif self._scene is not None:
            key = ("scene", self._scene_svg, width, height)
        else:
            key = ("bands", self.look.get("glow"), self.look.get("feeling"), width, height)
        if key != self._world_key:
            if key[0] == "picture":
                world = pixels.picture_pixels(self._picture, width, height)
            elif key[0] == "scene":
                world = pixels.scene_pixels(self._scene, width, height)
            else:
                glow = QColor(expression(self.look)["tint"] or self.look.get("glow") or "#c4b5fd")
                world = pixels.bands(glow.lighter(118), glow.darker(150), width, height)
            self._world_key, self._world = key, world
        return self._world

    def _frame_pixels(self, width: int, height: int):
        """Stepped round corners (a mask) and a one-pixel frame in her activity's colour."""
        tint = self._current_tint()
        key = (width, height, tint.rgb())
        if key != self._frame_key:
            mask = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            mask.fill(QColor(0, 0, 0, 255))
            frame = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            frame.fill(QColor(0, 0, 0, 0))
            for y in (0, 1, height - 2, height - 1):
                cut = 2 if y in (0, height - 1) else 1
                for x in list(range(cut)) + list(range(width - cut, width)):
                    mask.setPixelColor(x, y, QColor(0, 0, 0, 0))
            painter = QPainter(frame)
            painter.fillRect(2, 0, width - 4, 1, tint)
            painter.fillRect(2, height - 1, width - 4, 1, tint)
            painter.fillRect(0, 2, 1, height - 4, tint)
            painter.fillRect(width - 1, 2, 1, height - 4, tint)
            for x, y in ((1, 1), (width - 2, 1), (1, height - 2), (width - 2, height - 2)):
                painter.fillRect(x, y, 1, 1, tint)
            painter.end()
            self._frame_key, self._frame = key, (mask, frame)
        return self._frame

    def _paint_figure(self, painter, image, width, height, face, t):
        """Her, a person in her world: whole in the wide view, a portrait in the small
        one. Returns her head (left, top, width) for what floats over it."""
        look = self.look
        wide = width > height * 1.4
        hopping = self._bounce.value < -0.12
        pose = pose_for(look, self.activity, face, t, (self._gaze[0].value, self._gaze[1].value), hopping)
        tall = round(height * 0.58) if wide else round(height * 1.45)
        tall = max(16, round(tall * self._pop.value))
        sprite, (foot_x, foot_y), (hx, ht, hw, hh) = pixels.person(figure_of(look), pose, tall)
        hop = round(-self._bounce.value * tall * 0.05)
        if wide:
            ground = height - max(3, round(height * 0.07))
            x, y = width // 2 - foot_x, ground - foot_y - hop
            # A contact shadow: the ground itself, darker, at her feet.
            span = max(3, round(tall * 0.16)) + (3 if pose.sit else 0)
            for dx in range(-span, span + 1):
                gx = width // 2 + dx
                for gy in (ground, ground + 1):
                    if 0 <= gx < width and 0 <= gy < height and (gy == ground or abs(dx) < span - 1):
                        painter.fillRect(gx, gy, 1, 1, image.pixelColor(gx, gy).darker(165))
        else:
            # A portrait: her head a third of the way down, cut at the waist by the frame.
            x, y = width // 2 - foot_x, round(height * 0.3) - ht - hop
        painter.drawImage(x, y, sprite)
        head = (hx + x, ht + y, hw)
        self._paint_accent(painter, look.get("accent", "none"), head, hh, QColor(look.get("glow") or "#fde68a"), t)
        if face["tear"] and pose.facing == "front":
            fall = int(t * 3) % 3
            painter.fillRect(head[0] + hw - 2, head[1] + round(hh * 0.6) + 1 + fall, 1, 1, QColor("#7dd3fc"))
        return head

    def _paint_accent(self, painter, accent, head, rows, glow, t):
        """What floats with her: a halo, an antenna, a leaf, little stars."""
        hx, top, hw = head
        cx = hx + hw // 2
        if accent == "halo":
            half = max(2, hw // 2 + 1)
            y = top - 4 + (1 if math.sin(t * 2) > 0.5 else 0)
            painter.fillRect(cx - half + 1, y, 2 * half - 1, 1, QColor("#fde68a"))
            painter.fillRect(cx - half, y + 1, 1, 1, QColor("#fbbf24"))
            painter.fillRect(cx + half, y + 1, 1, 1, QColor("#fbbf24"))
            painter.fillRect(cx - half + 1, y + 2, 2 * half - 1, 1, QColor("#fbbf24"))
        elif accent == "antenna":
            sway = round(math.sin(t * 2.3))
            painter.fillRect(cx, top - 2, 1, 2, QColor("#3f3a4f"))
            tip = glow.lighter(125) if math.sin(t * 3.1) > 0 else glow
            painter.fillRect(cx + sway, top - 4, 2, 2, tip)
        elif accent == "leaf":
            pixels.draw(painter, pixels.LEAF, cx - 1, top - 2, {"g": QColor("#4ade80"), "G": QColor("#15803d")})
        elif accent == "stars":
            for index, (dx, dy) in enumerate(((-hw - 2, 1), (hw + 2, -2), (hw + 3, rows))):
                x, y = cx + dx, top + dy
                shine = math.sin(t * 2.2 + index * 2.1)
                painter.fillRect(x, y, 1, 1, QColor("#ffffff") if shine > 0.3 else QColor("#fbbf24"))
                if shine > 0.3:
                    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        painter.fillRect(x + ox, y + oy, 1, 1, QColor("#fbbf24"))

    def _paint_emote(self, painter, head, face, t, width):
        """What is inside her, in a balloon beside her head."""
        hx, top, hw = head
        colors = {"k": pixels.INK_DARK, "r": QColor("#ef4444")}
        if self.activity == "asleep":
            for phase in (0.0, 0.5):
                p = (t * 0.45 + phase) % 1
                color = QColor(248, 245, 255, round(255 * (1 - p)))
                pixels.draw(painter, pixels.LETTER_Z, hx + hw + 1 + round(p * 4), top - 2 - round(p * 7),
                            {"k": color})
            return
        if self.activity == "thinking":
            dots = int(t * 2.5) % 4  # "…" filling in, dot by dot
            icon = ["".join("k" if column % 2 == 0 and column // 2 < dots else "." for column in range(5))]
        elif self.look.get("feeling") == "anxious":
            pixels.draw(painter, pixels.DROP, hx + hw, top + 1, {"t": QColor("#7dd3fc")})
            return
        else:
            icon_name = EMOTES.get(self.look.get("feeling", ""))
            if icon_name is None or (t % 9) > 2.8:
                return
            icon = pixels.ICONS[icon_name]
        balloon_w, balloon_h = len(icon[0]) + 4, len(icon) + 4
        x = min(hx + hw + 1, width - balloon_w - 2)
        y = max(1, top - balloon_h - 1)
        pixels.balloon(painter, icon, x, y, colors)

