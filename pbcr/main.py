"""PBCR CLI

This defines the CLI entrypoint for PBCR
"""

import argparse
import pathlib

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
        '-d',
        '--daemon',
        action='store_true',
        dest='daemon',
    )
    run_parser.add_argument(
        '-v',
        '--volume',
        dest='volumes',
        nargs='*',
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
            run_command(
                image_storage,
                container_storage,
                cfg,
            )
        case _:
            parser.print_help()
