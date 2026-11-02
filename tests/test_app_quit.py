import subprocess
import sys

from soma.app import wait_for_exit


def test_quit_waits_until_the_old_process_has_really_exited():
    short = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    assert wait_for_exit(short.pid, 10)
    assert short.poll() is not None
    long = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert not wait_for_exit(long.pid, 0.5)  # still running: the caller reports failure
    finally:
        long.kill()
        long.wait()
    assert wait_for_exit(long.pid, 1)  # gone
