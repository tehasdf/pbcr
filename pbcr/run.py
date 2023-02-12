import ctypes
import os
import shutil
import uuid

from pbcr.docker_registry import pull_image_from_docker
from pbcr.types import Storage, Container

libc = ctypes.CDLL('libc.so.6')

CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWCGROUP = 0x02000000


def run_command(
    storage: Storage,
    image_name: str,
    container_name: str | None=None,
    daemon: bool=False,
    copies: list[str] | None=None,
):
    if not container_name:
        container_name = str(uuid.uuid4())
    if image_name.startswith('docker.io/'):
        image_name = image_name.replace('docker.io/', '', 1)
        img = pull_image_from_docker(storage, image_name)
    else:
        raise ValueError(f'unknown image reference: {image_name}')

    container = Container(
        id=container_name,
        image_registry=img.registry,
        image_name=img.manifest.name,
        pid=None,
    )
    storage.store_container(container)
    container_chroot = storage.make_container_chroot(container_name, img)

    for copy_spec in copies:
        copy_from, _, copy_to = copy_spec.partition(':')
        copy_to = container_chroot / copy_to.lstrip('/')
        shutil.copy(copy_from, copy_to)

    entrypoint = img.config.config['Entrypoint']
    command = img.config.config['Cmd']
    if not entrypoint:
        entrypoint = [command[0]]

    libc.unshare(CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWCGROUP | CLONE_NEWNS)
    forkpid = os.fork()
    if forkpid == 0:
        os.chroot(container_chroot)
        os.chdir('/')
        os.execv(entrypoint[0], entrypoint + command)
    else:
        container.pid = forkpid
        storage.store_container(container)

        if not daemon:
            os.waitpid(forkpid, 0)
            storage.remove_container(container)
