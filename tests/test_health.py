import json
from types import SimpleNamespace

import httpx

from soma.config import ModelConfig
from soma.health import RESTART_EVERY, STATE, Health
from soma.provider import ModelProvider

GB = 1024 ** 3


class FakeProvider:
    def __init__(self, **config):
        self.config = SimpleNamespace(**{"mode": "hybrid", "local_model": "qwen3.5:4b", "deep_api": "claude",
                                         "remote_api": "codex", **config})
        self.metrics = {"thinking_with": "", "routes": {}}
        self._rest_until = {"remote": 0.0, "deep": 0.0}
        self.budget = SimpleNamespace(available=lambda: True, resets_in=lambda: 0)
        self.reading = None
        self.released = 0

    def local_placement(self):
        return self.reading

    def release_local(self):
        self.released += 1


class FakeHost:
    available = True

    def __init__(self):
        self.restarts = 0

    def restart(self):
        self.restarts += 1


def on(vram, size=3.4 * GB, loaded=True, others=()):
    return {"reachable": True, "loaded": loaded, "size": int(size), "vram": int(vram), "others": list(others)}


def health(tmp_path, provider, now, **kw):
    return Health(tmp_path, provider, host=kw.pop("host", FakeHost()), clock=lambda: now[0], **kw)


def part(watcher, key):
    return next(p for p in watcher.parts() if p.key == key)


def test_the_local_brain_on_the_card_is_said_plainly_and_remembered(tmp_path):
    provider, now = FakeProvider(), [0.0]
    watcher = health(tmp_path, provider, now)
    provider.reading = on(3.4 * GB)
    provider.metrics["routes"] = {"local": {"seconds": 11.6, "ok": True, "error": ""}}
    watcher.tick()
    local = part(watcher, "local")
    assert (local.state, local.short) == ("ok", "мозок: GPU") and "12 с" in local.detail
    assert json.loads((tmp_path / STATE).read_text("utf-8"))["local_on_card_seen"]
    provider.metrics["thinking_with"] = "local"
    assert part(watcher, "local").short == "мозок: GPU · думає"


def test_a_local_brain_stuck_on_the_processor_is_unloaded_then_its_server_restarted(tmp_path):
    # Live, 2026-11-03: Ollama started before the eGPU after a reboot; 1-6 minutes a thought.
    provider, now, host = FakeProvider(), [0.0], FakeHost()
    (tmp_path / STATE).write_text(json.dumps({"local_on_card_seen": "2026-11-03T13:05:00+00:00"}), "utf-8")
    watcher = health(tmp_path, provider, now, host=host)
    provider.reading = on(0)
    watcher.tick()
    assert part(watcher, "local").state == "problem" and provider.released == 1 and host.restarts == 0
    now[0] += 31
    provider.reading = on(0, loaded=False)                  # unloaded; the next thought loads it again
    watcher.tick()
    now[0] += 31
    provider.reading = on(0)                                # ... onto the processor once more
    watcher.tick()
    assert host.restarts == 1 and "перезапустила" in watcher.remedy
    now[0] += 31
    provider.reading = on(3.4 * GB)                          # the card is back
    watcher.tick()
    assert part(watcher, "local").state == "ok" and "знову на відеокарті" in watcher.remedy
    for _ in range(3):                                       # lost again soon: no second restart within the hour
        now[0] += 31
        provider.reading = on(0)
        watcher.tick()
    assert host.restarts == 1 and "eGPU" in watcher.remedy
    now[0] += RESTART_EVERY
    watcher.tick()
    assert host.restarts == 2


def test_nothing_is_restarted_without_a_card_seen_here_while_painting_or_with_others_loaded(tmp_path):
    provider, now, host = FakeProvider(), [0.0], FakeHost()
    watcher = health(tmp_path, provider, now, host=host)
    provider.reading = on(0)
    for _ in range(3):
        now[0] += 31
        watcher.tick()
    assert provider.released == 0 and host.restarts == 0     # this PC never ran it on a card
    (tmp_path / STATE).write_text(json.dumps({"local_on_card_seen": "yes"}), "utf-8")
    watcher.imaging = SimpleNamespace(available=True, painting=True, last_seconds=63.0)
    now[0] += 31
    watcher.tick()
    assert provider.released == 0 and part(watcher, "painter").short == "малює…"
    watcher.imaging.painting = False
    provider.reading = on(0, others=["llama3:8b"])
    now[0] += 31
    watcher.tick()
    assert provider.released == 0 and "llama3:8b" in watcher.remedy


def test_brains_painter_and_body_say_what_works_now(tmp_path):
    provider, now = FakeProvider(), [0.0]
    kernel = SimpleNamespace(state=SimpleNamespace(value="AWAKE/AUTONOMOUS"), _private=False, _activity="thinking")
    watcher = health(tmp_path, provider, now, kernel=kernel,
                     imaging=SimpleNamespace(available=True, painting=False, last_seconds=63.0))
    provider.reading = {"reachable": False, "loaded": False, "size": 0, "vram": 0, "others": []}
    import time
    provider._rest_until["remote"] = time.monotonic() + 3600
    provider.metrics["thinking_with"] = "deep"
    watcher.tick()
    shown = {p.key: p for p in watcher.parts()}
    assert shown["local"].short == "мозок: Ollama мовчить" and shown["local"].state == "problem"
    assert shown["deep"].short == "Claude · думає" and shown["remote"].short.startswith("Codex: ліміт до ")
    assert shown["painter"].state == "ok" and "63 с" in shown["painter"].detail
    assert shown["body"].short == "бачить"
    kernel.state = SimpleNamespace(value="OBSERVE_AND_LEARN")
    assert part(watcher, "body").short == "вчиться"
    kernel.state, kernel._private = SimpleNamespace(value="AWAKE/AUTONOMOUS"), True
    assert part(watcher, "body").short == "очі заплющені"


def test_a_painter_not_found_at_start_is_looked_for_again(tmp_path):
    # Live, right after a hard reset: "the painter's engine or model is missing" until the next start.
    from soma.imaging import Imaging
    painter = Imaging(tmp_path)
    assert painter.available is False
    (tmp_path / "engine").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "engine" / "sd-cli.exe").write_bytes(b"")
    (tmp_path / "models" / "sdxl_lightning_4step.safetensors").write_bytes(b"")
    assert painter.available is False                      # not every look: at most once a minute
    painter._looked -= Imaging.LOOK_AGAIN
    assert painter.available is True and painter.engine.name == "sd-cli.exe"


def test_the_provider_reads_where_its_local_model_sits_and_which_brain_thinks():
    asked = []
    def handler(request):
        asked.append(request.url.path)
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [
                {"name": "qwen3.5:4b", "model": "qwen3.5:4b", "size": 3_600_000_000, "size_vram": 3_600_000_000},
                {"name": "llama3:8b", "model": "llama3:8b", "size": 5, "size_vram": 0}]})
        return httpx.Response(200, json={"version": "0.40.13"})
    provider = ModelProvider(ModelConfig(mode="local", local_endpoint="http://127.0.0.1:11434/v1",
                                         local_model="qwen3.5:4b", local_api="ollama", timeout_seconds=600),
                             transport=httpx.MockTransport(handler))
    assert provider.local_placement() == {"reachable": True, "loaded": True, "others": ["llama3:8b"],
                                          "size": 3_600_000_000, "vram": 3_600_000_000}
    down = ModelProvider(ModelConfig(mode="local", local_endpoint="http://127.0.0.1:11434/v1",
                                     local_model="qwen3.5:4b", local_api="ollama", timeout_seconds=600),
                         transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    assert down.local_placement()["reachable"] is False
    assert ModelProvider(ModelConfig(mode="remote", endpoint="https://x.example/v1", model="m"),
                         transport=httpx.MockTransport(handler)).local_placement() is None


def test_the_widget_shows_a_line_of_what_works_and_every_part_in_the_details(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from soma import app as app_module
    from soma.health import Part
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module.LifeWidget, "bootstrap", lambda self: None)
    widget = app_module.LifeWidget(tmp_path / "SOMA")
    try:
        widget.show_health({"parts": [
            Part("local", "Локальний мозок", "problem", "мозок: CPU — повільно", "qwen3.5:4b працює на процесорі."),
            Part("deep", "Глибокий мозок", "ok", "Claude", "Claude готовий."),
            Part("body", "Очі й руки", "ok", "бачить", "Бачить екран і може діяти.")],
            "remedy": "SOMA вивантажила його."})
        line = widget.health_line.text()
        assert "мозок:&nbsp;CPU" in line and "#ef4444" in line and "Claude" in line and "бачить" not in line
        assert "Очі й руки" in widget.health_full.text() and "вивантажила" in widget.health_full.text()
        assert "Локальний мозок: qwen3.5:4b працює на процесорі." in widget.health_line.toolTip()
    finally:
        widget._quitting = True
        widget.tray.hide()
        widget.close()
        application.processEvents()
