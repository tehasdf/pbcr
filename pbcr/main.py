"""PBCR CLI

This defines the CLI entrypoint for PBCR
"""

import argparse
import pathlib

from pbcr.containers import rm_container, ps
from pbcr.images import list_images_command, pull_image_command
from pbcr.run import run_command
from pbcr.storage import FileImageStorage, FileContainerStorage
from pbcr.types import ContainerConfig


def main():
    """CLI entrypoint

    This is usually run as a console script, installed into your virtualenv.
    Use argparse and dispatch to the selected method.
    """
    parser = argparse.ArgumentParser(
        prog='pbcr',
    )
    subparsers = parser.add_subparsers(dest='command')
    _ = subparsers.add_parser('images')

    pull_parser = subparsers.add_parser('pull')
    pull_parser.add_argument('image_names', nargs='+')

    run_parser = subparsers.add_parser('run')
    run_parser.add_argument('image_name', nargs=1)
    run_parser.add_argument(
        '-n',
        '--name',
        required=True,
        dest='container_name',
        help='Container name',
    )
    run_parser.add_argument(
        '--entrypoint',
        dest='entrypoint',
        default='',
        required=False,
    )
    run_parser.add_argument(
        '-d',
        '--daemon',
        action='store_true',
        dest='daemon',
    )
    run_parser.add_argument(
        '--rm',
        action='store_true',
        dest='remove',
    )
    run_parser.add_argument(
        '-v',
        '--volume',
        dest='volumes',
        action='append',
    )
    _ = subparsers.add_parser('ps')
    rm_parser = subparsers.add_parser('rm')
    rm_parser.add_argument('container_id')
    rm_parser.add_argument(
        '-f',
        '--force',
        action='store_true',
        dest='force',
    )

    kwargs = vars(parser.parse_args())

    command = kwargs.pop('command', None)
    base_path = pathlib.Path('~/.pbcr').expanduser().absolute()
    image_storage = FileImageStorage.create(base_path)
    container_storage = FileContainerStorage.create(base_path)

    match command:
        case "images":
            list_images_command(image_storage, **kwargs)
        case "pull":
            pull_image_command(image_storage, **kwargs)
        case "run":
            image_name = kwargs.pop('image_name')[0]
            cfg = ContainerConfig(
                image_name=image_name,
                **kwargs,
            )
            if cfg.daemon and cfg.remove:
                raise ValueError('Cannot run in daemon mode with remove')
            run_command(
                image_storage,
                container_storage,
                cfg,
            )
        case "ps":
            ps(container_storage)
        case "rm":
            rm_container(
                container_storage,
                **kwargs,
            )
        case _:
            parser.print_help()
