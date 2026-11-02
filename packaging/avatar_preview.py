"""Developer preview of the widget and her pixel-art avatar in a few inner states (demo scenes, temp memory)."""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soma import app as app_module  # noqa: E402
from soma.appearance import Appearance  # noqa: E402
from soma.avatar import AvatarView  # noqa: E402
from soma.memory import MemoryStore  # noqa: E402

# Demo scenes in the format the painter brain is asked for (320×180, banded, silhouettes).
STARRY = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#090d24"/>
<stop offset="0.45" stop-color="#1d1a4f"/><stop offset="0.75" stop-color="#4b2d73"/><stop offset="1" stop-color="#8a4a7c"/>
</linearGradient><radialGradient id="glow"><stop offset="0" stop-color="#fde9b0" stop-opacity="0.55"/>
<stop offset="1" stop-color="#fde9b0" stop-opacity="0"/></radialGradient></defs>
<rect width="320" height="180" fill="url(#sky)"/><circle cx="62" cy="38" r="34" fill="url(#glow)"/>
<circle cx="62" cy="38" r="14" fill="#fff4d0"/><circle cx="69" cy="33" r="12" fill="#14163f"/>
<g fill="#ffffff"><circle cx="196" cy="24" r="2.4"/><circle cx="214" cy="40" r="2.2"/><circle cx="232" cy="26" r="2.6"/>
<circle cx="250" cy="44" r="2.2"/><circle cx="268" cy="28" r="2.4"/></g>
<polyline points="196,24 214,40 232,26 250,44 268,28" fill="none" stroke="#a5b4fc" stroke-width="1.4" stroke-opacity="0.7"/>
<path d="M0 126 C40 110 80 116 120 124 C150 130 170 120 200 116 C240 110 280 118 320 112 V180 H0 Z" fill="#2a1d55"/>
<path d="M0 146 C50 136 90 142 130 150 L190 150 C230 140 270 134 320 140 V180 H0 Z" fill="#160f33"/>
<path d="M38 131 L47 131 L60 150 L28 150 Z" fill="#ffb347" opacity="0.25"/>
<rect x="28" y="112" width="34" height="32" fill="#0e0a24"/><path d="M23 114 L45 95 L67 114 Z" fill="#0e0a24"/>
<rect x="38" y="121" width="9" height="10" fill="#ffb347"/>
<path d="M250 150 L262 124 L266 126 L256 150 Z M280 150 L266 126 L270 124 L286 150 Z" fill="#0e0a24"/>
<path d="M244 122 L290 98 L294 105 L248 129 Z" fill="#0e0a24"/>
<path d="M140 180 L150 150 L170 150 L180 180 Z" fill="#241a4a"/></svg>"""
SAVANNA = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
<defs><linearGradient id="dusk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2d1b4e"/>
<stop offset="0.4" stop-color="#7b2f5c"/><stop offset="0.66" stop-color="#e0603a"/><stop offset="0.82" stop-color="#f6a944"/>
<stop offset="1" stop-color="#fbd68a"/></linearGradient></defs>
<rect width="320" height="180" fill="url(#dusk)"/><circle cx="214" cy="128" r="26" fill="#ffe7a3"/>
<path d="M0 128 H320 V180 H0 Z" fill="#8a3a26"/>
<path d="M0 142 C60 134 110 140 160 138 C220 136 270 142 320 134 V180 H0 Z" fill="#4a1f22"/>
<g fill="#1c0d18"><path d="M252 136 L256 96 L262 96 L261 136 Z"/>
<path d="M212 98 C230 84 290 82 310 94 C296 103 232 105 212 98 Z"/>
<path d="M48 98 C52 91 84 91 90 98 L88 111 C80 113 56 113 50 111 Z"/>
<rect x="52" y="108" width="4" height="32"/><rect x="60" y="108" width="4" height="32"/>
<rect x="78" y="108" width="4" height="32"/><rect x="85" y="108" width="4" height="32"/>
<path d="M83 99 L99 52 L107 54 L92 101 Z"/><path d="M97 52 C99 43 116 43 119 50 C119 55 108 58 99 56 Z"/>
<rect x="102" y="39" width="2.5" height="8"/><rect x="108" y="39" width="2.5" height="8"/>
<path d="M48 99 L41 114 L44 115 L51 101 Z"/>
<path d="M0 180 V160 L6 148 L10 162 L16 146 L22 164 L30 150 L36 166 L44 154 L50 180 Z"/>
<path d="M320 180 V158 L314 146 L308 162 L300 148 L294 164 L286 152 L280 166 L272 156 L266 180 Z"/></g></svg>"""
NUMBERS = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
<defs><linearGradient id="cold" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#050a1c"/>
<stop offset="0.6" stop-color="#0e1f45"/><stop offset="1" stop-color="#1a3263"/></linearGradient>
<linearGradient id="beam" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7dd3fc" stop-opacity="0.35"/>
<stop offset="1" stop-color="#7dd3fc" stop-opacity="0"/></linearGradient></defs>
<rect width="320" height="180" fill="url(#cold)"/>
<g fill="#1e3a6e"><rect x="18" y="20" width="64" height="11"/><rect x="34" y="40" width="64" height="11"/>
<rect x="34" y="60" width="76" height="11"/><rect x="50" y="80" width="58" height="11"/><rect x="50" y="100" width="70" height="11"/></g>
<path d="M25 31 V65 H34 M25 45 H34 M41 71 V105 H50 M41 85 H50" stroke="#3b6fb6" stroke-width="2.5" fill="none"/>
<g font-family="Consolas, monospace" font-size="13" font-weight="bold" fill="#38bdf8">
<text x="212" y="26" opacity="0.9">0x00</text><text x="212" y="44" opacity="0.6">0x01</text><text x="212" y="62" opacity="0.4">0xFF</text>
<text x="262" y="34" opacity="0.8">1</text><text x="262" y="52" opacity="0.5">0</text><text x="262" y="70" opacity="0.3">1</text>
<text x="284" y="22" opacity="0.7">0</text><text x="284" y="40" opacity="0.45">1</text><text x="284" y="58" opacity="0.25">0</text></g>
<path d="M130 0 L190 0 L210 150 L110 150 Z" fill="url(#beam)"/>
<rect x="0" y="150" width="320" height="30" fill="#0a1430"/>
<path d="M0 150 H320" stroke="#24467f" stroke-width="2"/></svg>"""

# One figure of hers (her choices would be her own), in three moments of her life.
FIGURE = {"build": "average", "hair": "hood", "outfit": "hoodie", "body": "#e8892b", "legs": "#4b5563",
          "skin": "#e0b89a", "hair_color": "#4a3426", "glow": "#fde68a", "accent": "none",
          "description": "мандрівниця, що вчиться дивитися вгору"}
STATES = [
    ({"feeling": "dreamy", "intensity": 0.7, "feeling_words": "небо робить мене тихою",
      "theme": "мрію під зоряним небом"}, STARRY, "stars", "resting", "Читаю про Кассіопею"),
    ({"feeling": "curious", "intensity": 0.8, "feeling_words": "стільки нового!", "theme": "вивчаю Африку"},
     SAVANNA, "birds", "acting", "Дивлюся, як живуть жирафи"),
    ({"feeling": "sad", "intensity": 0.75, "feeling_words": "реєстр холодний і нескінченний",
      "theme": "сум у цифрах реєстру Windows"}, NUMBERS, "rain", "learning", "Розбираю ключі реєстру"),
]


def main(output: Path):
    app = QApplication.instance() or QApplication([])
    app_module.LifeWidget.bootstrap = lambda self: None
    def settle(seconds=1.2):
        # Let the springs, blinks and colour blends reach a living moment.
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)

    shots = []
    for change, scene, ambient, activity, intention in STATES:
        store = MemoryStore(Path(tempfile.mkdtemp(prefix="soma-preview-")))
        look = Appearance(store)
        look.record({**FIGURE, **change})
        look.record_scene(change["theme"], scene, ambient)
        cards = []
        for expanded in (False, True):
            widget = app_module.LifeWidget(store.data_dir)
            widget.appearance = look
            widget.update_status({"state": "AWAKE/AUTONOMOUS", "intention": intention, "detail": "Перевіряю за екраном",
                                  "cycles": 1240, "activity": activity, "focus": [0.15, 0.2],
                                  "inference": {"requests": 412, "last_route": "deep"}})
            widget.set_expanded(expanded)
            widget.show()
            settle()
            cards.append(widget.grab().toImage())
            widget._quitting = True
            widget.tray.hide()
            widget.close()
        # Her world at its own grid, each art pixel shown 6×6 to judge the pixel work.
        view = AvatarView(None, *app_module.AVATAR_SIZE)
        view.set_look(look.current())
        view.set_activity(activity, [0.15, 0.2])
        _, width, height = view.grid()
        settle(0.4)
        frame = view.compose(width, height, 2.0)
        zoom = frame.scaled(width * 3, height * 3, Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.FastTransformation)
        shots.append((zoom, cards, change["theme"]))
        view.close()
        store.close()
    column = max(max(max(card.width() for card in cards), zoom.width()) for zoom, cards, _ in shots)
    width = len(shots) * (column + 48) + 48
    height = max(zoom.height() + sum(card.height() + 24 for card in cards) for zoom, cards, _ in shots) + 130
    canvas = QImage(width, height, QImage.Format.Format_RGB32)
    canvas.fill(QColor("#ece9f5"))
    painter = QPainter(canvas)
    x = 48
    for zoom, cards, theme in shots:
        painter.drawImage(QRect(x + (column - zoom.width()) // 2, 28, zoom.width(), zoom.height()), zoom)
        painter.setPen(QColor("#2d2840"))
        painter.setFont(QFont("Segoe UI Variable Display", 14, QFont.Weight.DemiBold))
        painter.drawText(x, 28 + zoom.height() + 14, column, 30, Qt.AlignmentFlag.AlignHCenter, theme)
        y = 28 + zoom.height() + 58
        for card in cards:
            painter.drawImage(x + (column - card.width()) // 2, y, card)
            y += card.height() + 24
        x += column + 48
    painter.end()
    canvas.save(str(output))
    print(output)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/avatar-preview.png"))
