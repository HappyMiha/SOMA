import pytest
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

from soma import pixels


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def canvas(width, height, color="#101020"):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def test_any_world_falls_into_a_small_palette_of_bands():
    picture = canvas(400, 300)
    painter = QPainter(picture)
    gradient = QLinearGradient(0, 0, 0, 300)
    gradient.setColorAt(0, QColor("#0b1026"))
    gradient.setColorAt(1, QColor("#f6a944"))
    painter.fillRect(picture.rect(), gradient)
    painter.end()
    small = pixels.picture_pixels(picture, 40, 20, colors=6)
    assert (small.width(), small.height()) == (40, 20)
    assert len({small.pixel(x, y) for y in range(20) for x in range(40)}) <= 6       # a small palette
    assert all(len({small.pixel(x, y) for x in range(40)}) == 1 for y in range(20))  # the sky in bands


def drawn_rows(image):
    rows = [y for y in range(image.height()) if any(image.pixelColor(x, y).alpha() for x in range(image.width()))]
    return rows[0], rows[-1]


def test_she_is_a_person_of_human_proportions_in_her_own_clothes():
    figure = pixels.Figure(build="average", hair="bob", hair_color="#2b1a1a", skin="#f1d2bd", outfit="coat",
                           body="#9f1d2f", legs="#1f2937", glow="#93c5fd", accent="scarf")
    image, (foot_x, foot_y), (hx, top, hw, rows) = pixels.person(figure, pixels.Pose(), 42)
    first, last = drawn_rows(image)
    assert 40 <= last - first <= 48 and last == foot_y + 1           # about her height, outline under her shoes
    assert round((last - first) / rows) in (6, 7, 8)                  # about seven heads tall
    colours = {image.pixelColor(x, y).name() for y in range(image.height()) for x in range(image.width())
               if image.pixelColor(x, y).alpha() == 255}
    assert {"#9f1d2f", "#f1d2bd", "#2b1a1a"} & colours                # her coat, skin, hair
    assert image.pixelColor(foot_x, first - 1).alpha() == 0
    outline = image.pixelColor(foot_x, last)
    assert pixels.luma(outline) < 40                                  # a dark outline around her


def test_her_body_speaks():
    figure = pixels.Figure()
    standing = pixels.person(figure, pixels.Pose(), 42)[0]
    joyful = pixels.person(figure, pixels.Pose(left=(150, 10), right=(150, 10)), 42)[0]
    sitting = pixels.person(figure, pixels.Pose(sit=True), 42)[0]
    behind = pixels.person(figure, pixels.Pose(facing="back"), 42)[0]
    assert drawn_rows(joyful)[0] < drawn_rows(standing)[0] - 2         # arms up above her head (and hood)
    assert drawn_rows(sitting)[0] > drawn_rows(standing)[0] + 10       # sitting on the ground
    skin = QColor(figure.skin)
    def skin_pixels(image):
        return sum(image.pixelColor(x, y).name() == skin.name() for y in range(image.height())
                   for x in range(image.width()))
    assert skin_pixels(behind) < skin_pixels(standing)                  # seen from behind: no face


def test_ambient_life_moves_but_every_particle_keeps_its_own_path():
    def frame(kind, t):
        image = canvas(80, 40)
        painter = QPainter(image)
        pixels.ambient(painter, kind, t, 80, 40)
        painter.end()
        return image
    for kind in ("stars", "snow", "rain", "fireflies", "petals", "dust", "birds"):
        assert frame(kind, 3.0) == frame(kind, 3.0), kind      # the same moment, the same picture
        assert frame(kind, 3.0) != frame(kind, 4.5), kind      # alive
    assert frame("none", 1.0) == frame("none", 7.0) == canvas(80, 40)

