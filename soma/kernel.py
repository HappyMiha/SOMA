"""Durable life scheduler, with a visual observation between every input."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import json
import threading
import time

from PIL import Image, ImageChops, ImageStat

from soma.core import Action, LifeState, utc_now
from soma.provider import ProviderCancelled, ProviderError, bounded_text, confidence


def visual_delta(before, after) -> float:
    with Image.open(BytesIO(before.png)) as first, Image.open(BytesIO(after.png)) as second:
        first = first.convert("RGB").resize((160, 100))
        second = second.convert("RGB").resize((160, 100))
        return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / (3 * 255)


class LifeKernel:
    def __init__(self, store, port, provider, recorder, status=None):
        self.store, self.port, self.provider, self.recorder = store, port, provider, recorder
        self.status_callback = status or (lambda value: None)
        self.state = LifeState.BIRTH
        self.intention = "Прокидаюся й оглядаю свій комп’ютер"
        self.stop_event = threading.Event()
        self._teach = threading.Event()
        self._finish_teach = threading.Event()
        self._sleep = threading.Event()
        self._resume = threading.Event()
        self._epoch = 0
        self._last_demo_capture = 0
        self._lessons = []
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="soma-inference")
        self._last_frame = None
        self._last_reflection = time.monotonic()
        self._cycles = 0
        self._retry_delay = 3

    def _status(self, detail=""):
        self.status_callback({"state": self.state.value, "intention": self.intention,
                              "detail": detail, "cycles": self._cycles,
                              "inference": dict(self.provider.metrics)})

    def _checkpoint(self):
        self.store.checkpoint({"state": self.state.value, "intention": self.intention,
                               "last_seen": utc_now(), "cycles": self._cycles,
                               "last_frame_id": self._last_frame.frame_id if self._last_frame else None,
                               "pending_lessons": self._lessons})

    def request_teaching(self):
        # Synchronous input inhibition: never wait for the model/network to return.
        self.port.set_observing(True)
        self._epoch += 1
        self._teach.set()

    def finish_teaching(self):
        self._finish_teach.set()

    def set_sensitive(self, sensitive: bool):
        if self.recorder.active:
            self.recorder.pause_recording(sensitive)

    def suspend(self):
        self.port.set_observing(True)
        self._epoch += 1
        self._sleep.set()
        self._resume.clear()

    def resume(self):
        self._epoch += 1
        self._sleep.clear()
        self._resume.set()

    def stop(self):
        self.port.set_observing(True)
        self.stop_event.set()
        self.provider.cancel.set()

    def _controls(self):
        def finish_demo(take_frame):
            capture_error = None
            try:
                if take_frame and not self.recorder.paused:
                    self.recorder.capture(self.port.capture_monitor_pixels())
            except Exception as error:
                capture_error = error
            finally:
                # Even a locked desktop or capture failure must stop global hooks.
                trace = self.recorder.stop()
            self._lessons.append(trace)
            self._epoch += 1
            self.state = LifeState.WAKE_RECOVER
            self._last_frame = None
            # Make the pending lesson durable before any autonomous input resumes.
            self._checkpoint()
            if not self._sleep.is_set() and not self.stop_event.is_set():
                self.port.set_observing(False)
            self._status("Демонстрацію збережено; узагальню навичку")
            if capture_error is not None:
                self.store.append_event("demonstration_capture_failed", {"id": trace["id"], "type": type(capture_error).__name__})
                raise capture_error

        if self._teach.is_set() and not self.recorder.active and not self._sleep.is_set() and not self.stop_event.is_set():
            self._teach.clear()
            self.recorder.start()
            self.state = LifeState.OBSERVE_AND_LEARN
            try:
                self._checkpoint()
                self._status("Запис демонстрації видимий; власне введення вимкнено")
                self.recorder.capture(self.port.capture_monitor_pixels())
                self._last_demo_capture = time.monotonic()
            except Exception:
                finish_demo(False)
                raise
        if self.recorder.active:
            if self._finish_teach.is_set() or self._sleep.is_set() or self.stop_event.is_set():
                self._finish_teach.clear()
                finish_demo(not self._sleep.is_set() and not self.stop_event.is_set())
            elif not self.recorder.paused and time.monotonic() - self._last_demo_capture >= 0.4:
                try:
                    self.recorder.capture(self.port.capture_monitor_pixels())
                    self._last_demo_capture = time.monotonic()
                except Exception:
                    finish_demo(False)
                    raise
        if self._sleep.is_set() and self.state != LifeState.ASLEEP:
            self.state = LifeState.ASLEEP
            self.port.release_all()
            self._checkpoint()
            self._status("Графічний сеанс недоступний")
        elif (not self._sleep.is_set() and not self.stop_event.is_set() and
              not self.recorder.active and not self._teach.is_set() and
              (self.state == LifeState.ASLEEP or self._resume.is_set())):
            self._resume.clear()
            self.state = LifeState.WAKE_RECOVER
            self._last_frame = None
            self.port.set_observing(False)
            self._checkpoint()

    def _wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._controls()
            self.stop_event.wait(min(0.1, max(0, deadline - time.monotonic())))

    def _rest(self, frame, seconds):
        """Wake early on visible change without spending inference on polling."""
        deadline = time.monotonic() + seconds
        epoch = self._epoch
        next_probe = time.monotonic() + min(2, seconds)
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._controls()
            if self._epoch != epoch or self.recorder.active or self._sleep.is_set():
                return
            if time.monotonic() >= next_probe:
                current = self.port.capture_monitor_pixels()
                if (current.geometry()["monitors"] != frame.geometry()["monitors"] or
                        (current.width, current.height) != (frame.width, frame.height) or
                        visual_delta(frame, current) > 0.015):
                    return
                next_probe = time.monotonic() + 2
            self.stop_event.wait(min(.1, max(0, deadline - time.monotonic())))

    def _infer(self, function, *args):
        epoch = self._epoch
        future = self._executor.submit(function, *args)
        while not future.done():
            self._controls()
            if self.stop_event.wait(0.1):
                self.provider.cancel.set()
                raise ProviderCancelled("Inference cancelled during shutdown")
        result = future.result()
        self._controls()
        if epoch != self._epoch or self.recorder.active or self._sleep.is_set() or self.stop_event.is_set():
            raise ProviderCancelled("Discarded decision after lifecycle transition")
        return result

    def _capture(self):
        frame = self.port.capture_monitor_pixels()
        self.store.save_frame(frame)
        self._last_frame = frame
        return frame

    def _settle(self, before):
        previous, stable, latest = before, 0, before
        deadline = time.monotonic() + 3
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            self._wait(0.2)
            if self.recorder.active or self._sleep.is_set():
                raise ProviderCancelled("Verification interrupted")
            latest = self._capture()
            stable = stable + 1 if visual_delta(previous, latest) < 0.003 else 0
            if stable >= 2:
                break
            previous = latest
        return latest

    def _recover(self, frame, pending):
        prompt = 'Reconcile these interrupted or uncertain inputs using ONLY this fresh screenshot. '
        prompt += 'Never replay them. Return {"results":[{"id":str,"status":"success|failure|uncertain",'
        prompt += '"confidence":0..1,"evidence":str}]}. Ambiguous evidence means uncertain. '
        prompt += json.dumps(pending, ensure_ascii=False)
        result = self._infer(self.provider._request, prompt, [frame])
        valid_ids = {p["id"] for p in pending}
        for item in result.get("results", []):
            if item.get("id") not in valid_ids or item.get("status") not in {"success", "failure", "uncertain"}:
                continue
            certainty = confidence(item.get("confidence"))
            evidence = bounded_text(item.get("evidence"))
            if certainty >= 0.8 and item["status"] != "uncertain":
                self.store.finish_action(item["id"], {"status": item["status"],
                    "confidence": certainty, "evidence": evidence, "recovered": True}, frame.frame_id)
        return not self.store.pending_actions()

    def _learn(self):
        trace = self._lessons[0]
        from soma.core import Monitor, ScreenFrame
        from soma.demonstration import learning_evidence

        # Only paths written by the recorder inside SOMA's frame store are read.
        root = (self.store.data_dir / "frames").resolve()
        available = []
        for recorded in trace.get("frames", []):
            # Portable backups retain frame IDs; recorded absolute paths belong
            # to the old installation and are never followed.
            candidate = self.store.frame_path(recorded["frame_id"])
            if candidate and candidate.resolve().is_relative_to(root) and candidate.is_file():
                available.append((recorded, candidate))
        frames, mapping = [], []
        count = min(8, len(available))
        indices = sorted({round(index * (len(available) - 1) / max(1, count - 1)) for index in range(count)})
        for index in indices:
            recorded, candidate = available[index]
            geometry = recorded.get("geometry", {})
            with Image.open(candidate) as image:
                frames.append(ScreenFrame(candidate.read_bytes(), image.width, image.height,
                    geometry.get("x", 0), geometry.get("y", 0),
                    tuple(Monitor(**monitor) for monitor in geometry.get("monitors", [])),
                    frame_id=recorded["frame_id"], captured_monotonic=recorded.get("captured_at", 0)))
            mapping.append({"image_index": len(frames) - 1, "frame_id": recorded["frame_id"],
                            "captured_at": recorded.get("captured_at"),
                            "geometry": {key: geometry.get(key) for key in ("width", "height", "x", "y")}})
        if not frames or not trace.get("steps"):
            self.store.append_event("demonstration_unusable", {"id": trace.get("id"),
                "reason": "no_retained_visual_input_evidence"})
            self._lessons.pop(0)
            self._checkpoint()
            return
        evidence = learning_evidence(trace, mapping)
        proposed = self._infer(self.provider.learn_demonstration, evidence, frames)
        # Retain semantic strategy fields only. No executable macro/action payload
        # from a demonstration or model response is admitted to the motor port.
        lesson = {key: bounded_text(proposed.get(key)) for key in ("name", "purpose", "recovery")}
        for key in ("principles", "visual_preconditions"):
            if not isinstance(proposed.get(key), list) or not 1 <= len(proposed[key]) <= 64:
                raise ProviderError("Invalid semantic demonstration strategy")
            lesson[key] = [bounded_text(value) for value in proposed[key]]
        if not isinstance(proposed.get("steps"), list) or not 1 <= len(proposed["steps"]) <= 64:
            raise ProviderError("Invalid semantic demonstration steps")
        lesson["steps"] = [{key: bounded_text(step.get(key))
                            for key in ("purpose", "visible_target", "expected_visual_result")}
                           for step in proposed["steps"]]
        lesson["confidence"] = confidence(proposed.get("confidence"))
        self.store.add_memory("procedural", lesson, {"demonstration": trace.get("id")},
                              confidence(lesson["confidence"]))
        self.store.append_event("skill_acquired", {"name": lesson["name"], "demonstration": trace.get("id")})
        self._lessons.pop(0)
        self._checkpoint()

    def cycle(self):
        self._controls()
        if self.recorder.active or self._sleep.is_set():
            self._wait(0.2)
            return
        if self._lessons:
            self._learn()
        frame = self._capture()
        pending = self.store.pending_actions()
        if pending and not self._recover(frame, pending):
            self.intention = "Перевіряю незавершену дію за екраном; повтор заборонено"
            self._status("Результат попередньої дії ще невідомий")
            self._wait(10)
            return
        self.state = LifeState.AUTONOMOUS
        recalled = self.store.recall(self.intention, limit=12) + self.store.recall(limit=6)
        memories = list({m["id"]: m for m in recalled}.values())
        # Raw demonstrations are visual evidence for the learner, not summaries
        # to repeatedly send in every ordinary cognitive context.
        memories = [m for m in memories if not (isinstance(m["content"], dict) and "demonstration" in m["content"])]
        context = {"identity": self.store.identity(), "goals": self.store.goals()[:16],
                   "memories": memories,
                   "recent_events": self.store.events(limit=12), "now": utc_now()}
        decision = self._infer(self.provider.decide, frame, context)
        self.intention = decision.intention
        known_goals = {g["id"]: g for g in self.store.goals()}
        if decision.uncertainty <= 0.5:
            for update in decision.goal_updates:
                if update["confidence"] >= 0.8 and update["id"] in known_goals:
                    revised = {**known_goals[update["id"]], "status": update["status"],
                        "last_reviewed": utc_now(), "evidence": {"frame_id": frame.frame_id,
                        "summary": update["evidence"], "confidence": update["confidence"]}}
                    self.store.put_goal(revised)
                    self.store.add_memory("intentions", {"goal_id": revised["id"], "status": revised["status"]}, revised["evidence"], update["confidence"])
            recent_contents = {json.dumps(m["content"], sort_keys=True, ensure_ascii=False) for m in recalled}
            for update in decision.memory_updates:
                content = {"summary": update["summary"], "type": "visual_inference"}
                if update["confidence"] >= 0.8 and json.dumps(content, sort_keys=True, ensure_ascii=False) not in recent_contents:
                    self.store.add_memory(update["kind"], content,
                        {"frame_id": frame.frame_id, "observation": decision.scene}, update["confidence"])
        goal = dict(decision.goal)
        # Keep an existing intention instead of manufacturing a new goal every tick.
        matching = next((g for g in self.store.goals() if g.get("description") == goal["description"]), None)
        if matching:
            goal["id"] = matching["id"]
        revised_status = next((u["status"] for u in decision.goal_updates
                               if u["id"] == goal.get("id") and u["confidence"] >= 0.8), "active")
        goal.update(status=revised_status, next_action=decision.action.to_dict(),
                    evidence={"frame_id": frame.frame_id, "scene": decision.scene}, last_reviewed=utc_now())
        goal_id = self.store.put_goal(goal)
        self._status(decision.scene)
        if revised_status != "active":
            self._checkpoint()
            self._wait(decision.reconsider_after)
            return
        if decision.uncertainty > 0.5:
            self.store.append_event("inspect_uncertain_scene", {"frame_id": frame.frame_id,
                "uncertainty": decision.uncertainty, "goal_id": goal_id})
            self._rest(frame, decision.reconsider_after)
            return
        # Observe immediately before dispatch: never act on a screen that changed
        # while a slow provider was thinking. Geometry changes also invalidate it.
        fresh = self._capture()
        if ((frame.width, frame.height, frame.x, frame.y, frame.monitors) !=
                (fresh.width, fresh.height, fresh.x, fresh.y, fresh.monitors) or visual_delta(frame, fresh) > 0.015):
            self.store.append_event("stale_plan_discarded", {"frame_id": frame.frame_id,
                                                           "fresh_frame_id": fresh.frame_id})
            return
        self._controls()
        if self.recorder.active or self._teach.is_set() or self._sleep.is_set() or self.stop_event.is_set():
            return
        action = Action.parse(decision.action.to_dict())
        if action.kind == "wait":
            self.store.append_event("rest", {"goal_id": goal_id, "intention": self.intention})
            self._checkpoint()
            self._rest(fresh, max(action.args["seconds"], decision.reconsider_after))
            return
        self.port.validate_action(action, fresh)
        ledger_id = self.store.begin_action(action.to_dict(), fresh.frame_id)
        # Any exception after this point intentionally leaves an unresolved ledger
        # entry. Startup must inspect pixels rather than retry input.
        self.port.execute(action, fresh, self.stop_event)
        after = self._settle(fresh)
        outcome = self._infer(self.provider.verify, fresh, action, after)
        self.store.finish_action(ledger_id, outcome, after.frame_id)
        event_id = self.store.append_event("experience", {"goal_id": goal_id, "action_id": ledger_id,
            "scene": decision.scene, "outcome": outcome, "frame_id": after.frame_id})
        self.store.add_memory("episodic", {"intention": self.intention, "outcome": outcome},
                              {"event_id": event_id, "frame_id": after.frame_id}, outcome["confidence"])
        self._cycles += 1
        if time.monotonic() - self._last_reflection > 300:
            reflection = self._infer(self.provider.reflect, self.store.events(limit=16))
            self.store.add_memory("reflective", reflection, {"events": reflection["sources"]},
                                  confidence(reflection.get("confidence", 0.5)))
            if reflection.get("skill") and reflection["confidence"] >= 0.8:
                self.store.add_memory("procedural", reflection["skill"],
                                      {"events": reflection["sources"], "origin": "experience"}, reflection["confidence"])
            self._last_reflection = time.monotonic()
        self._checkpoint()
        self._rest(after, decision.reconsider_after)

    def run(self):
        try:
            previous = self.store.latest_checkpoint()
            if previous:
                # MemoryStore returns a checkpoint envelope with state payload.
                previous = previous.get("state", previous) if isinstance(previous.get("state"), dict) else previous
                self.intention = previous.get("intention", self.intention)
                self._cycles = previous.get("cycles", 0)
            # The append-only demonstration journal is authoritative. A crash
            # after skill_acquired but before checkpoint must not requeue it.
            self._lessons = self.store.pending_demonstrations()
            missed = 0
            if previous and previous.get("last_seen"):
                missed = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(previous["last_seen"])).total_seconds())
            self.state = LifeState.WAKE_RECOVER
            self.store.append_event("wake", {"missed_seconds": missed, "persona_id": self.store.identity()["persona_id"]})
            self._status(f"Відновлено ту саму особистість; минуло {missed:.0f} с")
            while not self.stop_event.is_set():
                try:
                    self.cycle()
                    self._retry_delay = 3
                except ProviderCancelled:
                    continue
                except Exception as exc:
                    # Retain the action ledger and identity on any body/provider/storage failure.
                    self.port.set_observing(True)
                    self.intention = "Зберігаю неперервність і чекаю відновлення можливостей"
                    detail = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
                    self._status(detail)
                    try:
                        self.store.append_event("recoverable_error", {"type": type(exc).__name__})
                        self._checkpoint()
                    except Exception:
                        # Storage failure must inhibit input, never erase/rebirth
                        # the persona or leave a held key while cleanup runs.
                        self._status("Пам’ять недоступна; введення зупинено")
                        self.stop_event.set()
                        continue
                    self._wait(self._retry_delay)
                    if not self.recorder.active and not self._teach.is_set() and not self._sleep.is_set():
                        self.port.set_observing(False)
                    self._retry_delay = min(60, self._retry_delay * 2)
        finally:
            saved = False
            try:
                self.port.set_observing(True)
                if self.recorder.active:
                    self._lessons.append(self.recorder.stop())
                self.state = LifeState.SHUTDOWN_CHECKPOINT
                self._checkpoint()
                self.state = LifeState.ASLEEP
                self.store.append_event("sleep", {"at": utc_now()})
                self._checkpoint()
                saved = True
            finally:
                self.provider.cancel.set()
                self._executor.shutdown(wait=True, cancel_futures=True)
                try:
                    self.provider.close()
                finally:
                    self.port.close()
                self._status("Стан збережено" if saved else "Пам’ять недоступна; попередній checkpoint збережено")
