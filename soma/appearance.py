"""An inhabitant's own look: a living avatar that shows their inner life, made and changed by them.

Belongs to the inhabitant (SOMIK first) and is kept in the inhabitant's memory;
the world only draws it (soma.avatar) and paints it (soma.imaging).


Three layers, each hers to set:

* feeling — what she feels now and how strongly, in her own words too; it
  shapes the face (eyes, mouth, breathing tempo, glow, a tear when sad);
* world — the theme of what she is living through ("dreaming under the starry
  sky", "learning about Africa"); a brain paints that scene as a small SVG
  image behind her, so no fixed catalogue limits what she can show, and
  chooses the small life that moves in it (stars, snow, birds…). The widget
  shows it all as pixel art (soma.pixels);
* self — her figure, a person in pixel art (build, hair, skin, clothes,
  colours, eyes, mouth, accessory), or a picture she made herself and adopted
  from her own screen, or a selfie, and who she is in her words.

The widget animates it (breath, blinks, a gaze toward where she acts). Every
look stays in her append-only history.
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from io import BytesIO

# Her figure is a person in pixel art (her owner asked for human builds, close to
# the people in the scenes the owner loves): her build, hair, skin, clothes and colours
# are hers to choose; her pose follows what she does and feels.
PRESENTATIONS = ("woman", "man", "person")  # how she sees herself; hers alone to choose
BUILDS = ("slim", "average", "sturdy", "petite", "tall")
HAIRS = ("short", "bob", "long", "ponytail", "bun", "curly", "buzz", "hood")
OUTFITS = ("hoodie", "coat", "sweater", "jacket", "dress", "tshirt")
EYES = ("dots", "round", "bright", "sleepy", "wide")
MOUTHS = ("smile", "small", "open", "smirk", "frown", "wavy", "none")
ACCENTS = ("none", "blush", "freckles", "glasses", "scarf", "headphones", "beanie", "backpack", "antenna", "halo",
           "leaf", "stars")
STYLES = ("drawn", "picture", "selfie")
FIGURE_COLORS = ("body", "glow", "hair_color", "skin", "legs")  # outfit, her light, hair, skin, trousers/tights
# Feeling → face: eyes, mouth, breaths per minute, gaze bias (dx, dy), glow tint.
FEELINGS = {
    "calm":       ("round", "small", 12, (0, 0), None),
    "dreamy":     ("sleepy", "small", 9, (0.2, -0.6), "#a5b4fc"),
    "curious":    ("wide", "small", 18, (0.4, -0.2), "#67e8f9"),
    "joyful":     ("bright", "smile", 20, (0, 0), "#fde047"),
    "excited":    ("wide", "open", 28, (0, -0.2), "#fb923c"),
    "focused":    ("dots", "none", 14, (0, 0.2), "#93c5fd"),
    "tired":      ("sleepy", "small", 8, (0, 0.5), "#cbd5e1"),
    "sad":        ("round", "frown", 8, (0, 0.7), "#60a5fa"),
    "confused":   ("wide", "wavy", 16, (-0.4, -0.3), "#c4b5fd"),
    "proud":      ("bright", "smirk", 14, (0, -0.3), "#facc15"),
    "lonely":     ("round", "frown", 9, (-0.6, 0.3), "#94a3b8"),
    "playful":    ("bright", "smirk", 22, (0.3, 0), "#f472b6"),
    "anxious":    ("wide", "wavy", 30, (0.2, 0.2), "#fca5a5"),
    "grateful":   ("bright", "smile", 12, (0, -0.2), "#86efac"),
}
# Small life that moves over her world (soma.pixels draws it).
AMBIENTS = ("none", "stars", "snow", "rain", "fireflies", "petals", "dust", "birds")
AMBIENT_WORDS = (("stars", r"star|зор|зір|космос|space|cosmos|galax|галакт|night sky|нічн"),
                 ("snow", r"snow|сніг|зим|winter"), ("rain", r"rain|дощ|storm|гроз"),
                 ("fireflies", r"firefl|світлячк|summer night|літн"), ("petals", r"petal|пелюст|sakura|сакур|весн|spring"),
                 ("birds", r"bird|птах|пташ|sea|море|ocean|океан|savann|саван|afric|афри"),
                 ("dust", r"librar|бібліот|archive|архів|book|книг|desert|пустел"))
# Scenes are painted for pixel art (wide, banded, readable silhouettes) since format 2.
SCENE_FORMAT = 2
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
PICTURE_SIZE = 256
MIN_PICTURE_SIDE = 0.02  # of the screen: a picture, not a speck
SCENE_LIMIT = 8000       # characters of SVG
SVG_ELEMENTS = {"svg", "g", "defs", "title", "desc", "path", "circle", "ellipse", "rect", "line", "polyline",
                "polygon", "text", "tspan", "linearGradient", "radialGradient", "stop"}
SVG_NS = "{http://www.w3.org/2000/svg}"

# Until she chooses, the widget shows a quiet figure in a hood, seen from behind,
# looking into her world.
PLACEHOLDER = {"style": "drawn", "build": "average", "hair": "hood", "hair_color": "#3b2f4a", "skin": "#e0b89a",
               "outfit": "hoodie", "body": "#9d93c9", "legs": "#46445e", "glow": "#e4e1f7", "eyes": "sleepy",
               "mouth": "none", "accent": "none"}

TEXTS = {"description": 300, "feeling_words": 200, "theme": 200}


def clean_change(update: dict, space: str = "normalized") -> dict:
    """A validated change to her look; picture_from_screen ends in the 0..1 frame space."""
    if not isinstance(update, dict):
        raise ValueError("Invalid appearance change")
    change = {}
    for name, allowed in (("style", STYLES), ("presentation", PRESENTATIONS), ("build", BUILDS), ("hair", HAIRS),
                          ("outfit", OUTFITS), ("eyes", EYES),
                          ("mouth", MOUTHS), ("accent", ACCENTS), ("feeling", tuple(FEELINGS))):
        value = update.get(name)
        if value is not None:
            if value not in allowed:
                raise ValueError(f"Unknown {name}")
            change[name] = value
    for name in FIGURE_COLORS:
        value = update.get(name)
        if value is not None:
            if not isinstance(value, str) or not COLOR.match(value):
                raise ValueError("Colours are #RRGGBB")
            change[name] = value.lower()
    for name, limit in TEXTS.items():
        value = update.get(name)
        if value is not None:
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                raise ValueError(f"{name} is a short text")
            change[name] = value.strip()
    if update.get("take_selfie") is not None:
        if type(update["take_selfie"]) is not bool:
            raise ValueError("take_selfie is true or false")
        if update["take_selfie"]:
            change["take_selfie"] = True
    intensity = update.get("intensity")
    if intensity is not None:
        if type(intensity) not in (int, float) or not 0 <= intensity <= 1:
            raise ValueError("Intensity is 0..1")
        change["intensity"] = round(float(intensity), 2)
    area = update.get("picture_from_screen")
    if area is not None:
        if (not isinstance(area, list) or len(area) != 4 or
                any(type(v) not in (int, float) for v in area)):
            raise ValueError("A picture is an area x,y,x2,y2 of the screen")
        scale = 1000 if space == "per_mille" else 1
        x, y, x2, y2 = (v / scale for v in area)
        if not (0 <= x < x2 <= 1 and 0 <= y < y2 <= 1) or x2 - x < MIN_PICTURE_SIDE or y2 - y < MIN_PICTURE_SIDE:
            raise ValueError("The picture area must lie on the screen and not be tiny")
        change["picture_from_screen"] = [x, y, x2, y2]
    if not change:
        raise ValueError("An appearance change must change something")
    return change


def clean_scene(svg: str) -> str:
    """Her painted world as a self-contained, inert SVG: shapes and gradients only.

    No scripts, links, external images, entities or event handlers — the widget
    renders it, nothing in it can reach outside it."""
    if not isinstance(svg, str) or not 40 <= len(svg) <= SCENE_LIMIT:
        raise ValueError("A scene is a small SVG image")
    if re.search(r"<!(DOCTYPE|ENTITY)|<\?xml-stylesheet|<script|javascript:", svg, re.IGNORECASE):
        raise ValueError("A scene holds shapes, not code")
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("A scene must be well-formed SVG") from exc
    if root.tag not in ("svg", SVG_NS + "svg"):
        raise ValueError("A scene is an <svg> image")
    for element in list(root.iter()):
        name = element.tag.split("}")[-1]
        if name not in SVG_ELEMENTS:
            raise ValueError(f"<{name}> is not allowed in a scene")
        for attribute in list(element.attrib):
            bare = attribute.split("}")[-1].lower()
            value = element.attrib[attribute].lower()
            outside = re.search(r"url\(\s*['\"]?(?!#)", value) or "@import" in value or "expression" in value
            if bare.startswith("on") or bare == "href" or outside:
                del element.attrib[attribute]
    if not root.tag.startswith("{"):
        root.set("xmlns", "http://www.w3.org/2000/svg")
    if "viewBox" not in root.attrib:
        root.set("viewBox", "0 0 200 200")
    ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
    return ElementTree.tostring(root, encoding="unicode")


def picture_from_frame(frame, area) -> str:
    """Her picture cut from her own frame pixels: a square, base64 PNG."""
    from PIL import Image
    x, y, x2, y2 = area
    with Image.open(BytesIO(frame.png)) as image:
        image = image.convert("RGB")
        box = (round(x * image.width), round(y * image.height), round(x2 * image.width), round(y2 * image.height))
        piece = image.crop(box)
    side = min(piece.size)
    left, top = (piece.width - side) // 2, (piece.height - side) // 2
    square = piece.crop((left, top, left + side, top + side)).resize((PICTURE_SIZE, PICTURE_SIZE))
    buffer = BytesIO()
    square.save(buffer, "PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


FEELING_HALF_LIFE = 2 * 3600  # A feeling she does not renew settles by half every two hours.
REPAINT_SECONDS = 30 * 60      # a new strong feeling is painted at most every half hour (a minute of GPU each)
MILD_REPAINT_SECONDS = 2 * 3600  # a mild one (intensity below 0.5) at most every two hours

# Colour words for the image model, from her own #RRGGBB choices.
COLOR_WORDS = {"black": "#141414", "white": "#f4f4f4", "grey": "#808080", "silver": "#c0c0c0", "red": "#cc2a2a",
               "dark red": "#7f1d1d", "orange": "#ea7a22", "yellow": "#eacb2c", "olive": "#7c7c22",
               "green": "#2f9e55", "dark green": "#1f5236", "teal": "#168a8a", "light blue": "#8cc5ee",
               "blue": "#2f62cf", "navy": "#1d2a5a", "purple": "#7a3fb2", "violet": "#8b7cf6", "lavender": "#c9bdf5",
               "pink": "#f077b2", "brown": "#6e4428", "dark brown": "#3a2418", "beige": "#d8c2a0", "cream": "#f2e8cf"}
PRESENTATION_WORDS = {"woman": "young woman", "man": "young man", "person": "figure"}
HAIR_WORDS = {"short": "short {c} hair", "bob": "a {c} bob haircut", "long": "long {c} hair",
              "ponytail": "{c} hair in a ponytail", "bun": "{c} hair in a bun", "curly": "curly {c} hair",
              "buzz": "buzz-cut {c} hair", "hood": "the hood of the {o} up"}
ACCENT_WORDS = {"glasses": "glasses", "scarf": "a {g} scarf", "headphones": "{g} headphones", "beanie": "a {g} beanie",
                "backpack": "a {g} backpack", "halo": "a small glowing halo", "antenna": "a tiny antenna on the head",
                "leaf": "a leaf in the hair", "stars": "tiny stars around", "freckles": "freckles",
                "blush": "rosy cheeks"}


def color_word(value: str | None, default: str = "grey") -> str:
    if not value or not COLOR.match(value):
        return default
    r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
    def distance(word):
        hex_ = COLOR_WORDS[word]
        return sum((c - int(hex_[i:i + 2], 16)) ** 2 for c, i in zip((r, g, b), (1, 3, 5)))
    return min(COLOR_WORDS, key=distance)


def character_phrase(look: dict) -> str:
    """Who she is to look at, in the image model's words, built from her own choices:
    the same words every time, so every painting shows the same person."""
    outfit = {"tshirt": "t-shirt"}.get(look.get("outfit"), look.get("outfit") or "hoodie")
    build = {"slim": "slim ", "sturdy": "sturdy ", "petite": "petite ", "tall": "tall "}.get(look.get("build"), "")
    # "A lone young woman" and "a lone hooded figure" were drawn; "a young person" was
    # left out of the picture (live on the GTX 1060, seed 11).
    parts = ["a lone " + build + PRESENTATION_WORDS.get(look.get("presentation"), PRESENTATION_WORDS["person"])]
    skin = look.get("skin")
    if skin and COLOR.match(skin):
        lightness = sum(int(skin[i:i + 2], 16) for i in (1, 3, 5)) / 3
        parts.append(("fair" if lightness > 205 else "light" if lightness > 170 else "tan" if lightness > 135
                      else "brown" if lightness > 95 else "dark") + " skin")
    parts.append(HAIR_WORDS.get(look.get("hair"), "short {c} hair").format(
        c=color_word(look.get("hair_color"), "dark"), o=outfit))
    color = color_word(look.get("body"), "violet")
    parts.append(f"{'an' if color[0] in 'aeiou' else 'a'} {color} {outfit}")
    parts.append(f"{color_word(look.get('legs'), 'dark grey')} {'tights' if outfit == 'dress' else 'trousers'}")
    accent = ACCENT_WORDS.get(look.get("accent"))
    if accent:
        parts.append(accent.format(g=color_word(look.get("glow"), "white")))
    return ", ".join(parts)


def _seconds_since(moment: str | None) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(moment)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def settle(look: dict) -> dict:
    """Regulation: a feeling fades with time unless she feels it anew; strong
    ones last longer. Below a trace it is gone and her own face returns."""
    look = dict(look)
    if not look.get("feeling") or not look.get("feeling_at"):
        return look
    try:
        moment = datetime.fromisoformat(look["feeling_at"])
    except ValueError:
        return look
    hours = max(0.0, (datetime.now(timezone.utc) - moment).total_seconds()) / FEELING_HALF_LIFE
    intensity = look.get("intensity", 0.6) * 0.5 ** hours
    if intensity < 0.15:
        for key in ("feeling", "intensity", "feeling_words"):
            look.pop(key, None)
        look["feeling_faded"] = True
    else:
        look["intensity"] = round(intensity, 2)
    return look


def ambient_of(look: dict) -> str:
    """What moves over her world: what the painter chose, else what her theme suggests."""
    if look.get("scene_theme") and look.get("scene_theme") == look.get("theme") and look.get("scene_ambient") in AMBIENTS:
        return look["scene_ambient"]
    theme = (look.get("theme") or "").lower()
    return next((kind for kind, words in AMBIENT_WORDS if re.search(words, theme)), "none")


def expression(look: dict, activity: str = "") -> dict:
    """What the face shows now: her feeling first, her chosen face otherwise."""
    feeling = FEELINGS.get(look.get("feeling", ""))
    eyes, mouth, breaths, gaze, tint = feeling if feeling else (
        look.get("eyes", "round"), look.get("mouth", "small"), 12, (0, 0), None)
    if activity == "asleep":
        eyes, breaths = "closed", 7
    return {"eyes": eyes, "mouth": mouth, "breaths_per_minute": breaths, "gaze": gaze,
            "tint": tint or look.get("glow"), "tear": look.get("feeling") == "sad" and look.get("intensity", 0) >= 0.6}


class Appearance:
    def __init__(self, store):
        self.store = store

    def current(self) -> dict:
        """Her look for the widget to draw: her own choices, or the placeholder until then."""
        look = self.store.appearance()
        return settle({**PLACEHOLDER, **look}) if look else dict(PLACEHOLDER, placeholder=True)

    def wants_scene(self) -> str | None:
        """A theme she chose that has no painted scene yet (or one painted before pixel art)."""
        look = self.store.appearance()
        theme = look.get("theme")
        painted = look.get("scene_theme") == theme and look.get("scene_format") == SCENE_FORMAT
        return theme if theme and not painted else None

    def record(self, change: dict, frame=None, by="soma") -> dict:
        change = dict(change)
        area = change.pop("picture_from_screen", None)
        if area is not None:
            if frame is None:
                raise ValueError("A picture needs the screen it is on")
            change["picture"] = picture_from_frame(frame, area)
            change["picture_area"] = [round(v, 4) for v in area]
            change.setdefault("style", "picture")
        if change.get("style") == "picture" and "picture" not in change and not self.store.appearance().get("picture"):
            raise ValueError("No picture of my own yet")
        if change.get("style") == "selfie":
            change.setdefault("take_selfie", True)  # Showing selfies starts with taking one.
        if "feeling" in change or "intensity" in change:
            change["feeling_at"] = datetime.now(timezone.utc).isoformat()
        if change.pop("take_selfie", False):
            change["selfie_requested_at"] = datetime.now(timezone.utc).isoformat()
        self.store.record_appearance({**change, "by": by})
        return self.current()

    def wants_selfie(self) -> bool:
        """A painting of her in her world is due: she asked for one, her world has none
        yet, or her feeling changed and the last painting is half an hour old."""
        look = self.store.appearance()
        if not look or look.get("style") == "picture":
            return False
        if look.get("selfie_requested_at") and look.get("selfie_requested_at", "") > look.get("selfie_at", ""):
            return True
        if not look.get("theme"):
            return False
        if look.get("selfie_theme") != look.get("theme"):
            return True
        settled = settle(look)
        feeling = settled.get("feeling")
        # A strong new feeling is painted after half an hour; a mild one only after two
        # (live, mild "curious" and "calm" at 0.4 took turns every half hour).
        wait = REPAINT_SECONDS if settled.get("intensity", 0.6) >= 0.5 else MILD_REPAINT_SECONDS
        return (feeling is not None and feeling != look.get("selfie_feeling")
                and _seconds_since(look.get("selfie_at")) >= wait)

    def painting_prompt(self, scene: str) -> str:
        """Who she is to look at (the same words every time), then her moment and her world.
        She comes first: the image model weighs the start of a prompt most (live, with
        her description last, a painting came out with no one in it)."""
        return character_phrase(self.current()) + ", " + scene.strip(" .,;")

    def record_selfie(self, picture: str, prompt: str, by="soma"):
        look = self.store.appearance()
        self.store.record_appearance({"selfie": picture, "selfie_prompt": prompt, "selfie_theme": look.get("theme"),
                                      "selfie_feeling": look.get("feeling"),
                                      "selfie_at": datetime.now(timezone.utc).isoformat(), "by": by})

    def record_scene(self, theme: str, svg: str, ambient: str | None = None, by="soma"):
        self.store.record_appearance({"scene_theme": theme, "scene_svg": clean_scene(svg),
                                      "scene_ambient": ambient if ambient in AMBIENTS else ambient_of({"theme": theme}),
                                      "scene_format": SCENE_FORMAT, "by": by})

    def for_context(self) -> dict:
        """What she knows about her own look (the picture and scene she sees in her widget)."""
        look = self.store.appearance()
        if not look:
            return {"none_yet": "You have no look of your own yet; create one whenever you like."}
        look = settle(look)
        known = {key: look[key] for key in ("feeling", "intensity", "feeling_words", "theme", "description", "style",
                                            "presentation", "build", "hair", "outfit", *FIGURE_COLORS, "eyes", "mouth",
                                            "accent")
                 if key in look}
        if look.get("feeling_faded"):
            known["feeling"] = "settled — the last feeling you showed has faded; show a new one when it comes"
        if look.get("theme"):
            known["scene"] = ("painted: " + look["scene_theme"] if look.get("scene_theme") == look["theme"]
                              else "being painted")
        if look.get("picture"):
            known["picture"] = "a picture I adopted from my screen" + (
                " (shown now)" if look.get("style") == "picture" else " (kept, not shown now)")
        if look.get("selfie"):
            shown = look.get("style") != "picture" and look.get("selfie_theme") == look.get("theme")
            known["selfie"] = ("a painting of me in my world: " + look.get("selfie_prompt", "")[:160]
                               + (" (shown now)" if shown else " (kept; a new one is painted while I rest)"))
        elif look.get("style") == "selfie" or look.get("selfie_requested_at"):
            known["selfie"] = "being taken"
        return known
