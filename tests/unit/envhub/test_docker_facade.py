from unittest.mock import AsyncMock, patch

import pytest
import yaml

from rock.sdk.envhub.docker import DockerFacade
from rock.sdk.envhub.regionless.resolver import ROCK_REGISTRY_ENV, RockRegistryResolver


@pytest.fixture()
def resolver():
    r = RockRegistryResolver()
    yield r
    r.reset_cache()


@pytest.fixture()
def facade(resolver):
    return DockerFacade(resolver=resolver)


class TestResolveImage:
    async def test_delegates_to_resolver(self, facade, monkeypatch):
        monkeypatch.setenv(ROCK_REGISTRY_ENV, "reg.example.com/ns")
        with patch.object(
            RockRegistryResolver,
            "_http_probe_manifest",
            new=AsyncMock(return_value=True),
        ):
            result = await facade.resolve_image("ghcr.io/org/app:v1")
        assert result == "reg.example.com/org/app:v1"

    async def test_no_env_returns_original(self, facade, monkeypatch):
        monkeypatch.delenv(ROCK_REGISTRY_ENV, raising=False)
        result = await facade.resolve_image("ghcr.io/org/app:v1")
        assert result == "ghcr.io/org/app:v1"


class TestPullImage:
    async def test_resolve_and_pull(self, facade, monkeypatch):
        monkeypatch.setenv(ROCK_REGISTRY_ENV, "reg.example.com/ns")
        with (
            patch.object(
                RockRegistryResolver,
                "_http_probe_manifest",
                new=AsyncMock(return_value=True),
            ),
            patch("rock.sdk.envhub.docker.asyncio.create_subprocess_exec") as mock_exec,
        ):
            proc_mock = AsyncMock()
            proc_mock.returncode = 0
            proc_mock.communicate.return_value = (b"Pulled\n", b"")
            mock_exec.return_value = proc_mock

            result = await facade.pull_image("ghcr.io/org/app:v1")

        assert result.returncode == 0
        cmd = mock_exec.call_args[0]
        assert cmd == ("docker", "pull", "reg.example.com/org/app:v1")

    async def test_resolve_failure_pulls_original(self, facade, monkeypatch):
        monkeypatch.setenv(ROCK_REGISTRY_ENV, "reg.example.com/ns")
        with (
            patch.object(
                RockRegistryResolver,
                "resolve_image",
                new=AsyncMock(side_effect=Exception("probe boom")),
            ),
            patch("rock.sdk.envhub.docker.asyncio.create_subprocess_exec") as mock_exec,
        ):
            proc_mock = AsyncMock()
            proc_mock.returncode = 0
            proc_mock.communicate.return_value = (b"Pulled\n", b"")
            mock_exec.return_value = proc_mock

            result = await facade.pull_image("ghcr.io/org/app:v1")

        assert result.returncode == 0
        cmd = mock_exec.call_args[0]
        assert cmd == ("docker", "pull", "ghcr.io/org/app:v1")

    async def test_pull_failure_raises(self, facade, monkeypatch):
        monkeypatch.delenv(ROCK_REGISTRY_ENV, raising=False)
        with patch("rock.sdk.envhub.docker.asyncio.create_subprocess_exec") as mock_exec:
            proc_mock = AsyncMock()
            proc_mock.returncode = 1
            proc_mock.communicate.return_value = (b"", b"Error: pull access denied\n")
            mock_exec.return_value = proc_mock

            with pytest.raises(RuntimeError, match="docker pull failed"):
                await facade.pull_image("ghcr.io/org/app:v1")


class TestResolveDockerfile:
    async def test_delegates_to_resolver(self, facade, tmp_path, monkeypatch):
        monkeypatch.setenv(ROCK_REGISTRY_ENV, "reg.example.com/ns")
        df = tmp_path / "Dockerfile"
        df.write_text("FROM ghcr.io/org/app:v1\nRUN echo hello\n")
        with patch.object(
            RockRegistryResolver,
            "_http_probe_manifest",
            new=AsyncMock(return_value=True),
        ):
            changed = await facade.resolve_dockerfile(df)
        assert changed
        assert "FROM reg.example.com/org/app:v1" in df.read_text()


class TestResolveCompose:
    async def test_delegates_to_compose_module(self, facade, tmp_path, monkeypatch):
        monkeypatch.setenv(ROCK_REGISTRY_ENV, "reg.example.com/ns")
        cf = tmp_path / "docker-compose.yml"
        data = {"version": "3", "services": {"web": {"image": "ghcr.io/org/app:v1"}}}
        cf.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        with patch.object(
            RockRegistryResolver,
            "_http_probe_manifest",
            new=AsyncMock(return_value=True),
        ):
            changed = await facade.resolve_compose(cf)
        assert changed
        result = yaml.safe_load(cf.read_text())
        assert result["services"]["web"]["image"] == "reg.example.com/org/app:v1"


class TestPullCompose:
    async def test_delegates_to_compose_module(self, facade, tmp_path, monkeypatch):
        monkeypatch.setenv(ROCK_REGISTRY_ENV, "reg.example.com/ns")
        cf = tmp_path / "docker-compose.yml"
        data = {"version": "3", "services": {"web": {"image": "ghcr.io/org/app:v1"}}}
        cf.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        with (
            patch.object(
                RockRegistryResolver,
                "_http_probe_manifest",
                new=AsyncMock(return_value=True),
            ),
            patch("rock.sdk.envhub.regionless.compose.asyncio.create_subprocess_exec") as mock_exec,
        ):
            proc_mock = AsyncMock()
            proc_mock.returncode = 0
            proc_mock.communicate.return_value = (b"Done\n", b"")
            mock_exec.return_value = proc_mock

            result = await facade.pull_compose(cf)

        assert result.returncode == 0


class TestCustomResolver:
    async def test_uses_injected_resolver(self):
        custom = RockRegistryResolver()
        f = DockerFacade(resolver=custom)
        assert f._resolver is custom

    async def test_default_resolver(self):
        f = DockerFacade()
        assert isinstance(f._resolver, RockRegistryResolver)
