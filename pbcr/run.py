import ctypes
import json
import os
import sys
import uuid
import subprocess
import signal
import threading

from pbcr.docker_registry import load_docker_image
from pbcr.types import Storage, Container

libc = ctypes.CDLL('libc.so.6')

CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWCGROUP = 0x02000000


def _get_container_spec(mnt_cmd, container_dir):
    container_chroot = container_dir / 'chroot'
    parentpid = os.getpid()
    evt = threading.Event()
    signal.signal(signal.SIGUSR1, lambda sig, frame: evt.set())

    newuidmap_args = ['0', str(os.getuid()), '1']
    newgidmap_args = ['0', str(os.getgid()), '1']

    forkpid = os.fork()
    if forkpid == 0:
        libc.unshare(CLONE_NEWUSER | CLONE_NEWCGROUP | CLONE_NEWNS)
        os.kill(parentpid, signal.SIGUSR1)
        evt.wait()
        evt.clear()
        os.system(mnt_cmd)

        container = {}
        try:
            uids = []
            with (container_chroot / 'etc' / 'passwd').open() as f:
                for line in f:
                    parts = line.split(':')
                    uid = parts[2]
                    uids.append(uid)
            container['uids'] = uids
        except IOError:
            container['uids'] = []

        try:
            gids = []
            with (container_chroot / 'etc' / 'group').open() as f:
                for line in f:
                    parts = line.split(':')
                    gid = parts[2]
                    gids.append(gid)
            container['gids'] = gids
        except IOError:
            container['gids'] = []

        with (container_dir / 'container.json').open('w') as f:
            json.dump(container, f)

        os.kill(parentpid, signal.SIGUSR1)
        sys.exit(0)

    else:
        evt.wait()
        evt.clear()

        subprocess.call(['/usr/bin/newuidmap', str(forkpid)] + newuidmap_args)
        subprocess.call(['/usr/bin/newgidmap', str(forkpid)] + newgidmap_args)

        os.kill(forkpid, signal.SIGUSR1)
        evt.wait()
        evt.clear()
        with (container_dir / 'container.json').open() as f:
            container_data = json.load(f)

        min_uid = min(int(u) for u in container_data['uids'] if u != '0')
        min_gid = min(int(u) for u in container_data['gids'] if u != '0')

        max_uid = max(int(u) for u in container_data['uids'] if u != '0')
        max_gid = max(int(u) for u in container_data['gids'] if u != '0')
        newuidmap_args += [str(min_uid), '100000', str(max_uid - min_uid + 1)]
        newgidmap_args += [str(min_gid), '100000', str(max_gid - min_gid + 1)]

        signal.signal(signal.SIGUSR1, signal.SIG_DFL)
        return newuidmap_args, newgidmap_args


def run_command(
    storage: Storage,
    image_name: str,
    container_name: str | None=None,
    daemon: bool=False,
    volumes: list[str] | None=None,
):
    if not container_name:
        container_name = str(uuid.uuid4())
    if image_name.startswith('docker.io/'):
        image_name = image_name.replace('docker.io/', '', 1)
        img = load_docker_image(storage, image_name)
    else:
        raise ValueError(f'unknown image reference: {image_name}')

    container = Container(
        id=container_name,
        image_registry=img.registry,
        image_name=img.manifest.name,
        pid=None,
    )
    storage.store_container(container)
    container_dir = storage.make_container_dir(container_name, img)

    entrypoint = img.config.config['Entrypoint']
    command = img.config.config['Cmd']
    container_chroot = container_dir / 'chroot'
    container_workdir = container_dir / 'workdir'
    container_upperdir = container_dir / 'upper'
    container_volumes = container_dir / 'volumes'
    container_chroot.mkdir(exist_ok=True)
    container_upperdir.mkdir(exist_ok=True)
    container_workdir.mkdir(exist_ok=True)
    container_workdir.mkdir(exist_ok=True)

    if volumes:
        for volume in volumes:
            volume_source, _, volume_target = volume.partition(':')
            volume_target = volume_target.lstrip('/')
            target = container_volumes / volume_target
            if not target.parent.is_dir():
                target.parent.mkdir(parents=True)
            if target.exists():
                os.unlink(target)
            os.link(volume_source, target)

    if not entrypoint:
        entrypoint = [command[0]]
    parentpid = os.getpid()

    lowers = str(container_volumes) + ':' + ':'.join(str(ll.path) for ll in reversed(img.layers))
    upper = container_upperdir
    workdir = container_workdir
    mnt_cmd = (
        'mount -t overlay overlay '
        f'-o lowerdir={lowers},upperdir={upper},workdir={workdir} '
        f'{container_chroot}'
    )

    newuidmap_args, newgidmap_args = _get_container_spec(mnt_cmd, container_dir)

    evt = threading.Event()
    signal.signal(signal.SIGUSR1, lambda sig, frame: evt.set())

    forkpid = os.fork()
    if forkpid == 0:
        libc.unshare(CLONE_NEWUSER | CLONE_NEWCGROUP | CLONE_NEWNS)
        os.kill(parentpid, signal.SIGUSR1)

        evt.wait()
        evt.clear()
        os.system(mnt_cmd)

        os.chroot(container_chroot)
        os.execv(entrypoint[0], entrypoint + command)

    else:
        evt.wait()
        evt.clear()
        container.pid = forkpid
        storage.store_container(container)

        subprocess.call(['/usr/bin/newuidmap', str(forkpid)] + newuidmap_args)
        subprocess.call(['/usr/bin/newgidmap', str(forkpid)] + newgidmap_args)

        os.kill(forkpid, signal.SIGUSR1)
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)

        if not daemon:
            signal.signal(signal.SIGINT, lambda sig, frame: evt.set())
            evt.wait()
            evt.clear()

            _, retcode = os.waitpid(forkpid, 0)
            storage.remove_container(container)
            # for some reason, I can't remove in-process?
            subprocess.call(['/bin/rm', '-rf', str(container_dir)])
            sys.exit(retcode)
