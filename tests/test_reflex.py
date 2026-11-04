import json

import httpx

from soma.config import ModelConfig
from soma.provider import ModelProvider
from soma.reflex import LOOK_AGAIN, Reflex, is_reflex_model, rule


def ollama(answers, tags=("qwen3.5:4b", "laya:latest", "laya:322m-multilingual-bf16"), asked=None, fail=False):
    """A local Ollama serving decision models at /v1/systemone."""
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": name} for name in tags]})
        if request.url.path == "/v1/systemone":
            body = json.loads(request.content)
            if asked is not None:
                asked.append(body)
            if fail:
                return httpx.Response(500, json={"error": "loading"})
            return httpx.Response(200, json={"answers": {name: {"noul": answers[name]} for name in body["questions"]}})
        return httpx.Response(200, json={})
    return httpx.MockTransport(handler)


def test_the_reflex_finds_a_pulled_laya_and_prefers_the_multilingual_one():
    assert Reflex(transport=ollama({})).model == "laya:322m-multilingual-bf16"   # her screens speak three languages
    assert Reflex(transport=ollama({}, tags=("qwen3.5:4b",))).model is None     # nothing is ever pulled from here
    assert Reflex(model="laya:latest", transport=ollama({})).model == "laya:latest"
    assert is_reflex_model("laya:latest") and not is_reflex_model("qwen3.5:4b")
    # Its own variant on the processor comes first: on the card Laya evicted SOMIK's brain.
    tags = ("qwen3.5:4b", "laya:latest", "laya:322m-multilingual-bf16", "laya-soma:cpu")
    assert Reflex(transport=ollama({}, tags=tags)).model == "laya-soma:cpu" and is_reflex_model("laya-soma:cpu")


def test_a_clear_prompt_stops_a_plan_without_asking_the_model():
    # Measured live: Laya missed a "(Y/n)" prompt; the plain rule catches it first.
    asked = []
    reflex = Reflex(transport=ollama({"asks": .1, "attention": .1}, asked=asked))
    verdict = reflex.judge("key y", "I move north-west", ["Really step into the pit? (Y/n)"])
    assert not verdict["go_on"] and verdict["by"] == "rule" and not asked
    assert reflex.judge("key l", "I move", [])["go_on"]   # only graphics changed: the pixels said it worked


def test_the_model_judges_what_came_up_and_stops_for_what_needs_a_look():
    asked = []
    calm = Reflex(transport=ollama({"asks": .05, "attention": .04}, asked=asked))
    assert calm.judge("key l", "I move one tile east", ["You hear a distant thump."]) == {
        "go_on": True, "why": "", "by": "laya", "asks": .05, "attention": .04}
    assert "You hear a distant thump." in asked[0]["state"] and asked[0]["keep_alive"] == "30m"
    alarmed = Reflex(transport=ollama({"asks": .08, "attention": .75}))
    verdict = alarmed.judge("key l", "I move", ["Spotted zombie! Safe mode is on."])
    assert not verdict["go_on"] and "needs a look" in verdict["why"] and "zombie" in verdict["why"]


def test_a_silent_model_leaves_the_judgment_to_the_rule_and_is_looked_for_later():
    clock = [0.0]
    reflex = Reflex(transport=ollama({}, fail=True), clock=lambda: clock[0])
    assert reflex.judge("key l", "I move", ["Warning: low battery"])["by"] == "rule"
    assert not reflex.judge("key l", "I move", ["Warning: low battery"])["go_on"]
    assert reflex.model is None                     # not asked again at once
    clock[0] += LOOK_AGAIN
    assert reflex.model == "laya:322m-multilingual-bf16"
    assert rule(["Lighting: dark"])["go_on"] and not rule(["Save changes?"])["go_on"]


def test_only_a_sure_it_worked_is_taken_as_an_outcome():
    sure = Reflex(transport=ollama({"worked": .96}))
    outcome = sure.outcome("key enter", "my reply appears in the chat", ["SOMIK 13:42", "Дякую, Міхо!"])
    assert outcome["status"] == "success" and outcome["confidence"] == .96 and "reflex" in outcome["evidence"]
    assert Reflex(transport=ollama({"worked": .54})).outcome("key enter", "Settings open", ["404"]) is None
    assert sure.outcome("key enter", "", ["x"]) is None and sure.outcome("key enter", "y", [], []) is None


def test_the_widget_says_which_reflex_judges(tmp_path):
    from types import SimpleNamespace
    from soma.health import Health
    reflex = Reflex(transport=ollama({}))
    provider = SimpleNamespace(config=SimpleNamespace(mode="remote", local_model="", deep_api="", remote_api="codex"),
                               metrics={"routes": {}}, _rest_until={"remote": 0.0, "deep": 0.0},
                               budget=SimpleNamespace(available=lambda: True, resets_in=lambda: 0))
    watcher = Health(tmp_path, provider, kernel=SimpleNamespace(reflex=reflex, state=None))
    part = lambda: next(p for p in watcher.parts() if p.key == "reflex")
    assert part().short == "рефлекс: правило"
    assert reflex.model and part().short == "рефлекс: Laya" and "multilingual" in part().detail


def test_the_local_brain_does_not_count_its_own_reflex_as_someone_elses_model():
    def handler(request):
        return httpx.Response(200, json={"models": [
            {"name": "qwen3.5:4b", "model": "qwen3.5:4b", "size": 3_400_000_000, "size_vram": 3_400_000_000},
            {"name": "laya:322m-multilingual-bf16", "size": 732_797_336, "size_vram": 732_797_336}]})
    provider = ModelProvider(ModelConfig(mode="local", local_endpoint="http://127.0.0.1:11434/v1",
                                         local_model="qwen3.5:4b", local_api="ollama", timeout_seconds=600),
                             transport=httpx.MockTransport(handler))
    assert provider.local_placement()["others"] == []   # Ollama may still be restarted when hung
    provider.close()
