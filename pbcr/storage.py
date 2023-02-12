import json
import pathlib

from pbcr.types import Image, Storage, PullToken


class FileStorage:
    def __init__(self, base: pathlib.Path):
        self._base = base

    def list_images(self) -> list[Image]:
        return []

    def get_pull_token(self, registry: str, repo: str) -> PullToken | None:
        tokens_file = self._base / 'pull_tokens.json'
        try:
            with tokens_file.open() as f:
                tokens = json.load(f)
        except (ValueError, IOError):
            tokens = {}

        try:
            token_data = tokens[registry][repo]
        except KeyError:
            return None
        token = PullToken.fromdict(token_data)

        if token.is_expired:
            del tokens[registry][repo]
            with tokens_file.open('w') as f:
                json.dump(tokens, f, indent=4)
            return None
        return token

    def store_pull_token(self, registry: str, repo: str, token: PullToken):
        tokens_file = self._base / 'pull_tokens.json'
        with tokens_file.open('w+') as f:
            try:
                tokens = json.load(f)
            except ValueError:
                tokens = {}
            tokens.setdefault(registry, {})[repo] = token.asdict()
            f.seek(0)
            json.dump(tokens, f, indent=4)


def make_storage(
    base_path: pathlib.Path | str=pathlib.Path('~/.pbcr'),
    **kwargs,
) -> Storage:
    base_path = pathlib.Path(base_path).expanduser().absolute()
    if not base_path.is_dir():
        base_path.mkdir()
    return FileStorage(base=base_path)
