"""Commands and utilities for running a container"""

import os
import pathlib
import pwd
import shlex
import socket
import subprocess
import uuid

import typing as t
import asyncio

from pbcr import libc
from pbcr.docker_registry import load_docker_image
from pbcr.types import (
    ImageStorage,
    ContainerStorage,
    Container,
    Image,
    ContainerConfig,
    ImageConfig,
)
from pbcr.networking import (
    IPInfo,
    TCPInfo,
    send_process_net_fd,
    receive_process_net_fd,
    TCPStack,
)
from pbcr.forkbarrier import ForkBarrier


class _UIDMapper:
    @classmethod
    def for_current_user(cls):
        """Create a _UIDMapper initialized for the current user."""
        uid = os.getuid()
        username = pwd.getpwuid(uid).pw_name
        subuid = cls._parse_sub_file(pathlib.Path('/etc/subuid'), username)
        subgid = cls._parse_sub_file(pathlib.Path('/etc/subgid'), username)
        return cls(subuid, subgid, str(uid))

    @classmethod
    def _parse_sub_file(
        cls,
        source_path: pathlib.Path,
        username: str,
    ) -> str:
        with source_path.open() as source_file:
            for line in source_file:
                parts = line.split(':')
                if parts[0] == username:
                    return parts[1]
        raise ValueError(username)

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

    def newuidmap(self, pid: int, uids: t.Iterable[str]):
        """Use newuidmap to subuid the given ids, for the given pid"""
        args = self._format_args(set(uids), self._subuid)
        subprocess.call(['/usr/bin/newuidmap', str(pid)] + args)

    def newgidmap(self, pid: int, gids: t.Iterable[str]):
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

    def add_volumes(self, volumes: list[str] | None):
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
        #    if target.exists():
        #        os.unlink(target)
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


def _get_container_spec_from_image(image_config: ImageConfig) -> tuple[list[str], list[str]]:
    """Get container UIDs and GIDs from pre-computed image configuration"""
    return image_config.uids, image_config.gids


async def _choose_image(storage: ImageStorage, image_name: str) -> Image:
    if image_name.startswith('docker.io/'):
        registry = 'docker.io'
        repo, _, reference = image_name.replace('docker.io/', '', 1).partition(':')
        reference = reference or 'latest'

        # Try to get the image from storage first
        img = storage.get_image(registry, repo, reference)
        if img:
            return img

        # If not found in storage, pull it
        return await load_docker_image(storage, f"{repo}:{reference}")
    raise ValueError(f'unknown image reference: {image_name}')


def _find_command_to_run(
    cfg: ContainerConfig,
    img: Image,
) -> list[str]:
    if cfg.entrypoint:
        entrypoint = cfg.entrypoint
        to_run = shlex.split(entrypoint + cfg.command)
    else:
        entrypoint = img.config.config.get('Entrypoint')
        command = img.config.config['Cmd']
        if not entrypoint:
            entrypoint = [command[0]]
            command = command[1:]
        to_run = entrypoint + command
    return to_run


async def run_command(
    loop: asyncio.AbstractEventLoop,
    image_storage: ImageStorage,
    container_storage: ContainerStorage,
    cfg: ContainerConfig,
) -> int:
    """The CLI command that runs a container"""
    # this has to be fixed later
    # pylint: disable=too-many-locals
    container_name = cfg.container_name or str(uuid.uuid4())

    img = await _choose_image(image_storage, cfg.image_name)

    uidmapper = _UIDMapper.for_current_user()
    container = Container(
        container_id=container_name,
        image_registry=img.registry,
        image_name=img.manifest.name,
        pid=None,
    )
    container_storage.store_container(container)

    container_fs = _ContainerFS.prepare(
        container_storage.make_container_dir(container_name),
        [ll.path for ll in img.layers],
    )
    container_fs.add_volumes(cfg.volumes)

    to_run = _find_command_to_run(cfg, img)

    container_uids, container_gids = _get_container_spec_from_image(img.config)

    left_sock, right_sock = socket.socketpair()
    with ForkBarrier() as barrier:
        if barrier.is_child:
            libc.unshare(
                libc.CLONE_NEWUSER |
                libc.CLONE_NEWCGROUP |
                libc.CLONE_NEWNS |
                libc.CLONE_NEWNET,
            )
            send_process_net_fd(left_sock)
            left_sock.close()
            right_sock.close()

            barrier.signal()
            barrier.wait()

            container_fs.mount()
            container_fs.chroot()
            os.execv(to_run[0], to_run)

        else:
            barrier.wait()
            net_fd = receive_process_net_fd(right_sock)
            left_sock.close()
            right_sock.close()

            container.pid = barrier.other_pid
            container_storage.store_container(container)

            if barrier.other_pid is not None:
                uidmapper.newuidmap(barrier.other_pid, container_uids)
                uidmapper.newgidmap(barrier.other_pid, container_gids)

                os.set_blocking(net_fd, False)
                tcp_stack_instance = TCPStack(net_fd, loop)
                loop.add_reader(net_fd, _reader_callback, net_fd, tcp_stack_instance)

                barrier.signal()

            retcode = 1
            if barrier.other_pid is not None:
                while True:
                    try:
                        retcode = os.waitpid(barrier.other_pid, os.WNOHANG)
                        await asyncio.sleep(0.1)
                    except ChildProcessError:
                        break

                os.close(net_fd)
                loop.remove_reader(net_fd)
            if cfg.remove:
                container_storage.remove_container(container)
                container_fs.remove()
            return retcode


def _reader_callback(net_fd: int, tcp_stack_instance: TCPStack):
    while True:
        try:
            data = bytearray(os.read(net_fd, 8192))
            if not data: # No more data to read right now
                break

            iph, data_remaining = IPInfo.parse(data)
            if iph.ipver != 4:
                continue
            if iph.proto == 6:  # tcp
                tcph, data_remaining = TCPInfo.parse(iph, data_remaining)
                tcp_stack_instance.handle_packet(iph, tcph, data_remaining)
            else:
                print(f"Unhandled IP protocol: {iph.proto}: {data}")

        except BlockingIOError: # No more data immediately available
            break
