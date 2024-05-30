"""PBCR container-related commands
"""

import os
import signal
import time

from pbcr.types import ContainerStorage


def ps(storage: ContainerStorage):
    """List containers"""
    containers = storage.list_containers()
    for container in containers:
        print(container)


def rm_container(
    storage: ContainerStorage,
    container_id: str,
    force: bool = False,
):
    """Remove a container"""
    container = storage.get_container(container_id)
    if not container:
        print(f"Container {container_id} not found")
        return

    if container.pid:
        try:
            os.kill(container.pid, 0)
        except OSError:
            pass
        else:
            if not force:
                print(
                    f"Container {container_id} is running. "
                    "Stop it first or use --force"
                )
                return
            _stop_container_process(container.pid)
    storage.remove_container(container)


def _stop_container_process(pid: int):
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        else:
            time.sleep(0.1)
    # after 50 retries, ie. 5 seconds, if it's still up....
    # KILL DASH NINE
    os.kill(pid, 9)
