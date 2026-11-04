import asyncio
import json
import shutil
from collections.abc import Callable
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import aiohttp
import click
import tomlkit

from amass import CONCURRENT_REQUESTS, parse_lock_file, parse_toml_file


def coroutine(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(f(*args, **kwargs))

    return wrapper


DEFAULT_OUTPUT_DIR = Path("vendor")


def _get_configured_output() -> Path | None:
    try:
        with open("pyproject.toml") as f:
            content = f.read()
    except FileNotFoundError:
        return None

    document = tomlkit.parse(content)
    configured = document.get("tool", {}).get("amass", {}).get("output")

    if configured is None:
        return None

    return Path(configured)


def _resolve_output_dir(*, output: Path | None) -> Path:
    if output is not None:
        return output

    configured = _get_configured_output()
    if configured is not None:
        return configured

    return DEFAULT_OUTPUT_DIR


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(version("amass"), "-v", "--version")
def cli() -> None:
    pass


@cli.command(name="lock", short_help="Lock the dependencies")
@coroutine
async def lock() -> None:
    with open("pyproject.toml") as f:
        content = f.read()

    lock_file = await parse_toml_file(content=content)

    with open("amass.lock", "w") as f:
        f.write(json.dumps(lock_file.content, indent=2))
        f.write("\n")


@cli.command(
    name="install", short_help="Install the dependencies from the lock file"
)
@click.option(
    "-o",
    "--output",
    "output",
    # types-click's Path stub only allows str/bytes for path_type, but click
    # supports pathlib.Path at runtime and returns a Path here.
    type=click.Path(file_okay=False, path_type=Path),  # type: ignore[type-var]
    default=None,
    help=(
        "Directory to install the assets into. Overrides "
        "[tool.amass].output in pyproject.toml. Absolute paths are used "
        "as-is; relative paths are resolved against the current working "
        "directory."
    ),
)
@coroutine
async def install(output: Path | None) -> None:
    with open("amass.lock") as f:
        content = json.loads(f.read())

    lock_file = parse_lock_file(content=content)

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "output"
        tmp_path.mkdir()

        semaphore = asyncio.Semaphore(value=CONCURRENT_REQUESTS)
        async with aiohttp.ClientSession() as session:
            await asyncio.gather(
                lock_file.download(
                    session=session, semaphore=semaphore, output_dir=tmp_path
                )
            )

        lock_file.check_integrity(directory=tmp_path)
        lock_file.create_maps(directory=tmp_path)

        output_dir = _resolve_output_dir(output=output)
        if output_dir.exists():
            shutil.rmtree(output_dir)

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), str(output_dir))
