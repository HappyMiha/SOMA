"""The hands' reflex: a quick judgment between two steps of a plan, without a thought.

While the hands carry out a plan the brain made (walk five squares, page through
an article, type and press Enter), each step is checked on the screen: its pixels
say whether anything happened, the text that came up says what. A small decision
model on this PC judges that text when it is there: Laya (Convai Innovations, an
encoder that answers yes/no questions in one pass instead of writing text),
served by the same local Ollama at /v1/systemone. Without it a plain rule does
the asking part. Either way an unclear moment ends the plan and the brain looks
again; the reflex never chooses an input itself.

Measured on SOMIK's PC (2026-11-04, GTX 1060): about 50-80 ms a judgment on the
card, 250-350 ms on the processor, seconds to load. The multilingual Laya (322M) told dialogs in German and
Ukrainian, a zombie coming into view and a loaded page from an ordinary game log
line, and was 0.94-0.98 sure of an input that visibly worked; it missed a
"(Y/n)" prompt, which the plain rule catches first. It could NOT tell a person's
message from routine text (Miha's message: "routine" 0.99, a clock: "person"
0.85), so who looks at what woke her stays with the brains.

Only the text read from her own frames is judged, inside SOMA (spec §4.1). No
model is ever downloaded from here: the owner pulls it into Ollama, and the
reflex finds it there.
"""

from __future__ import annotations

import re
import time

import httpx

# New text that asks for an answer: the next key of a plan could give one by
# accident (in a game "y" walks north-west and confirms a "(Y/n)" prompt alike).
# A dialog's own buttons, standing alone, also mean one opened.
CLEARLY_ASKS = re.compile(r"\(\s*y\s*/\s*n\s*\)|\[\s*y\s*/\s*n\s*\]|\byes\s*/\s*no\b|\bare you sure\b|"
                          r"\bconfirm\b|так\s*/\s*ні|ви впевнені|підтверд", re.IGNORECASE)
MAY_ASK = re.compile(r"\?|\breally\b|\bwarning\b|\berror\b|\bdanger\b|справді|увага|помилк|небезпе",
                     re.IGNORECASE)
BUTTONS = {"ok", "cancel", "yes", "no", "так", "ні", "скасувати", "гаразд"}
STATE_CHARS = 1200   # Laya reads 512 tokens: the step and the newest lines that came up
LOOK_AGAIN = 600     # a decision model that is missing or did not answer is looked for again after this
STOP_AT = 0.5        # a "yes" this likely to "it asks" or "it needs attention" ends the plan
SURE_IT_WORKED = 0.9  # only this sure an outcome is taken without the brain's own check
KEEP_LOADED = "30m"  # loading takes up to half a minute; a judgment then takes a blink
QUICK, LOADING = 8, 60  # seconds a judgment may take once loaded / while the model loads
# On a GPU the decision server reserves 16 slots of 8K context (2.7 GiB) and evicted
# SOMIK's brain to load; request options do not change that. A variant made from the
# pulled model with "PARAMETER num_gpu 0" and "PARAMETER num_ctx 1024" runs on the
# processor in 250-350 ms and takes nothing from the card (see README). Preferred.
OWN_VARIANT = "laya-soma"
QUESTIONS = {
    "asks": {"type": "noul", "instructions": "Does the new text ask the person at the computer something "
             "or wait for their answer (a question, a prompt, a confirmation, a dialog with buttons)?"},
    "attention": {"type": "noul", "instructions": "Does the new text tell of something unexpected that "
                  "needs a look before going on (danger, an error, a warning, someone writing, a new window)?"},
}
WORKED = {"worked": {"type": "noul", "instructions":
                     "Does the change on the screen show that the input had its expected result?"}}


def is_reflex_model(name: str, wanted: str = "") -> bool:
    """A model of SOMA's own reflex in the local server (not someone else's program)."""
    name = str(name)
    if wanted:  # "laya" means any of its tags; "laya:latest" only that one
        return name == wanted or (":" not in wanted and name.split(":")[0] == wanted)
    return name.split(":")[0].split("/")[-1] in {"laya", OWN_VARIANT}


def _asks_clearly(line: str) -> bool:
    return bool(CLEARLY_ASKS.search(line)) or line.strip().lower().strip(" []()<>") in BUTTONS


def rule(appeared) -> dict:
    """The plain rule, without a model: new text that asks something ends the plan."""
    for line in appeared:
        text = line.strip()
        if _asks_clearly(text) or MAY_ASK.search(text):
            return {"go_on": False, "why": f'new text came up: "{text[:120]}"', "by": "rule"}
    return {"go_on": True, "why": "", "by": "rule"}


class Reflex:
    def __init__(self, root="http://127.0.0.1:11434", model="", *, transport=None, clock=time.monotonic):
        self.root = root.rstrip("/")
        self.wanted = model
        self.clock = clock
        self._client = httpx.Client(timeout=QUICK, transport=transport, trust_env=False)
        self._model, self._next_look, self._loaded = None, 0.0, False

    @property
    def model(self) -> str | None:
        """The decision model pulled into the local server, looked for at most every LOOK_AGAIN.
        The multilingual one is preferred: her screens speak Ukrainian, German and English."""
        if self._model is None and self.clock() >= self._next_look:
            self._next_look = self.clock() + LOOK_AGAIN
            try:
                response = self._client.get(self.root + "/api/tags", timeout=3)
                response.raise_for_status()
                names = [str(m["name"]) for m in response.json()["models"]]
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return None
            found = sorted((n for n in names if is_reflex_model(n, self.wanted)),
                           key=lambda n: (not n.startswith(OWN_VARIANT), "multilingual" not in n, n))
            self._model, self._loaded = (found[0] if found else None), False
        return self._model

    def _ask(self, state: str, questions: dict) -> dict | None:
        """{question: probability of yes}, or None when the model is missing or did not answer."""
        model = self.model
        if model is None:
            return None
        try:
            response = self._client.post(self.root + "/v1/systemone", timeout=QUICK if self._loaded else LOADING,
                                         json={"model": model, "state": state, "questions": questions,
                                               "keep_alive": KEEP_LOADED})
            response.raise_for_status()
            answers = response.json()["answers"]
            likely = {name: float(answers[name]["noul"]) for name in questions}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # Not answering now: the plain rule judges, and the model is looked for again later.
            self._model, self._next_look, self._loaded = None, self.clock() + LOOK_AGAIN, False
            return None
        self._loaded = True
        return likely

    def judge(self, step: str, expected: str, appeared) -> dict:
        """Whether the plan goes on after one step, from the text that came up with it."""
        appeared = [str(line) for line in appeared if str(line).strip()]
        if not appeared:
            return {"go_on": True, "why": "", "by": "pixels"}  # only graphics changed: the pixels said it worked
        clearly = next((line for line in appeared if _asks_clearly(line)), None)
        if clearly:  # Laya missed a "(Y/n)" prompt when measured; the rule never does
            return {"go_on": False, "why": f'new text asks: "{clearly.strip()[:120]}"', "by": "rule"}
        state = (f"After the input {step}" + (f" (expected: {expected})" if expected else "")
                 + ", this text came up on the screen:\n" + "\n".join(appeared)[-STATE_CHARS:])
        likely = self._ask(state, QUESTIONS)
        if likely is None:
            return rule(appeared)
        stop = [name for name, value in likely.items() if value >= STOP_AT]
        newest = appeared[-1].strip()[:120]
        why = ("" if not stop else
               f'new text asks something: "{newest}"' if "asks" in stop else
               f'new text needs a look: "{newest}"')
        return {"go_on": not stop, "why": why, "by": "laya", **{name: round(v, 3) for name, v in likely.items()}}

    def outcome(self, step: str, expected: str, appeared, vanished=()) -> dict | None:
        """"It worked", when the text that came up shows it beyond doubt; None to let the brain check."""
        appeared, vanished = [str(x) for x in appeared], [str(x) for x in vanished]
        if not expected or not (appeared or vanished):
            return None
        came = "\n".join(appeared)[-STATE_CHARS // 2:]
        went = "\n".join(vanished)[-STATE_CHARS // 3:]
        state = (f"Input: {step}\nExpected result: {expected}\nText that came up on the screen after it:\n"
                 f"{came or '(none)'}\nText that went away:\n{went or '(none)'}")
        likely = self._ask(state, WORKED)
        if likely is None or likely["worked"] < SURE_IT_WORKED:
            return None
        shown = (appeared[0] if appeared else vanished[0]).strip()[:100]
        return {"status": "success", "confidence": round(likely["worked"], 2),
                "evidence": f'The text on the screen shows it ("{shown}"), read by my reflex.'}

    def release(self):
        """Give the graphics card back (the painter needs all of it); the next judgment loads it again."""
        if self._model:
            try:
                self._client.post(self.root + "/api/generate", timeout=5, json={"model": self._model, "keep_alive": 0})
            except httpx.HTTPError:
                pass
            self._loaded = False

    def close(self):
        self._client.close()
