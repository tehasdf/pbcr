"""PBCR container-related commands
"""

import os

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
            is_running = False
        else:
            is_running = True
        if is_running and not force:
            print(
                f"Container {container_id} is running. "
                "Stop it first or use --force"
            )
            return
    storage.remove_container(container)
