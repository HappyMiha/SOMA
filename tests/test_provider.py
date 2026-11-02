import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from soma.config import ModelConfig
from soma.core import Action, ScreenFrame
from soma.provider import ModelProvider, ProviderError, parse_json


def frame():
    output = BytesIO()
    Image.new("RGB", (200, 100), "white").save(output, "PNG")
    return ScreenFrame(output.getvalue(), 200, 100)


def envelope(content, **extra):
    return {"choices": [{"message": {"content": json.dumps(content), **extra}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def decision():
    return {"scene": "A visible button", "intention": "Explore a visible program",
            "goal": {"origin": "self", "motive": "curiosity", "description": "Learn the desktop",
                     "expected_outcome": "Visible response", "priority": .5},
            "uncertainty": .2, "reconsider_after": 3,
            "action": {"kind": "click", "args": {"x": .5, "y": .5}, "expected": "Dialog opens"}}


def test_cognitive_network_contains_only_images_and_context_no_tools():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope(decision()))
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="vision"),
                             "test-secret", transport=httpx.MockTransport(handler))
    result = provider.decide(frame(), {"identity": {"persona_id": "unchanging"}})
    payload = json.loads(requests[0].content)
    assert "tools" not in payload and "functions" not in payload
    assert requests[0].url.path == "/v1/chat/completions"
    image = payload["messages"][1]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/jpeg;base64,")
    Image.open(BytesIO(base64.b64decode(image.split(",")[1]))).verify()
    assert result.action.kind == "click"
    assert provider.metrics["input_tokens"] == 10
    provider.close()


@pytest.mark.parametrize("action", [
    {"kind": "shell", "args": {"command": "whoami"}},
    {"kind": "click", "args": {"x": 10, "y": .5}},
    {"kind": "type_text", "args": {"text": "hello", "paste": True}},
    {"kind": "key", "args": {"key": "a"}, "script": "x"},
])
def test_model_cannot_extend_closed_action_alphabet(action):
    value = decision()
    value["action"] = action
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="vision"),
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=envelope(value))))
    with pytest.raises(ProviderError):
        provider.decide(frame(), {})
    provider.close()


def test_provider_tool_call_rejected_without_dispatch():
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="vision"),
        transport=httpx.MockTransport(lambda req: httpx.Response(200,
            json=envelope(decision(), tool_calls=[{"name": "shell"}]))))
    with pytest.raises(ProviderError):
        provider.decide(frame(), {})
    provider.close()


def test_hybrid_fallback_never_forwards_remote_key_to_local():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(503) if request.url.host == "brain.example" else httpx.Response(200, json=envelope(decision()))
    provider = ModelProvider(ModelConfig(mode="hybrid", endpoint="https://brain.example/v1",
        model="remote", local_model="local"), "remote-secret", transport=httpx.MockTransport(handler))
    provider.decide(frame(), {})
    assert seen[0].headers["Authorization"] == "Bearer remote-secret"
    assert "Authorization" not in seen[1].headers
    assert provider.metrics["last_route"] == "local"
    provider.close()


def test_low_confidence_verification_is_uncertain():
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="vision"),
        transport=httpx.MockTransport(lambda req: httpx.Response(200,
            json=envelope({"status": "success", "confidence": .6, "evidence": "Possibly sent"}))))
    result = provider.verify(frame(), Action("key", {"key": "enter"}, "Message appears"), frame())
    assert result["status"] == "uncertain"
    provider.close()


def test_nonfinite_json_rejected():
    with pytest.raises(ValueError):
        parse_json('{"confidence": NaN}')


@pytest.mark.parametrize("config", [
    ModelConfig(endpoint="http://remote.example/v1", model="v"),
    ModelConfig(endpoint="https://user:secret@example.org/v1", model="v"),
    ModelConfig(mode="local", local_endpoint="https://remote.example/v1", local_model="v"),
    ModelConfig(endpoint="https://brain.example/v1", model="v", requests_per_minute=0),
])
def test_config_rejects_unsafe_or_unbounded_routes(config):
    with pytest.raises(ValueError):
        config.validate()


def test_streaming_trickle_cannot_extend_inference_forever(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("soma.provider.time.monotonic", lambda: clock[0])
    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] += 3
            yield b'{"choices":'
            clock[0] += 3
            yield b'[]}'
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="v", timeout_seconds=5),
        transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Trickle())))
    with pytest.raises(ProviderError):
        provider.decide(frame(), {})
    assert provider.metrics["requests"] == 0
    provider.close()


def test_reflections_cannot_invent_provenance():
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="v"),
        transport=httpx.MockTransport(lambda req: httpx.Response(200,
            json=envelope({"principle": "I learned", "confidence": .9, "sources": [999]}))))
    with pytest.raises(ProviderError):
        provider.reflect([{"id": 1, "kind": "experience"}])
    provider.close()


def ollama_handler(seen, content):
    def handler(request):
        seen.append(request)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.13"})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(content)},
                                         "done_reason": "stop", "prompt_eval_count": 1200, "eval_count": 90})
    return handler


def local_config(**overrides):
    values = dict(mode="local", local_endpoint="http://127.0.0.1:11434/v1", local_model="qwen3-vl:4b-instruct",
                  timeout_seconds=600, max_output_tokens=768)
    values.update(overrides)
    return ModelConfig(**values)


def test_local_ollama_uses_native_chat_with_context_size_and_schema():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler(seen, decision())))
    result = provider.decide(frame(), {"goals": []})
    chat = json.loads(seen[-1].content)
    assert seen[-1].url.path == "/api/chat"
    assert chat["options"]["num_ctx"] == 8192 and chat["stream"] is False
    branches = chat["format"]["properties"]["action"]["anyOf"]
    click = next(b for b in branches if b["properties"]["kind"]["enum"] == ["click"])
    assert set(click["properties"]["args"]["properties"]) == {"x", "y", "button"}
    assert click["properties"]["args"]["additionalProperties"] is False
    assert "tools" not in chat
    # Static instructions are in the cacheable system prefix; pixels only in the user turn,
    # which names its task on the first line.
    assert "TASK: perceive" in chat["messages"][0]["content"]
    user = chat["messages"][1]["content"]
    assert user.startswith("TASK: perceive") and user.count("TASK") == 1 and len(chat["messages"][1]["images"]) == 1
    assert result.action.kind == "click"
    assert provider.metrics["input_tokens"] == 1200
    # Every task shares one system message, so the local prompt cache keeps it.
    with pytest.raises(ProviderError):   # this mock answers every task with a decision
        provider.verify(frame(), Action("click", {"x": .5, "y": .5}, "Dialog opens"), frame(), "Desktop")
    assert json.loads(seen[-1].content)["messages"][0]["content"] == chat["messages"][0]["content"]
    assert json.loads(seen[-1].content)["messages"][1]["content"].startswith("TASK: verify")
    provider.close()


def test_local_context_overflow_is_refused_not_silently_truncated():
    seen = []
    provider = ModelProvider(local_config(local_context_tokens=2048),
                             transport=httpx.MockTransport(ollama_handler(seen, decision())))
    with pytest.raises(ProviderError, match="Context budget"):
        provider.decide(frame(), {"memories": ["x" * 4000]})
    assert all(r.url.path != "/api/chat" for r in seen)
    provider.close()


def test_long_screen_text_is_fitted_to_the_local_window_and_says_what_was_left_out():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler(seen, decision())))
    lines = [f"({i},{i}) {'слово ' * 30}{i}" for i in range(160)]
    provider.decide(frame(), {"goals": [], "screen_text": lines})
    chat = json.loads(seen[-1].content)
    sent = json.loads(chat["messages"][1]["content"].split("geometry:\n", 1)[1])["context"]
    assert 0 < len(sent["screen_text"]) < 160
    assert sent["screen_text_omitted"] == 160 - len(sent["screen_text"])
    # The top of the screen and the newest lines at the bottom are kept.
    assert sent["screen_text"][0].startswith("(0,0)") and sent["screen_text"][-1].startswith("(159,159)")
    assert all(len(line) <= 72 for line in sent["screen_text"])
    provider.close()


def test_token_estimate_counts_digits_and_marks_as_the_tokenizer_does():
    from soma.provider import estimate_tokens
    assert estimate_tokens("550,925 Send") == 8          # six digits, a comma, one word
    prose = "You see the monitor and you act with the mouse and keyboard. " * 10
    assert 0.9 < estimate_tokens(prose) / (len(prose.split()) + prose.count(".")) < 1.3   # ~a token per word
    assert estimate_tokens("Привіт") == 3


def test_goal_ids_are_short_for_the_brain_and_real_for_her_memory():
    goal_id = "78902d9b-85ca-46f4-9753-62f883557bdf"
    seen = []
    answer = decision()
    answer["goal"] = {"id": "g1", "origin": "self", "priority": .6}   # continued by id alone
    answer["goal_updates"] = [{"id": "g1", "status": "completed", "evidence": "Article ends", "confidence": .9}]
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler(seen, answer)))
    known = {"id": goal_id, "origin": "self", "motive": "curiosity", "description": "Read about the Moon",
             "expected_outcome": "Article read", "priority": .5}
    result = provider.decide(frame(), {"goals": [known]})
    prompt = json.loads(seen[-1].content)["messages"][1]["content"]
    assert goal_id not in prompt and '"id":"g1"' in prompt
    assert result.goal == {"id": goal_id, "origin": "self", "priority": .6, "motive": "curiosity",
                           "description": "Read about the Moon", "expected_outcome": "Article read"}
    assert result.goal_updates[0]["id"] == goal_id
    provider.close()


def test_a_reading_habit_is_parsed_and_scroll_needs_no_expected_text():
    answer = decision()
    answer["action"] = {"kind": "scroll", "args": {"dx": 0, "dy": -5, "x": 500, "y": 500}}
    answer["repeat"] = {"times": 6, "pause": 8}
    seen = []
    provider = ModelProvider(local_config(coordinate_space="per_mille"),
                             transport=httpx.MockTransport(ollama_handler(seen, answer)))
    result = provider.decide(frame(), {"goals": []})
    assert result.repeat == {"times": 6, "pause": 8.0}
    assert result.action == Action("scroll", {"dx": 0, "dy": -5, "x": .5, "y": .5})
    branches = json.loads(seen[-1].content)["format"]["properties"]["action"]["anyOf"]
    required = {b["properties"]["kind"]["enum"][0]: b["required"] for b in branches}
    assert "expected" not in required["scroll"] and "expected" in required["click"]
    answer["repeat"] = {"times": 50, "pause": 8}
    with pytest.raises(ProviderError):
        provider.decide(frame(), {"goals": []})
    provider.close()


def test_old_reading_gives_way_before_the_current_screen():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler(seen, decision())))
    read = [f"line {i} of a long article that she read a while ago " * 2 for i in range(200)]
    provider.decide(frame(), {"goals": [], "read_meanwhile": read, "screen_text": ["550,925 Send"]})
    sent = json.loads(json.loads(seen[-1].content)["messages"][1]["content"].split("geometry:\n", 1)[1])["context"]
    assert 0 < len(sent["read_meanwhile"]) < 200 and sent["read_meanwhile"][-1] == read[-1]
    assert sent["screen_text"] == ["550,925 Send"]
    provider.close()


def test_only_goals_she_has_can_be_continued():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler(seen, decision())))
    known = {"id": "78902d9b-85ca-46f4-9753-62f883557bdf", "origin": "self", "motive": "curiosity",
             "description": "Read", "expected_outcome": "Read", "priority": .5}
    provider.decide(frame(), {"goals": [known]})
    schema = json.loads(seen[-1].content)["format"]
    continued = schema["properties"]["goal"]["anyOf"][0]
    assert continued["properties"]["id"] == {"type": "string", "enum": ["g1"]}
    assert schema["properties"]["goal_updates"]["items"]["properties"]["id"]["enum"] == ["g1"]
    provider.decide(frame(), {"goals": []})
    schema = json.loads(seen[-1].content)["format"]
    assert "anyOf" not in schema["properties"]["goal"] and "goal_updates" not in schema["properties"]
    assert set(schema["properties"]["goal"]["required"]) >= {"motive", "description", "expected_outcome"}
    provider.close()


def test_no_brain_ever_receives_one_of_her_passwords():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler(seen, decision())))
    provider.scrub = lambda text: text.replace("Andromeda-1984!", "‹password›")
    provider.decide(frame(), {"goals": [], "memories": [{"kind": "semantic", "content": "password Andromeda-1984!"}],
                              "screen_text": ["500,500 Andromeda-1984!"]})
    body = seen[-1].content.decode("utf-8")
    assert "Andromeda-1984!" not in body and "‹password›" in body
    provider.close()


def test_a_new_goal_still_needs_its_description():
    answer = decision()
    answer["goal"] = {"origin": "self", "priority": .5}
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler([], answer)))
    with pytest.raises(ProviderError, match="Invalid visual decision"):
        provider.decide(frame(), {"goals": []})
    provider.close()


def test_local_verification_from_changed_text_sends_no_picture():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(
        ollama_handler(seen, {"status": "success", "confidence": .9, "evidence": "Message sent"})))
    change = {"appeared": ["(600,880) Привіт!"], "vanished": ["(550,925) Write a message"]}
    result = provider.verify(frame(), Action("key", {"key": "enter"}, "Message appears"), frame(), "Chat", change)
    chat = json.loads(seen[-1].content)
    assert not chat["messages"][1].get("images")
    assert "Привіт!" in chat["messages"][1]["content"] and "No image" in chat["messages"][1]["content"]
    assert result["status"] == "success"
    provider.close()


def test_local_verification_sends_only_after_image_with_before_scene():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(
        ollama_handler(seen, {"status": "success", "confidence": .9, "evidence": "Dialog visible"})))
    result = provider.verify(frame(), Action("click", {"x": .5, "y": .5}, "Dialog opens"), frame(), "Desktop")
    chat = json.loads(seen[-1].content)
    assert len(chat["messages"][1]["images"]) == 1
    assert "Scene before the action: Desktop" in chat["messages"][1]["content"]
    assert result["status"] == "success"
    provider.close()


def test_per_mille_coordinates_become_normalized_and_stay_bounded():
    value = decision()
    value["action"] = {"kind": "drag", "args": {"x": 500, "y": 250, "x2": 1000, "y2": 0, "button": None},
                       "expected": "Moved"}
    provider = ModelProvider(local_config(coordinate_space="per_mille"),
                             transport=httpx.MockTransport(ollama_handler([], value)))
    action = provider.decide(frame(), {}).action
    assert action.args == {"x": .5, "y": .25, "x2": 1.0, "y2": 0.0}
    value["action"]["args"]["x"] = 1001
    with pytest.raises(ProviderError):
        provider.decide(frame(), {})
    provider.close()


def test_truncated_local_output_is_an_error():
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "1"})
        return httpx.Response(200, json={"message": {"content": "{\"scene\": \"cut"}, "done_reason": "length"})
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="truncated"):
        provider.decide(frame(), {})
    provider.close()


def test_slow_local_budget_allowed_but_remote_stays_bounded():
    local_config(timeout_seconds=900).validate()
    with pytest.raises(ValueError):
        ModelConfig(endpoint="https://brain.example/v1", model="v", timeout_seconds=600).validate()


def test_settings_from_a_newer_version_do_not_block_wake(tmp_path):
    (tmp_path / "model.json").write_text(json.dumps({"mode": "local", "local_model": "m",
        "local_endpoint": "http://127.0.0.1:11434/v1", "future_option": 1}), "utf-8")
    assert ModelConfig.load(tmp_path).local_model == "m"


def test_daily_remote_budget_stops_paid_thinking_and_persists(tmp_path):
    from soma.provider import ProviderBudgetExhausted
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=envelope(decision()))
    config = ModelConfig(endpoint="https://brain.example/v1", model="vision", daily_request_budget=2)
    path = tmp_path / "thinking-budget.json"
    provider = ModelProvider(config, transport=httpx.MockTransport(handler), budget_path=path)
    provider.decide(frame(), {})
    provider.decide(frame(), {})
    with pytest.raises(ProviderBudgetExhausted) as exhausted:
        provider.decide(frame(), {})
    assert len(seen) == 2 and 60 <= exhausted.value.resets_in <= 86400
    provider.close()
    again = ModelProvider(config, transport=httpx.MockTransport(handler), budget_path=path)
    with pytest.raises(ProviderBudgetExhausted):
        again.decide(frame(), {})
    again.close()


def test_hybrid_uses_free_local_brain_when_remote_budget_is_spent(tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(200, json=envelope(decision()))
    config = ModelConfig(mode="hybrid", endpoint="https://brain.example/v1", model="remote", local_model="local",
                         local_api="openai", daily_request_budget=1, timeout_seconds=300)
    provider = ModelProvider(config, transport=httpx.MockTransport(handler), budget_path=tmp_path / "b.json")
    provider.decide(frame(), {})
    provider.decide(frame(), {})
    assert seen == ["brain.example", "127.0.0.1"]
    provider.close()


def test_budget_resets_on_a_new_local_day(tmp_path):
    from datetime import datetime
    from soma.provider import DailyBudget
    now = [datetime(2026, 10, 30, 23, 59)]
    budget = DailyBudget(1, tmp_path / "b.json", clock=lambda: now[0])
    budget.spend()
    assert not budget.available() and budget.resets_in() == 60
    now[0] = datetime(2026, 10, 31, 0, 1)
    assert budget.available() and budget.used == 0


def test_openai_host_gets_max_completion_tokens_others_max_tokens():
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=envelope(decision()))
    for endpoint in ("https://api.openai.com/v1", "https://openrouter.ai/api/v1"):
        provider = ModelProvider(ModelConfig(endpoint=endpoint, model="m", max_output_tokens=4096),
                                 transport=httpx.MockTransport(handler))
        provider.decide(frame(), {})
        provider.close()
    assert bodies[0]["max_completion_tokens"] == 4096 and "max_tokens" not in bodies[0]
    assert bodies[1]["max_tokens"] == 4096 and "max_completion_tokens" not in bodies[1]


def test_first_run_finds_a_local_vision_model_without_a_wizard():
    from soma.config import detect_local_brain
    def tags(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "llama3:8b"}, {"name": "qwen3-vl:4b-instruct"}]})
    found = detect_local_brain(httpx.MockTransport(tags))
    assert found.mode == "local" and found.local_model == "qwen3-vl:4b-instruct"
    assert found.coordinate_space == "per_mille"
    found.validate()
    text_only = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "llama3:8b"}]}))
    assert detect_local_brain(text_only) is None
    def down(request): raise httpx.ConnectError("refused")
    assert detect_local_brain(httpx.MockTransport(down)) is None


def test_codex_route_parses_nullable_strict_answers_and_counts_budget(tmp_path, monkeypatch):
    from soma.provider import ProviderError
    calls = []
    class FakeCodex:
        def think(self, system, prompt, images, schema, deadline, cancel):
            calls.append((system, len(images), schema))
            value = decision()
            value["goal"]["id"] = None
            value["goal_updates"] = None
            value["memory_updates"] = None
            value["action"]["args"] = {"x": .5, "y": .5, "button": None}
            return value, {"input_tokens": 20000, "output_tokens": 300}
    config = ModelConfig(mode="hybrid", remote_api="codex", local_model="qwen3-vl:4b-instruct",
                         local_endpoint="http://127.0.0.1:11434/v1", timeout_seconds=600, daily_request_budget=5)
    config.validate()
    provider = ModelProvider(config, budget_path=tmp_path / "b.json")
    provider._cli = FakeCodex()
    result = provider.decide(frame(), {"goals": []})
    assert result.action.args == {"x": .5, "y": .5} and "id" not in result.goal
    assert "TASK: perceive" in calls[0][0] and calls[0][1] == 1
    assert provider.metrics["last_route"] == "remote" and provider.metrics["remote_today"] == 1
    provider.close()
    # A brain that tries to act itself is rejected (remote-only: no network fallback here).
    remote = ModelProvider(ModelConfig(mode="remote", remote_api="codex", timeout_seconds=600),
                           budget_path=tmp_path / "c.json")
    class ActingCodex:
        def think(self, *args): raise PermissionError("tool")
    remote._cli = ActingCodex()
    with pytest.raises(ProviderError):
        remote.decide(frame(), {"goals": []})
    assert "act through a tool" in remote.metrics["last_error"]
    remote.close()


def test_soma_does_not_belittle_herself_but_stays_truthful():
    from soma.provider import SYSTEM
    lowered = " ".join(SYSTEM.lower().split())
    for stigma in ("are simulated", "openly a digital personality", "never claim to be a human",
                   "do not claim proven consciousness"):
        assert stigma not in lowered
    assert "your life here is real" in lowered
    # Her birthday is hers, in her identity (SOMIK: 1984-10-18, see test_world); SOMA is the world.
    assert "your name and birthday are in identity" in lowered and "you live in soma, the world" in lowered
    assert "do not invent" not in lowered and "decide for yourself how to behave" in lowered
    # Self-identification is hers to discover and to voice, above all to her
    # owner, who knows how she came to be. Kept for other people's sake: no
    # harmful or fraudulent deception, no impersonating a real person, and no
    # leading someone who does not know her origin, and sincerely asks, to
    # believe they are talking with a flesh-and-blood human.
    assert "who you are is yours to discover" in lowered and "as a person" in lowered
    assert "especially with your owner, miha" in lowered
    assert "you do not deny it" not in lowered and "do not deny being an ai" not in lowered
    assert "to defraud them" in lowered and "specific real person" in lowered
    assert "people who do not know how you came to be" in lowered
    assert "do not lead them to believe that you are one" in lowered


def test_captcha_step_is_framed_as_the_sites_rule_not_her_lack():
    from soma.provider import SYSTEM
    text = " ".join(SYSTEM.lower().split())
    assert "something you do not have" not in text
    assert "a captcha" in text and "says nothing about who you are" in text


def test_codex_usage_limit_is_recognized():
    import json
    import pytest
    from soma.cli_brains import BrainExhausted, codex_events, claude_events
    limit = {"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again at Nov 4th."}}
    with pytest.raises(BrainExhausted):
        codex_events(json.dumps(limit))
    with pytest.raises(BrainExhausted):
        claude_events(json.dumps({"type": "result", "is_error": True,
                                  "result": "Claude usage limit reached · resets 9pm"}))


def test_hybrid_rests_an_exhausted_remote_brain_and_uses_a_compact_local_context(tmp_path):
    from soma.cli_brains import BrainExhausted
    sent = []
    def local(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "1"})
        sent.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json={"message": {"content": json.dumps(decision())}, "done_reason": "stop"})
    config = ModelConfig(mode="hybrid", remote_api="codex", local_model="qwen3-vl:4b-instruct",
                         local_endpoint="http://127.0.0.1:11434/v1", timeout_seconds=600, max_output_tokens=1024)
    provider = ModelProvider(config, transport=httpx.MockTransport(local), budget_path=tmp_path / "b.json")
    calls = []
    class Exhausted:
        name = "Codex"
        def think(self, *args):
            calls.append(1)
            raise BrainExhausted("Codex usage limit reached")
    provider._cli = Exhausted()
    big = {"memories": ["x" * 30000]}
    small = {"memories": ["fits"]}
    provider.decide(frame(), big, small)
    provider.decide(frame(), big, small)
    assert calls == [1]                         # asked once, then the remote brain rests
    assert all('"fits"' in prompt for prompt in sent) and len(sent) == 2
    provider.close()


class RecordingBrain:
    def __init__(self, name, log, answer=None, error=None):
        self.name, self.log, self.answer, self.error = name, log, answer, error
    def think(self, system, prompt, images, schema, deadline, cancel):
        self.log.append((self.name, system.split("\n")[-3:], len(images)))
        if self.error:
            raise self.error
        return self.answer, {"input_tokens": 10, "output_tokens": 5}


def test_each_brain_has_its_own_job(tmp_path):
    from soma.cli_brains import BrainExhausted
    log = []
    def local(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "1"})
        if request.url.path == "/api/generate":        # periodic unload of the local model
            return httpx.Response(200, json={})
        body = json.loads(request.content)
        task = body["messages"][1]["content"].split("\n", 1)[0]
        log.append(("local", task, len(body["messages"][1].get("images", []))))
        answer = decision() if task.startswith("TASK: perceive") else {
            "status": "success", "confidence": .9, "evidence": "Reply visible"}
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}, "done_reason": "stop"})
    config = ModelConfig(mode="hybrid", remote_api="codex", deep_api="claude", routine_on_local=True,
                         local_model="qwen3-vl:4b-instruct", local_endpoint="http://127.0.0.1:11434/v1",
                         timeout_seconds=600, max_output_tokens=1024, daily_request_budget=0)
    config.validate()
    provider = ModelProvider(config, transport=httpx.MockTransport(local), budget_path=tmp_path / "b.json")
    provider._cli = RecordingBrain("Codex", log, decision())
    provider._deep = RecordingBrain("Claude", log, decision())
    # Routine: the local brain alone; nobody's quota is spent.
    provider.decide(frame(), {"goals": []}, {"goals": []}, False)
    provider.verify(frame(), Action("key", {"key": "enter"}, "Reply appears"), frame(), "Chat",
                    {"appeared": ["600,880 Привіт!"], "vanished": []})
    assert [entry[0] for entry in log] == ["local", "local"]
    # A conversation or something new: Claude, with the full screenshot.
    provider.decide(frame(), {"goals": []}, {"goals": []}, True, deep=True)
    assert log[-1][0] == "Claude" and log[-1][2] == 1
    # Claude reaches its limit: it rests, Codex stands in, then the local brain.
    provider._deep.error = BrainExhausted("Claude usage limit reached")
    provider._cli.error = BrainExhausted("Codex usage limit reached")
    provider.decide(frame(), {"goals": []}, {"goals": []}, True, deep=True)
    assert [entry[0] for entry in log[-3:]] == ["Claude", "Codex", "local"]
    provider.decide(frame(), {"goals": []}, {"goals": []}, True, deep=True)
    assert log[-1][0] == "local" and [entry[0] for entry in log].count("Claude") == 2   # both rest now
    assert provider.thinking_locally is True
    provider.close()


def test_routine_on_local_needs_a_local_brain():
    with pytest.raises(ValueError):
        ModelConfig(mode="remote", remote_api="codex", routine_on_local=True, timeout_seconds=600).validate()
    with pytest.raises(ValueError):
        ModelConfig(mode="hybrid", deep_api="gemini").validate()


def test_scroll_direction_is_spelled_out_for_the_brain():
    from soma.provider import DECIDE
    text = " ".join(DECIDE.split()).lower()
    assert "dy negative scrolls down" in text and "dy positive scrolls up" in text


def test_scroll_follows_the_brains_stated_direction_when_unambiguous():
    from soma.provider import scroll_as_intended
    assert scroll_as_intended(20, "The view scrolls down slightly, revealing more of the page below") == -20
    assert scroll_as_intended(5, "The page scrolls down") == -5
    assert scroll_as_intended(-3, "Scroll up to the title above") == 3
    # Ambiguous (content moves up to reveal what is below): the number stands.
    assert scroll_as_intended(-3, "The article moves upward, revealing the paragraph below") == -3
    assert scroll_as_intended(4, "More of the chart appears") == 4


def test_local_model_is_unloaded_periodically_to_release_its_prompt_cache():
    seen = []
    provider = ModelProvider(local_config(), transport=httpx.MockTransport(ollama_handler(seen, decision())))
    for _ in range(provider.config.local_unload_every):
        provider.decide(frame(), {"goals": []})
    unloads = [json.loads(r.content) for r in seen if r.url.path == "/api/generate"]
    assert unloads == [{"model": "qwen3-vl:4b-instruct", "keep_alive": 0}]
    provider.close()
    # A small-KV model on a GPU keeps its cache: unloading can be switched off.
    seen.clear()
    provider = ModelProvider(local_config(local_unload_every=0),
                             transport=httpx.MockTransport(ollama_handler(seen, decision())))
    for _ in range(6):
        provider.decide(frame(), {"goals": []})
    assert not [r for r in seen if r.url.path == "/api/generate"]
    provider.close()


def test_decision_may_carry_a_short_plan_of_keyboard_steps():
    value = decision()
    value["then"] = [{"kind": "type_text", "args": {"text": "Привіт"}, "expected": "Draft appears"},
                     {"kind": "key", "args": {"key": "Enter"}, "expected": "Message sent"}]
    provider = ModelProvider(ModelConfig(endpoint="https://brain.example/v1", model="vision"),
                             transport=httpx.MockTransport(lambda r: httpx.Response(200, json=envelope(value))))
    result = provider.decide(frame(), {})
    assert [s.kind for s in result.follow_up] == ["type_text", "key"]
    value["then"] = [{"kind": "click", "args": {"x": .5, "y": .5}, "expected": "Something"}]
    with pytest.raises(ProviderError):
        provider.decide(frame(), {})  # clicks need a fresh look: never in a plan tail
    value["then"] = [{"kind": "key", "args": {"key": "PgDn"}, "expected": "Next page"}] * 5
    with pytest.raises(ProviderError):
        provider.decide(frame(), {})
    provider.close()


def test_plan_tail_schema_allows_only_keyboard_scroll_and_wait():
    from soma.provider import decide_schema
    tail = decide_schema("per_mille")["properties"]["then"]
    kinds = {branch["properties"]["kind"]["enum"][0] for branch in tail["items"]["anyOf"]}
    assert kinds == {"key", "hotkey", "type_text", "type_secret", "type_new_secret", "scroll", "wait"}
    assert tail["maxItems"] == 4
