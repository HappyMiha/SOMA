"""The world's self-diagnosis: whether each of SOMA's parts works right now, said plainly.

Everything read here is SOMA's own: its brains' answers and timings (soma.provider),
the local brain server's own HTTP API, the painter and the life loop. No process
list, window or file of another application is read.

One part heals itself. Live, after a reboot the local brain ran on the processor
although the GTX 1060 was there (1-6 minutes a thought instead of ~10 s). When the
local model sits on the processor although it has run on the graphics card here
before, it is first unloaded (the next thought loads it again, onto the card if
it is free); if it lands on the processor again, the local server is restarted
(soma.brain_host), at most once in RESTART_EVERY, and never while the painter
holds the card or while the server also keeps models that are not SOMA's.
"""

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHECK_EVERY = 30           # seconds between looks at the local brain server
LIVE_EVERY = 3             # seconds between updates of what works right now
RESTART_EVERY = 2 * 3600   # at most one restart of the local server in this long
STATE = "health.json"      # in the world's folder: whether the local brain has run on the card
ON_CARD = 0.9              # share of the model in video memory that counts as "on the card"

BRAIN_NAMES = {"claude": "Claude", "codex": "Codex", "openai": "віддалена модель"}
STATES = ("ok", "busy", "idle", "warn", "problem")  # worst last


@dataclass(frozen=True)
class Part:
    key: str
    title: str
    state: str    # one of STATES
    short: str    # a few words for the card
    detail: str   # a sentence for the details


def _gigabytes(size) -> str:
    return f"{size / 1024 ** 3:.1f} ГБ"


def _clock_in(seconds) -> str:
    return (datetime.now() + timedelta(seconds=seconds)).strftime("%H:%M")


class Health:
    def __init__(self, world_dir, provider, *, imaging=None, kernel=None, host=None, publish=None,
                 journal=None, clock=time.monotonic):
        self.world_dir, self.provider, self.imaging, self.kernel = Path(world_dir), provider, imaging, kernel
        self.host, self.publish, self.journal, self.clock = host, publish, journal, clock
        self.placement = None       # the local server's last answer (soma.provider.local_placement)
        self.remedy = ""            # what the world last did or found, said plainly
        self._checked = None
        self._unloaded = False      # the model was unloaded from the processor and not yet seen again
        self._restarted_at = None
        self._stop = threading.Event()
        self._thread = None

    # ── the world's memory of its own card ────────────────────────────────
    def _state(self) -> dict:
        try:
            return json.loads((self.world_dir / STATE).read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _remember(self, **fields):
        state = {**self._state(), **fields}
        path = self.world_dir / STATE
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
            os.replace(temporary, path)
        except OSError:
            pass  # A diagnosis must never cost a decision.

    # ── looking ───────────────────────────────────────────────────────────
    def tick(self):
        """One look: the local server every CHECK_EVERY, what works right now every time."""
        now = self.clock()
        if self._checked is None or now - self._checked >= CHECK_EVERY:
            self._checked = now
            try:
                self.placement = self.provider.local_placement()
            except Exception:
                self.placement = None
            self._heal()
        if self.publish is not None:
            self.publish({"parts": self.parts(), "remedy": self.remedy})

    def _heal(self):
        reading = self.placement
        if not reading or not reading.get("reachable") or not reading.get("loaded") or not reading.get("size"):
            return
        if reading["vram"] >= ON_CARD * reading["size"]:
            if not self._state().get("local_on_card_seen"):
                self._remember(local_on_card_seen=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            if self._unloaded or self.remedy:
                self.remedy = "Локальний мозок знову на відеокарті."
            self._unloaded = False
            return
        if reading["vram"] > 0 or not self._state().get("local_on_card_seen"):
            return  # partly on the card, or this PC never ran it there: nothing to restore
        if getattr(self.imaging, "painting", False):
            return  # the painter holds the card; the model goes back after the painting
        if reading.get("others"):
            self.remedy = ("Локальний мозок на процесорі, але Ollama зараз тримає й інші моделі ("
                           + ", ".join(reading["others"][:3]) + "), тому SOMA її не перезапускає.")
            return
        if not self._unloaded:
            self._unloaded = True
            self.provider.release_local()
            self.remedy = "Локальний мозок опинився на процесорі: SOMA вивантажила його, щоб він повернувся на відеокарту."
            self._journal("unloaded")
            return
        now = self.clock()
        if (self.host is not None and getattr(self.host, "available", False) and
                (self._restarted_at is None or now - self._restarted_at >= RESTART_EVERY)):
            self._restarted_at, self._unloaded = now, False
            try:
                self.host.restart()
                self.remedy = "Ollama не бачила відеокарту (так буває після старту ПК): SOMA перезапустила її."
                self._journal("restarted")
            except Exception as exc:
                self.remedy = "Не вдалося перезапустити Ollama: " + type(exc).__name__
            return
        self.remedy = ("Відеокарту не знайдено навіть після перезапуску Ollama: перевір, чи підключена "
                       "eGPU, і перезапусти Ollama, коли вона з'явиться.")

    def _journal(self, did):
        if self.journal is not None:
            try:
                self.journal("health.remedy", {"part": "local", "did": did, "why": self.remedy})
            except Exception:
                pass

    # ── saying it ─────────────────────────────────────────────────────────
    def parts(self) -> list[Part]:
        found = [self._local(), *self._remote_brains(), self._painter(), self._body()]
        return [part for part in found if part is not None]

    def _routes(self) -> dict:
        return self.provider.metrics.get("routes", {})

    def _local(self) -> Part | None:
        config = self.provider.config
        if config.mode not in {"local", "hybrid"} or not config.local_model:
            return None
        title, model = "Локальний мозок", config.local_model
        thinking = self.provider.metrics.get("thinking_with") == "local"
        last = self._routes().get("local")
        took = f"; остання думка {last['seconds']:.0f} с" if last and last.get("ok") else ""
        reading = self.placement
        if reading is None:
            return Part("local", title, "busy" if thinking else "idle", "мозок: перевіряю",
                        f"{model}: SOMA ще не спитала сервер моделей, де він.")
        if not reading.get("reachable"):
            return Part("local", title, "problem", "мозок: Ollama мовчить",
                        "Локальний сервер моделей (Ollama) не відповідає.")
        if not reading.get("loaded"):
            return Part("local", title, "busy" if thinking else "idle",
                        "мозок: завантажується" if thinking else "мозок спить",
                        f"{model} вивантажено; завантажиться з першою думкою{took}.")
        size, vram = reading["size"], reading["vram"]
        if vram >= ON_CARD * size:
            return Part("local", title, "busy" if thinking else "ok", "мозок: GPU · думає" if thinking else "мозок: GPU",
                        f"{model} на відеокарті ({_gigabytes(vram)}){took}.")
        if vram > 0:
            return Part("local", title, "warn", "мозок: частково GPU",
                        f"{model}: {vram * 100 // size}% на відеокарті, решта на процесорі — повільніше{took}.")
        return Part("local", title, "problem", "мозок: CPU — повільно",
                    f"{model} працює на процесорі: одна думка триває хвилини{took}.")

    def _remote_brains(self) -> list:
        config, provider = self.provider.config, self.provider
        brains = []
        if getattr(config, "deep_api", "") and config.deep_api != getattr(config, "remote_api", ""):
            brains.append(("deep", config.deep_api, "Глибокий мозок"))
        if config.mode in {"remote", "hybrid"} and getattr(config, "remote_api", ""):
            brains.append(("remote", config.remote_api, "Віддалений мозок"))
        parts = []
        resting = getattr(provider, "_rest_until", {})
        for route, api, title in brains:
            name = BRAIN_NAMES.get(api, api)
            last = self._routes().get(route) or {}
            rest = max(0.0, resting.get(route, 0.0) - time.monotonic())
            if provider.metrics.get("thinking_with") == route:
                parts.append(Part(route, title, "busy", f"{name} · думає", f"{name} думає зараз."))
            elif not provider.budget.available():
                parts.append(Part(route, title, "warn", f"{name}: бюджет",
                                  f"Денний бюджет віддалених запитів вичерпано; знову з {_clock_in(provider.budget.resets_in())}."))
            elif rest and "not logged in" in last.get("error", ""):
                parts.append(Part(route, title, "problem", f"{name}: не ввійшов",
                                  f"{name} просить увійти в обліковий запис (у його CLI)."))
            elif rest:
                parts.append(Part(route, title, "warn", f"{name}: ліміт до {_clock_in(rest)}",
                                  f"{name} вичерпав ліміт підписки і відпочиває до {_clock_in(rest)}."))
            elif last and not last.get("ok"):
                parts.append(Part(route, title, "warn", f"{name}: збій",
                                  f"Остання спроба {name} не вдалася ({last.get('error', '')})."))
            else:
                took = f"; остання думка {last['seconds']:.0f} с" if last.get("ok") else ""
                parts.append(Part(route, title, "ok", name, f"{name} готовий{took}."))
        return parts

    def _painter(self) -> Part | None:
        imaging = self.imaging
        if imaging is None:
            return None
        if not getattr(imaging, "available", False):
            return Part("painter", "Художник", "idle", "без художника",
                        "Художника на відеокарті немає; аватар малює код.")
        last = getattr(imaging, "last_seconds", None)
        took = f"; останнє полотно за {last:.0f} с" if last else ""
        if getattr(imaging, "painting", False):
            return Part("painter", "Художник", "busy", "малює…", "Художник малює на відеокарті.")
        if getattr(self.kernel, "_selfie_failures", 0) >= 2:
            return Part("painter", "Художник", "warn", "художник: збої", "Художник двічі не зміг намалювати.")
        return Part("painter", "Художник", "ok", "художник", f"Художник готовий{took}.")

    def _body(self) -> Part:
        kernel = self.kernel
        title = "Очі й руки"
        if kernel is None:
            return Part("body", title, "idle", "ще не прокинувся", "Мешканець ще не прокинувся.")
        state = getattr(getattr(kernel, "state", None), "value", "")
        if state == "OBSERVE_AND_LEARN":
            return Part("body", title, "busy", "вчиться", "Дивиться демонстрацію: його руки вимкнені.")
        if getattr(kernel, "_private", False):
            return Part("body", title, "idle", "очі заплющені", "Відкрито вікно власника: він не дивиться й не діє.")
        if state == "ASLEEP":
            return Part("body", title, "idle", "спить", "Сеанс Windows заблоковано або ПК спить.")
        if getattr(kernel, "_activity", "") == "acting":
            return Part("body", title, "busy", "діє", "Діє мишею й клавіатурою.")
        return Part("body", title, "ok", "бачить", "Бачить екран і може діяти.")

    # ── living alongside ──────────────────────────────────────────────────
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="soma-health", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                pass  # The diagnosis looks again in a moment; it never stops a life.
            self._stop.wait(LIVE_EVERY)

    def stop(self):
        self._stop.set()
