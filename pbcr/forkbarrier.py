"""A simple barrier for synchronizing between parent and child processes"""

import os
import signal
import threading


class ForkBarrier:
    """A simple barrier for synchronizing between parent and child processes"""
    def __init__(self):
        self.is_parent = True
        self.is_child = False
        self.other_pid = None
        self._evt = threading.Event()

    def __enter__(self):
        signal.signal(signal.SIGUSR1, lambda *_: self._evt.set())
        parent_pid = os.getpid()
        pid = os.fork()
        self.other_pid = pid or parent_pid

        self.is_child = pid == 0
        self.is_parent = not self.is_child

        return self

    def __exit__(self, *_):
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)

    def signal(self):
        """Signal the other side"""
        if self.other_pid is not None:
            os.kill(self.other_pid, signal.SIGUSR1)

    def wait(self):
        """Wait for a signal called from the other side"""
        self._evt.wait()
        self._evt.clear()
