import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import aiohttp
import pytest
import pytest_asyncio
import tomlkit
from click.testing import CliRunner
from packaging.specifiers import SpecifierSet

from amass import (
    CONCURRENT_REQUESTS,
    AssetFile,
    Dependency,
    LockedDependency,
    LockFile,
    Provider,
    ProviderVersion,
    generate_lock_file,
    get_dependency_provider,
    is_allowed_asset_type,
    parse_dependencies,
    parse_lock_file,
    parse_toml_file,
)
from amass.cli import DEFAULT_OUTPUT_DIR, _resolve_output_dir, cli

TEST_VERSIONS = [
    "0.0.8",
    "0.1.0",
    "0.1.1",
    "0.1.2",
    "0.2.0",
    "0.3.0",
    "0.4.0",
    "0.4.1",
    "1.0.0",
    "1.0.1",
    "1.0.2",
    "1.1.0",
    "1.2.0",
    "1.2.1",
    "1.3.0",
    "1.3.1",
    "1.3.2",
    "1.3.3",
    "1.4.0",
    "1.4.1",
    "1.5.0",
    "1.6.0",
    "1.6.1",
    "1.7.0",
]
TEST_LOCK_FILE = {
    "content_hash": (
        "sha256:8d25d01d0adc9808db2afd9feb489abc10c52008039293ecc1ee39d0e31cae8b"
    ),
    "dependencies": [
        {
            "assets": [
                {
                    "name": "htmx.min.js",
                    "sri": (
                        "sha512-etqA0KankuxrlSeZDYycQBY/D/KWZn0YZjlsjAo7kCEBTy1gg+DwmR6icxtOpqDBOzm2P00/lSIXEu7K+zvNsg=="
                    ),
                },
            ],
            "name": "htmx",
            "version": "1.7.0",
            "provider": "cdnjs",
            "maps": [],
        }
    ],
    "lock_version": "1.0",
}

TEST_TOML_FILE = """
[tool.amass.dependencies]
vega = { version = "==5.20.2", include = ["vega(.min)?.js"], maps = ["vega.map"] }
"""


def test_cli():
    runner = CliRunner()
    result = runner.invoke(cli)
    assert result.output != ""


async def test_toml_file_parsing():
    lock_file = await parse_toml_file(content=TEST_TOML_FILE)
    assert lock_file.content


@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture(scope="session")
def semaphore():
    return asyncio.Semaphore(value=CONCURRENT_REQUESTS)


async def test_update_all_assets(session, semaphore):
    dependency = Dependency(
        name="htmx",
        provider=Provider.CDNJS,
        specifiers=SpecifierSet("==1.7.0"),
        include_filter={
            "htmx(.min)?.js",
        },
    )
    await dependency.update_assets(
        session=session,
        semaphore=semaphore,
    )
    assert dependency.resolved_version == "1.7.0"
    assert dependency.assets == [
        AssetFile(
            name="htmx.js",
            sri="sha512-wJXYT7RzKp/dxju83CCCATupp32GQvko0KrJVK3zTgTMkVWiLiHnupKKgOUt+87t+oe/Rm2Q2p+pOpiD+IR0lQ==",
        ),
        AssetFile(
            name="htmx.min.js",
            sri="sha512-etqA0KankuxrlSeZDYycQBY/D/KWZn0YZjlsjAo7kCEBTy1gg+DwmR6icxtOpqDBOzm2P00/lSIXEu7K+zvNsg==",
        ),
    ]


def test_resolve_dependency():
    dependency = Dependency(name="foo", provider=Provider.CDNJS)
    assert (
        dependency.resolve_version(
            versions={ProviderVersion(remote_version=v) for v in TEST_VERSIONS}
        )
        == "1.7.0"
    )


def test_dependency_to_lock_entry():
    dependency = Dependency(
        name="foo",
        resolved_version="1.7.0",
        assets=[],
        provider=Provider.CDNJS,
    )
    assert dependency.locked == LockedDependency(
        name="foo",
        version="1.7.0",
        assets=[],
        provider=Provider.CDNJS,
        maps=[],
    )


def test_lock_file_content():
    lock_file = LockFile(
        dependencies=[
            LockedDependency(
                name="foo",
                version="3.6.0",
                assets=[],
                provider=Provider.CDNJS,
                maps=["foo"],
            )
        ]
    )
    assert lock_file.content == {
        "lock_version": "1.0",
        "content_hash": (
            "sha256:d0a4f142b8acbe104affa7e4294069d32b6999a41ddca420e8b0006ccaf1a2a1"
        ),
        "dependencies": [
            {
                "name": "foo",
                "version": "3.6.0",
                "assets": [],
                "provider": "cdnjs",
                "maps": ["foo"],
            }
        ],
    }


def test_parse_lock_file():
    content = {
        "lock_version": "1.0",
        "content_hash": (
            "sha256:4b42e84b4366f09c9bf04c533f9370ff31758542d6b785a57758982baf5a6e95"
        ),
        "dependencies": [
            {
                "name": "foo",
                "version": "3.6.0",
                "assets": [],
                "provider": "cdnjs",
                "maps": ["foo.map"],
            }
        ],
    }

    assert parse_lock_file(content=content) == LockFile(
        dependencies=[
            LockedDependency(
                name="foo",
                version="3.6.0",
                assets=[],
                provider=Provider.CDNJS,
                maps=["foo.map"],
            )
        ]
    )


async def test_generate_lock_file(session, semaphore):
    dependency = Dependency(
        name="htmx",
        provider=Provider.CDNJS,
        include_filter={"htmx.min.js"},
        specifiers=SpecifierSet("==1.7.0"),
    )
    await dependency.update_assets(
        session=session,
        semaphore=semaphore,
    )
    lock_file = generate_lock_file(dependencies=[dependency])

    assert lock_file.content == TEST_LOCK_FILE


async def test_fetch_asset_file(session, semaphore):
    dependency = Dependency(name="htmx", provider=Provider.CDNJS)
    await dependency.update_assets(session=session, semaphore=semaphore)
    locked_dependency = dependency.locked

    with TemporaryDirectory() as dir:
        output_path = Path(dir)
        asset = locked_dependency.assets[0]
        await asset.download(
            session=session,
            semaphore=semaphore,
            output_dir=output_path,
            dependency_provider=get_dependency_provider(
                provider=dependency.provider
            ),
            dependency_name=dependency.name,
            dependency_version=dependency.resolved_version,
        )

        with open(output_path / dependency.name / asset.name) as f:
            content = f.read()

    assert content != ""


async def test_download_lock_file(session, semaphore, tmp_path):
    lock_file = parse_lock_file(content=TEST_LOCK_FILE)

    await lock_file.download(
        session=session, semaphore=semaphore, output_dir=tmp_path
    )

    assert [str(f.relative_to(tmp_path)) for f in tmp_path.rglob("*")] == [
        "htmx",
        "htmx/htmx.min.js",
    ]


@pytest.mark.parametrize(
    "provider_string,expected_provider",
    (("cdnjs", Provider.CDNJS), ("unpkg", Provider.UNPKG)),
)
def test_parse_dependencies(provider_string, expected_provider):
    dependencies = tomlkit.table()
    dependencies.add(
        "htmx",
        {
            "version": "==1.7.0",
            "provider": provider_string,
            "include": ["htmx.min.js"],
        },
    )

    parsed = parse_dependencies(dependencies=dependencies)

    assert parsed == [
        Dependency(
            name="htmx",
            provider=expected_provider,
            specifiers=SpecifierSet("==1.7.0"),
            include_filter={"htmx.min.js"},
            maps=[],
        )
    ]


async def test_resolve_beta_version(session, semaphore):
    dependency = Dependency(
        name="itk-wasm",
        specifiers=SpecifierSet("==1.0.0-b.18"),
        provider=Provider.UNPKG,
    )

    await dependency.update_assets(session=session, semaphore=semaphore)

    assert dependency.resolved_version == "1.0.0-b.18"


@pytest.mark.parametrize("provider", (Provider.CDNJS, Provider.UNPKG))
async def test_dependency_provider_get_versions(session, semaphore, provider):
    dependency_provider = get_dependency_provider(provider=provider)

    versions = await dependency_provider.get_versions(
        session=session, semaphore=semaphore, name="jquery"
    )

    assert "3.7.0" in versions
    assert len(versions) > 10


@pytest.mark.parametrize("provider", (Provider.CDNJS, Provider.UNPKG))
async def test_dependency_provider_get_assets(session, semaphore, provider):
    dependency_provider = get_dependency_provider(provider=provider)

    assets = await dependency_provider.get_assets(
        session=session, semaphore=semaphore, name="jquery", version="3.7.0"
    )

    assert len(assets) > 5


@pytest.mark.parametrize(
    "provider,prefix", ((Provider.CDNJS, ""), (Provider.UNPKG, "dist/"))
)
async def test_dependency_provider_fetch_file(
    session, semaphore, provider, prefix
):
    dependency_provider = get_dependency_provider(provider=provider)

    content = await dependency_provider.fetch_file(
        session=session,
        semaphore=semaphore,
        name=f"{prefix}jquery.min.js",
        dependency_name="jquery",
        dependency_version="3.7.0",
    )

    assert content.decode().startswith("/*! jQuery v3.7.0 |")


def test_is_allowed_asset_type_text_test():
    assert is_allowed_asset_type("text/anything")
    assert not is_allowed_asset_type("application/anything")


def test_resolve_output_dir_flag_wins_over_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.amass]\noutput = "configured"\n'
    )

    assert _resolve_output_dir(output=Path("from_flag")) == Path("from_flag")


def test_resolve_output_dir_uses_config_when_no_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.amass]\noutput = "configured"\n'
    )

    assert _resolve_output_dir(output=None) == Path("configured")


def test_resolve_output_dir_default_when_no_flag_no_config(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.other]\nkey = 1\n")

    assert _resolve_output_dir(output=None) == DEFAULT_OUTPUT_DIR


def test_resolve_output_dir_default_when_no_pyproject(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert _resolve_output_dir(output=None) == DEFAULT_OUTPUT_DIR


@pytest.fixture
def mocked_install(monkeypatch):
    """Patch the install command's network and verification steps.

    download writes a single known asset into the staging directory so the
    final on-disk destination can be asserted; integrity and map creation are
    turned into no-ops.
    """

    async def fake_download(self, *, session, semaphore, output_dir):
        target = output_dir / "htmx" / "htmx.min.js"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("// htmx")

    def noop_check_integrity(self, *, directory):
        return None

    def noop_create_maps(self, *, directory):
        return None

    monkeypatch.setattr(LockFile, "download", fake_download)
    monkeypatch.setattr(LockFile, "check_integrity", noop_check_integrity)
    monkeypatch.setattr(LockFile, "create_maps", noop_create_maps)


def _write_lock_file(directory):
    (directory / "amass.lock").write_text(json.dumps(TEST_LOCK_FILE))


def _assert_installed(output_dir):
    assert (output_dir / "htmx" / "htmx.min.js").read_text() == "// htmx"


def test_install_absolute_output(tmp_path, monkeypatch, mocked_install):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    _write_lock_file(cwd)

    destination = tmp_path / "elsewhere" / "assets"

    result = CliRunner().invoke(cli, ["install", "--output", str(destination)])

    assert result.exit_code == 0, result.output
    _assert_installed(destination)


def test_install_relative_output(tmp_path, monkeypatch, mocked_install):
    monkeypatch.chdir(tmp_path)
    _write_lock_file(tmp_path)

    result = CliRunner().invoke(cli, ["install", "-o", "relative/path"])

    assert result.exit_code == 0, result.output
    _assert_installed(tmp_path / "relative" / "path")


def test_install_uses_configured_output(tmp_path, monkeypatch, mocked_install):
    monkeypatch.chdir(tmp_path)
    _write_lock_file(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.amass]\noutput = "configured_dir"\n'
    )

    result = CliRunner().invoke(cli, ["install"])

    assert result.exit_code == 0, result.output
    _assert_installed(tmp_path / "configured_dir")


def test_install_default_output(tmp_path, monkeypatch, mocked_install):
    monkeypatch.chdir(tmp_path)
    _write_lock_file(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.other]\nkey = 1\n")

    result = CliRunner().invoke(cli, ["install"])

    assert result.exit_code == 0, result.output
    _assert_installed(tmp_path / DEFAULT_OUTPUT_DIR)


def test_install_flag_overrides_config(tmp_path, monkeypatch, mocked_install):
    monkeypatch.chdir(tmp_path)
    _write_lock_file(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.amass]\noutput = "configured_dir"\n'
    )

    result = CliRunner().invoke(cli, ["install", "-o", "from_flag"])

    assert result.exit_code == 0, result.output
    _assert_installed(tmp_path / "from_flag")
    assert not (tmp_path / "configured_dir").exists()


def test_install_creates_missing_parents(
    tmp_path, monkeypatch, mocked_install
):
    monkeypatch.chdir(tmp_path)
    _write_lock_file(tmp_path)

    destination = tmp_path / "a" / "b" / "c" / "assets"

    result = CliRunner().invoke(cli, ["install", "--output", str(destination)])

    assert result.exit_code == 0, result.output
    _assert_installed(destination)


def test_install_replaces_existing_directory(
    tmp_path, monkeypatch, mocked_install
):
    monkeypatch.chdir(tmp_path)
    _write_lock_file(tmp_path)

    destination = tmp_path / "assets"
    destination.mkdir()
    (destination / "stale.txt").write_text("old")

    result = CliRunner().invoke(cli, ["install", "--output", str(destination)])

    assert result.exit_code == 0, result.output
    _assert_installed(destination)
    assert not (destination / "stale.txt").exists()


def test_install_without_pyproject(tmp_path, monkeypatch, mocked_install):
    monkeypatch.chdir(tmp_path)
    _write_lock_file(tmp_path)

    destination = tmp_path / "assets"

    result = CliRunner().invoke(cli, ["install", "--output", str(destination)])

    assert result.exit_code == 0, result.output
    _assert_installed(destination)


def test_install_help_lists_output_flag():
    result = CliRunner().invoke(cli, ["install", "--help"])

    assert result.exit_code == 0
    assert "--output" in result.output
    assert "-o" in result.output
