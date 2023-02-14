"""Commands and utilities for running a container"""

import ctypes
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import uuid
from typing import Iterable

from pbcr.docker_registry import load_docker_image
from pbcr.types import Storage, Container, Image

libc = ctypes.CDLL('libc.so.6')

CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWCGROUP = 0x02000000


class _UIDMapper:
    def __init__(self, subuid: str, subgid: str, root_map: str):
        self._subuid = subuid
        self._subgid = subgid
        self._root_map = root_map

    def _format_args(self, ids: set[str], start: str) -> list[str]:
        args = ['0', self._root_map, '1']

        # root, not part of this map, we'll always add it to the args anyway
        ids = ids - {'0'}
        if ids:
            min_id = min(int(u) for u in ids)
            max_id = max(int(u) for u in ids)
            args += [str(min_id), start, str(max_id - min_id + 1)]

        return args

    def newuidmap(self, pid: int, uids: Iterable[str]):
        """Use newuidmap to subuid the given ids, for the given pid"""
        args = self._format_args(set(uids), self._subuid)
        subprocess.call(['/usr/bin/newuidmap', str(pid)] + args)

    def newgidmap(self, pid: int, gids: Iterable[str]):
        """Use newgidmap to subgid the given ids, for the given pid"""
        args = self._format_args(set(gids), self._subgid)
        subprocess.call(['/usr/bin/newgidmap', str(pid)] + args)


class _ContainerFS:
    @classmethod
    def prepare(cls, container_dir: pathlib.Path, lowers: list[pathlib.Path]):
        """Create the directory structure at container_dir"""
        (container_dir / 'upper').mkdir(exist_ok=True)
        (container_dir / 'workdir').mkdir(exist_ok=True)
        (container_dir / 'chroot').mkdir(exist_ok=True)
        return cls(container_dir, lowers)

    def __init__(
        self,
        container_dir: pathlib.Path,
        lowers: list[pathlib.Path]
    ):
        self.container_chroot = container_dir / 'chroot'
        self.container_dir = container_dir
        self._lowers = lowers
        self._container_workdir = container_dir / 'workdir'
        self._container_upperdir = container_dir / 'upper'

    def mount(self):
        """Mount the overlayfs at the container chroot"""
        lowers = ':'.join(reversed([str(lower) for lower in self._lowers]))
        upper = self._container_upperdir
        workdir = self._container_workdir
        mnt_cmd = [
            '/bin/mount', '-t', 'overlay', 'overlay',
            '-o', f'lowerdir={lowers},upperdir={upper},workdir={workdir}',
            f'{self.container_chroot}'
        ]
        subprocess.call(mnt_cmd)

    def add_volumes(self, volumes: list[str]):
        """Add volumes to this container's "lower" overlayfs dirs"""
        if not volumes:
            return
        container_volumes = self.container_dir / 'volumes'
        container_volumes.mkdir(exist_ok=True)

        for volume in volumes:
            volume_source, _, volume_target = volume.partition(':')
            volume_target = volume_target.lstrip('/')
            target = container_volumes / volume_target
            if not target.parent.is_dir():
                target.parent.mkdir(parents=True)
            if target.exists():
                os.unlink(target)
            os.link(volume_source, target)
            self._lowers.append(container_volumes)

    def chroot(self):
        """Chroot into this container's chroot"""
        os.chroot(self.container_chroot)
        os.chdir('/')

    def remove(self):
        """Remove the container directories"""
        # for some reason, I can't remove in-process?
        subprocess.call(['/bin/rm', '-rf', str(self.container_dir)])


class _ForkBarrier:
    def __init__(self):
        self.is_parent = True
        self.is_child = False
        self.other_pid = None
        self._evt = threading.Event()

    def __enter__(self):
        signal.signal(signal.SIGUSR1, lambda sig, frame: self._evt.set())
        parent_pid = os.getpid()
        pid = os.fork()
        self.other_pid = pid or parent_pid

        self.is_child = pid == 0
        self.is_parent = not self.is_child

        return self

    def __exit__(self, etype, evalue, traceback):
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)

    def signal(self):
        """Signal the other side"""
        os.kill(self.other_pid, signal.SIGUSR1)

    def wait(self):
        """Wait for a signal called from the other side"""
        self._evt.wait()
        self._evt.clear()


def _find_ids(source_path) -> list[str]:
    ids = []
    try:
        with (source_path).open() as source_file:
            for line in source_file:
                parts = line.split(':')
                ids.append(parts[2])
    except IOError:
        pass
    return ids


def _get_container_spec(container_fs: _ContainerFS, uidmapper: _UIDMapper):
    evt = threading.Event()
    ids_storage_path = container_fs.container_dir / 'container.json'
    signal.signal(signal.SIGUSR1, lambda sig, frame: evt.set())

    with _ForkBarrier() as barrier:
        if barrier.is_child:
            libc.unshare(CLONE_NEWUSER | CLONE_NEWCGROUP | CLONE_NEWNS)
            barrier.signal()
            barrier.wait()
            container_fs.mount()

            container = {
                'uids': _find_ids(container_fs.container_chroot / 'etc/passwd'),
                'gids': _find_ids(container_fs.container_chroot / 'etc/group')
            }
            with ids_storage_path.open('w') as container_file:
                json.dump(container, container_file)

            barrier.signal()
            sys.exit(0)
        else:
            barrier.wait()

            uidmapper.newuidmap(barrier.other_pid, [])
            uidmapper.newgidmap(barrier.other_pid, [])

            barrier.signal()
            barrier.wait()

            with ids_storage_path.open() as container_file:
                container_data = json.load(container_file)

            return container_data['uids'], container_data['gids']

def _choose_image(storage: Storage, image_name: str) -> Image:
    if image_name.startswith('docker.io/'):
        image_name = image_name.replace('docker.io/', '', 1)
        return load_docker_image(storage, image_name)
    raise ValueError(f'unknown image reference: {image_name}')

def run_command(
    storage: Storage,
    image_name: str,
    container_name: str | None=None,
    daemon: bool=False,
    volumes: list[str] | None=None,
):
    """The CLI command that runs a container"""
    if not container_name:
        container_name = str(uuid.uuid4())
    img = _choose_image(storage, image_name)

    uidmapper = _UIDMapper('100000', '100000', '1000')
    container = Container(
        container_id=container_name,
        image_registry=img.registry,
        image_name=img.manifest.name,
        pid=None,
    )
    storage.store_container(container)

    container_fs = _ContainerFS.prepare(
        storage.make_container_dir(container_name, img),
        [ll.path for ll in img.layers],
    )
    container_fs.add_volumes(volumes)

    entrypoint = img.config.config['Entrypoint']
    command = img.config.config['Cmd']

    if not entrypoint:
        entrypoint = [command[0]]

    container_uids, container_gids = _get_container_spec(
        container_fs, uidmapper)

    with _ForkBarrier() as barrier:
        if barrier.is_child:
            libc.unshare(CLONE_NEWUSER | CLONE_NEWCGROUP | CLONE_NEWNS)
            barrier.signal()
            barrier.wait()

            container_fs.mount()
            container_fs.chroot()
            os.execv(entrypoint[0], entrypoint + command)

        else:
            barrier.wait()
            container.pid = barrier.other_pid
            storage.store_container(container)

            uidmapper.newuidmap(barrier.other_pid, container_uids)
            uidmapper.newgidmap(barrier.other_pid, container_gids)
            barrier.signal()

            if not daemon:
                signal.signal(signal.SIGINT, signal.SIG_IGN)

                _, retcode = os.waitpid(barrier.other_pid, 0)
                storage.remove_container(container)
                container_fs.remove()
                sys.exit(retcode)
