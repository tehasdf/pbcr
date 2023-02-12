import ctypes
import os

from pbcr.docker_registry import pull_image_from_docker
from pbcr.types import Storage

libc = ctypes.CDLL('libc.so.6')

5
CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWCGROUP = 0x02000000


def run_command(storage: Storage, image_name: str, container_name: str):
    if image_name.startswith('docker.io/'):
        image_name = image_name.replace('docker.io/', '', 1)
        img = pull_image_from_docker(storage, image_name)
    else:
        raise ValueError(f'unknown image reference: {image_name}')

    container_chroot = storage.make_container_chroot(container_name, img)

    entrypoint = img.config.config['Entrypoint']
    command = img.config.config['Cmd']
    if not entrypoint:
        entrypoint = command
        command = []

    libc.unshare(CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWCGROUP | CLONE_NEWNS)
    forkpid = os.fork()
    if forkpid == 0:
        os.chroot(container_chroot)
        os.chdir('/')
        os.execv(entrypoint[0], entrypoint + command)
    else:
        os.waitpid(forkpid, 0)
