"""PBCR container-related commands
"""

from pbcr.types import ContainerStorage


def ps(storage: ContainerStorage):
    """List containers"""
    containers = storage.list_containers()
    for container in containers:
        print(container)
