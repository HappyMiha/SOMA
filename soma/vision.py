"""Machine vision over SOMA's own screen pixels: reading text with its positions.

This is computation on a captured frame inside SOMA (spec §4.1 allows OCR and
visual grounding over frame pixels). It reads nothing from applications. The
recognizer is PaddleOCR PP-OCRv5 (Cyrillic + Latin) through RapidOCR/ONNX,
running offline on the CPU.

Reading is incremental, the way an eye only refocuses where something moved:
text is detected again only inside regions whose pixels changed since the
previous frame, and a line whose pixels were already recognized (also after
scrolling moved it) reuses its text instead of being recognized again.
"""

from __future__ import annotations

from collections import OrderedDict
import hashlib
from io import BytesIO
import math
import threading

CELL = 16               # change grid in pixels
PAD = 12                # context kept around a changed region for detection
FULL_READ_SHARE = 0.5   # beyond this changed share the whole screen is read again
REMEMBERED_LINES = 4096


def _merge(boxes):
    """Union of overlapping rectangles until none overlap."""
    boxes = list(boxes)
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    boxes[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return boxes


def _overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def changed_regions(old, new):
    """Rectangles (pixels) around everything that differs between two RGB arrays."""
    import numpy as np
    height, width = new.shape[:2]
    diff = np.any(old != new, axis=2)
    if not diff.any():
        return []
    rows, columns = -(-height // CELL), -(-width // CELL)
    grid = np.zeros((rows * CELL, columns * CELL), bool)
    grid[:height, :width] = diff
    cells = grid.reshape(rows, CELL, columns, CELL).any(axis=(1, 3))
    if cells.mean() > FULL_READ_SHARE:
        return [(0, 0, width, height)]
    seen = np.zeros_like(cells)
    boxes = []
    for row, column in zip(*np.nonzero(cells)):
        if seen[row, column]:
            continue
        seen[row, column] = True
        stack, (r0, r1, c0, c1) = [(row, column)], (row, row, column, column)
        while stack:
            y, x = stack.pop()
            r0, r1, c0, c1 = min(r0, y), max(r1, y), min(c0, x), max(c1, x)
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    if 0 <= ny < rows and 0 <= nx < columns and cells[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        boxes.append((max(0, int(c0) * CELL - PAD), max(0, int(r0) * CELL - PAD),
                      min(width, (int(c1) + 1) * CELL + PAD), min(height, (int(r1) + 1) * CELL + PAD)))
    return _merge(boxes)


def _cover(regions, lines):
    """Grow regions until no previously read line is cut by one: it is read whole again."""
    for _ in range(16):
        grown = []
        for region in regions:
            boxes = [region] + [line["px"] for line in lines if _overlaps(line["px"], region)]
            grown.append((min(b[0] for b in boxes), min(b[1] for b in boxes),
                          max(b[2] for b in boxes), max(b[3] for b in boxes)))
        grown = _merge(grown)
        if grown == regions:
            break
        regions = grown
    return regions


def _digest(piece) -> bytes:
    """Identity of a line's pixels, independent of where it sits or its plain margins."""
    import numpy as np
    ink = np.any(piece != piece[0, 0], axis=2)
    rows, columns = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    if rows.size:
        piece = piece[rows[0]:rows[-1] + 1, columns[0]:columns[-1] + 1]
    return hashlib.blake2b(np.ascontiguousarray(piece).tobytes() + repr(piece.shape).encode(),
                           digest_size=16).digest()


class ScreenReader:
    def __init__(self):
        self._engine = None
        self._failed = False
        self._lock = threading.Lock()
        self._cache = (None, [])
        self._previous = None              # (pixels, lines) of the last frame read
        self._known = OrderedDict()        # line pixel digest -> (text, score)
        self.stats = {"full": 0, "partial": 0, "unchanged": 0, "recognized": 0, "reused": 0}

    def _load(self):
        if self._engine is None and not self._failed:
            try:
                import logging
                logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
                self._engine = RapidOCR(params={"Rec.ocr_version": OCRVersion.PPOCRV5,
                                                "Rec.lang_type": LangRec.CYRILLIC,
                                                "Rec.model_type": ModelType.MOBILE,
                                                # Screen text is upright: no orientation pass.
                                                "Global.use_cls": False,
                                                # Native resolution for a whole screen and
                                                # for a small changed region alike.
                                                "Det.limit_type": "max", "Det.limit_side_len": 2000})
            except Exception:
                self._failed = True  # Without a reader SOMA simply keeps using images.
        return self._engine

    @property
    def available(self) -> bool:
        return self._load() is not None

    def read(self, frame) -> list[dict]:
        """Text lines, top to bottom, each with its box as fractions of the screen."""
        with self._lock:
            if self._cache[0] == frame.frame_id:
                return self._cache[1]
            if self._load() is None:
                return []
            import numpy as np
            from PIL import Image
            with Image.open(BytesIO(frame.png)) as image:
                pixels = np.array(image.convert("RGB"))
            height, width = pixels.shape[:2]
            lines = self._read(pixels)
            described = [{"text": line["text"], "score": line["score"],
                          "box": (line["px"][0] / width, line["px"][1] / height,
                                  line["px"][2] / width, line["px"][3] / height)} for line in lines]
            self._cache = (frame.frame_id, described)
            return described

    def _read(self, pixels) -> list[dict]:
        height, width = pixels.shape[:2]
        whole = (0, 0, width, height)
        previous = self._previous
        if previous is None or previous[0].shape != pixels.shape:
            regions = [whole]
        else:
            regions = changed_regions(previous[0], pixels)
            if regions and regions != [whole]:
                regions = _cover(regions, previous[1])
                if sum((r[2] - r[0]) * (r[3] - r[1]) for r in regions) > FULL_READ_SHARE * width * height:
                    regions = [whole]
        if not regions:
            lines = previous[1]
            self.stats["unchanged"] += 1
        elif regions == [whole]:
            lines = self._ocr(pixels, whole)
            self.stats["full"] += 1
        else:
            kept = [line for line in previous[1] if not any(_overlaps(line["px"], r) for r in regions)]
            lines = kept + [line for region in regions for line in self._ocr(pixels, region)]
            self.stats["partial"] += 1
        lines.sort(key=lambda line: (round(line["px"][1] / height * 50), line["px"][0]))
        self._previous = (pixels, lines)
        return lines

    def _ocr(self, pixels, region) -> list[dict]:
        import numpy as np
        x0, y0, x1, y1 = region
        crop = np.ascontiguousarray(pixels[y0:y1, x0:x1])
        found = self._engine(crop, use_det=True, use_cls=False, use_rec=False)
        boxes = getattr(found, "boxes", None)
        if boxes is None or not len(boxes):
            return []
        rects, keys, todo = [], [], {}
        for box in boxes:
            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            bx0, by0 = max(0, int(min(xs))), max(0, int(min(ys)))
            bx1, by1 = min(crop.shape[1], math.ceil(max(xs))), min(crop.shape[0], math.ceil(max(ys)))
            if bx1 - bx0 < 2 or by1 - by0 < 2:
                continue
            piece = crop[by0:by1, bx0:bx1]
            key = _digest(piece)
            rects.append((bx0 + x0, by0 + y0, bx1 + x0, by1 + y0))
            keys.append(key)
            if key not in self._known:
                todo.setdefault(key, piece)
        if todo:
            result = self._engine.recognize_txt(list(todo.values()))
            for key, text, score in zip(todo, result.txts or (), result.scores or ()):
                self._known[key] = (str(text).strip(), float(score))
            while len(self._known) > REMEMBERED_LINES:
                self._known.popitem(last=False)
        self.stats["recognized"] += len(todo)
        self.stats["reused"] += len(keys) - len(todo)
        lines = []
        for rect, key in zip(rects, keys):
            text, score = self._known.get(key, ("", 0.0))
            if key in self._known:
                self._known.move_to_end(key)
            if text and score >= 0.5:
                lines.append({"text": text, "score": round(score, 2), "px": rect})
        return lines


def describe(lines, space: str, limit: int = 160) -> list[str]:
    """Compact lines for cognition: "x,y text", the centre in the space SOMA clicks with.

    Every digit is a token for the local brain, so nothing decorates the point."""
    described = []
    for line in lines[:limit]:
        x0, y0, x1, y1 = line["box"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        point = f"{round(cx * 1000)},{round(cy * 1000)}" if space == "per_mille" else f"{cx:.3f},{cy:.3f}"
        described.append(f"{point} {line['text']}")
    return described
