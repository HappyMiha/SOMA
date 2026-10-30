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
