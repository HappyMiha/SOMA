"""Headless integration regressions found while reviewing lifecycle transitions."""

import threading
import time
from types import SimpleNamespace

import pytest

from soma.core import LifeState
from soma.kernel import LifeKernel
from soma.memory import MemoryStore
from soma.provider import ProviderCancelled


@pytest.fixture
def reviewed_kernel(tmp_path):
    class Port:
        observing = False

        def set_observing(self, observing):
            self.observing = observing

        def release_all(self):
            pass

    store = MemoryStore(tmp_path)
    provider = SimpleNamespace(cancel=threading.Event(), metrics={})
    recorder = SimpleNamespace(active=False, paused=False)
    kernel = LifeKernel(store, Port(), provider, recorder)
    kernel.state = LifeState.AUTONOMOUS
    yield kernel
    kernel._executor.shutdown(wait=True)
    store.close()


def test_suspend_and_resume_between_kernel_ticks_restores_body(reviewed_kernel):
    kernel = reviewed_kernel
    kernel.suspend()
    assert kernel.port.observing
    kernel.resume()
    kernel._controls()
    assert not kernel.port.observing
    assert not kernel._sleep.is_set()


def test_stopping_inflight_inference_does_not_busy_spin(reviewed_kernel):
    kernel = reviewed_kernel
    entered, release = threading.Event(), threading.Event()
    control_calls = []

    def slow_inference():
        entered.set()
        assert release.wait(2), "controlled inference was not released"

    def stop_while_running():
        assert entered.wait(2)
        kernel.stop_event.set()
        time.sleep(0.03)
        release.set()

    kernel._controls = lambda: control_calls.append(None)
    stopper = threading.Thread(target=stop_while_running)
    stopper.start()
    try:
        with pytest.raises(ProviderCancelled):
            kernel._infer(slow_inference)
    finally:
        release.set()
        stopper.join(timeout=2)
    # Before the fix, Event.wait() returned immediately after stop and generated
    # tens of thousands of control iterations in a few milliseconds.
    assert len(control_calls) < 100
