from io import BytesIO

import pytest
from PIL import Image

from soma.appearance import Appearance, clean_change, clean_scene, expression
from soma.core import ScreenFrame
from soma.memory import MemoryStore

STARRY = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
          '<defs><radialGradient id="sky"><stop offset="0" stop-color="#1e1b4b"/>'
          '<stop offset="1" stop-color="#020617"/></radialGradient></defs>'
          '<rect width="200" height="200" fill="url(#sky)"/>'
          '<circle cx="30" cy="40" r="2" fill="#fff"/><circle cx="160" cy="30" r="1.5" fill="#fde68a"/></svg>')


@pytest.fixture
def look(tmp_path):
    store = MemoryStore(tmp_path)
    yield Appearance(store)
    store.close()


def frame_with_drawing():
    image = Image.new("RGB", (400, 200), "white")
    image.paste((240, 120, 30), (100, 50, 200, 150))   # her drawing in an editor, say
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return ScreenFrame(buffer.getvalue(), 400, 200)


def test_her_changes_are_checked_and_her_coordinates_respected():
    change = clean_change({"feeling": "dreamy", "intensity": 0.8, "theme": "under the starry sky",
                           "body": "#7C6CF0", "picture_from_screen": [250, 250, 500, 750]}, "per_mille")
    assert change == {"feeling": "dreamy", "intensity": 0.8, "theme": "under the starry sky", "body": "#7c6cf0",
                      "picture_from_screen": [0.25, 0.25, 0.5, 0.75]}
    for bad in ({"feeling": "furious-rainbow"}, {"body": "purple"}, {"picture_from_screen": [0.5, 0.5, 0.505, 0.6]},
                {"intensity": 3}, {}):
        with pytest.raises(ValueError):
            clean_change(bad)


def test_a_painted_world_is_inert():
    assert "circle" in clean_scene(STARRY)
    for hostile in ('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                    '<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>',
                    '<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///C:/secret.png"/></svg>',
                    "<svg>" + "<circle/>" * 2000 + "</svg>", "not svg at all, just words"):
        with pytest.raises(ValueError):
            clean_scene(hostile)
    cleaned = clean_scene('<svg xmlns="http://www.w3.org/2000/svg" onload="evil()">'
                          '<rect width="9" height="9" fill="url(http://tracker/x.png)" style="fill:red"/></svg>')
    assert "onload" not in cleaned and "tracker" not in cleaned and 'style="fill:red"' in cleaned


def test_feeling_world_and_self_with_their_whole_history(look):
    assert look.current()["placeholder"] and "none_yet" in look.for_context()
    look.record({"feeling": "dreamy", "intensity": 0.7, "feeling_words": "the sky makes me quiet",
                 "theme": "dreaming under the starry sky", "shape": "drop", "description": "a curious wanderer"})
    assert look.wants_scene() == "dreaming under the starry sky"
    look.record_scene("dreaming under the starry sky", STARRY)
    assert look.wants_scene() is None and look.current()["scene_svg"].startswith("<svg")
    known = look.for_context()
    assert known["feeling"] == "dreamy" and known["scene"].startswith("painted") and "scene_svg" not in known
    look.record({"feeling": "curious", "theme": "learning about Africa"})
    assert look.wants_scene() == "learning about Africa" and look.for_context()["scene"] == "being painted"
    history = [e for e in look.store.events(limit=50) if e["kind"] == "appearance.recorded"]
    assert len(history) == 3 and history[0]["data"]["feeling"] == "dreamy"     # nothing erased


def test_a_picture_she_made_is_taken_from_her_own_screen(look):
    with pytest.raises(ValueError):
        look.record({"style": "picture"})                    # no picture of her own yet
    current = look.record({"picture_from_screen": [0.25, 0.25, 0.5, 0.75]}, frame_with_drawing())
    assert current["style"] == "picture"
    with Image.open(BytesIO(__import__("base64").b64decode(current["picture"]))) as picture:
        assert picture.size == (256, 256) and picture.getpixel((128, 128)) == (240, 120, 30)
    wide = look.record({"picture_from_screen": [0.0, 0.0, 1.0, 1.0]}, frame_with_drawing())
    with Image.open(BytesIO(__import__("base64").b64decode(wide["picture"]))) as picture:
        assert picture.size == (448, 224)                    # all she chose, not its square middle


def test_a_feeling_settles_unless_she_feels_it_anew(look):
    from datetime import datetime, timedelta, timezone
    from soma.appearance import settle
    hours_ago = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()
    assert settle({"feeling": "sad", "intensity": 0.8, "feeling_at": hours_ago(4)})["intensity"] == 0.2
    faded = settle({"feeling": "sad", "intensity": 0.8, "feeling_words": "cold", "feeling_at": hours_ago(8)})
    assert "feeling" not in faded and "feeling_words" not in faded and faded["feeling_faded"]
    look.record({"feeling": "joyful", "intensity": 0.9})
    assert look.current()["intensity"] == 0.9                   # just felt: full strength
    assert look.store.appearance()["feeling_at"]                # when she felt it, kept in history


def test_her_feeling_shapes_her_face():
    assert expression({"feeling": "sad", "intensity": 0.8})["tear"] is True
    assert expression({"feeling": "sad", "intensity": 0.3})["tear"] is False
    assert expression({"feeling": "joyful"})["eyes"] == "bright"
    assert expression({"feeling": "dreamy"}, "asleep")["eyes"] == "closed"
    assert expression({"eyes": "wide", "mouth": "smirk"})["mouth"] == "smirk"     # no feeling: her chosen face


def test_scenes_are_painted_for_pixel_art_with_the_life_that_moves_in_them(look):
    from soma.appearance import ambient_of
    look.record({"theme": "dreaming under the starry sky"})
    look.store.record_appearance({"scene_theme": "dreaming under the starry sky", "scene_svg": STARRY})  # before pixel art
    assert look.wants_scene() == "dreaming under the starry sky"           # painted once more, for pixel art
    assert ambient_of(look.current()) == "stars"                            # meanwhile her theme's own words
    look.record_scene("dreaming under the starry sky", STARRY, "fireflies")
    assert look.wants_scene() is None and ambient_of(look.current()) == "fireflies"   # the painter's choice
    look.record({"theme": "гуляю зимовим лісом"})
    assert ambient_of(look.current()) == "snow"


def test_selfies_are_asked_for_taken_and_kept(look):
    assert look.wants_selfie() is False
    look.record({"theme": "night sky", "feeling": "dreamy", "take_selfie": True})
    assert look.wants_selfie() and look.for_context()["selfie"] == "being taken"
    look.record_selfie("UE5HDQo=", "a small violet drop under the stars")
    assert not look.wants_selfie() and look.for_context()["selfie"].startswith("a painting of me in my world")
    look.record({"style": "selfie"})                         # showing selfies: a fresh one first
    assert look.wants_selfie()
    look.record_selfie("UE5HDQo=", "the same drop, smiling")
    look.record({"feeling": "joyful", "intensity": 0.8})     # a new feeling: painted, but not every minute
    assert not look.wants_selfie()
    from datetime import datetime, timedelta, timezone
    ago = lambda minutes: (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    look.store.record_appearance({"selfie_at": ago(31)})
    assert look.wants_selfie()
    look.record_selfie("UE5HDQo=", "the same drop, arms up")
    look.record({"theme": "learning about Africa"})          # her world moved on: so does her painting
    assert look.wants_selfie() and look.current()["selfie_theme"] == "night sky"
    look.record({"style": "picture", "picture_from_screen": [0.25, 0.25, 0.5, 0.75]}, frame_with_drawing())
    assert not look.wants_selfie()                           # she shows her own picture now
    known = look.for_context()                               # ... and is told so, not "a new one is painted"
    assert "instead of my painting" in known["picture"] and "does not paint me" in known["selfie"]
    look.record({"style": "selfie"})
    assert look.wants_selfie()                               # her painting back, painted anew


def test_a_mild_new_feeling_waits_longer_for_its_painting(look):
    from datetime import datetime, timedelta, timezone
    ago = lambda minutes: (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    look.record({"theme": "a quiet evening", "feeling": "curious", "intensity": 0.4})
    look.record_selfie("UE5HDQo=", "reading on a rooftop")
    look.record({"feeling": "calm", "intensity": 0.4})       # live, mild feelings took turns every half hour
    look.store.record_appearance({"selfie_at": ago(31)})
    assert not look.wants_selfie()
    look.store.record_appearance({"selfie_at": ago(121)})
    assert look.wants_selfie()


def test_every_painting_shows_the_same_person_in_her_own_choices(look):
    from soma.appearance import character_phrase
    look.record({"presentation": "woman", "build": "slim", "hair": "bob", "hair_color": "#2b1a1a", "skin": "#f1d2bd",
                 "outfit": "coat", "body": "#9f1d2f", "legs": "#1f2937", "glow": "#93c5fd", "accent": "scarf"})
    phrase = character_phrase(look.current())
    assert phrase == ("a lone slim young woman, fair skin, a dark brown bob haircut, a dark red coat, navy trousers, "
                      "a light blue scarf")
    assert look.painting_prompt("standing in the rain, a street at dusk.") == phrase + ", standing in the rain, a street at dusk"
    hooded = character_phrase({"hair": "hood", "outfit": "hoodie", "body": "#ea7a22"})
    assert "the hood of the hoodie up" in hooded and "an orange hoodie" in hooded


def test_her_avatar_is_pixel_art_in_both_of_its_sizes(look):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from soma.avatar import AvatarView
    app = QApplication.instance() or QApplication([])
    look.record({"feeling": "curious", "theme": "night sky", "shape": "round", "body": "#f59e0b"})
    look.record_scene("night sky", STARRY, "stars")
    view = AvatarView(None, 304, 144)
    view.set_look(look.current())
    view.set_activity("thinking")
    wide = view.compose(152, 72, 2.0)
    assert wide.pixelColor(0, 0).alpha() == 0 and wide.pixelColor(76, 36).alpha() == 255   # stepped corners
    balloon = QColor("#fffdf6")                                # "…" over her head while she thinks
    assert any(wide.pixelColor(x, y) == balloon for x in range(152) for y in range(72))
    square = view.compose(36, 36, 2.0)
    assert square.width() == 36 and square.pixelColor(18, 26).alpha() == 255
    app.processEvents()


def test_the_avatar_lives_in_every_state(look):
    from PySide6.QtWidgets import QApplication
    from soma.avatar import AvatarView
    app = QApplication.instance() or QApplication([])
    view = AvatarView(size=96)
    look.record({"feeling": "dreamy", "theme": "night sky", "accent": "stars", "shape": "cloud"})
    look.record_scene("night sky", STARRY)
    for activity in ("thinking", "acting", "resting", "asleep", "learning"):
        view.set_activity(activity, [0.9, 0.1])
        view.set_look(look.current())
        image = view.grab().toImage()                     # physical pixels at the screen's scale
        middle = image.width() // 2
        assert image.width() >= 96 and image.pixelColor(middle, middle).alpha() == 255   # opaque, drawn
    look.record({"picture_from_screen": [0.25, 0.25, 0.5, 0.75]}, frame_with_drawing())
    view.set_look(look.current())
    image = view.grab().toImage()
    assert image.pixelColor(image.width() // 2, image.height() // 2).red() > 200   # her own picture shown
    app.processEvents()
