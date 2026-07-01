"""Facade for Docker operations with regionless mirror support."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from rock.logger import init_logger
from rock.sdk.envhub.regionless.compose import compose_pull, resolve_compose
from rock.sdk.envhub.regionless.resolver import _DEFAULT_PROBE_TIMEOUT_SEC, RockRegistryResolver

logger = init_logger(__name__)


class DockerFacade:
    """Unified SDK entry point for Docker operations with ROCK mirror registry support.

    Aggregates regionless image resolution, Dockerfile rewriting, and compose
    file handling behind a single facade.
    """

    def __init__(self, resolver: RockRegistryResolver | None = None) -> None:
        self._resolver = resolver or RockRegistryResolver()

    async def resolve_image(
        self,
        image: str,
        *,
        timeout_sec: float = _DEFAULT_PROBE_TIMEOUT_SEC,
    ) -> str:
        """Resolve an image reference to a ROCK mirror if available."""
        return await self._resolver.resolve_image(image, timeout_sec=timeout_sec)

    async def pull_image(
        self,
        image: str,
        *,
        timeout_sec: float = _DEFAULT_PROBE_TIMEOUT_SEC,
    ) -> subprocess.CompletedProcess:
        """Resolve image to a ROCK mirror, then ``docker pull``.

        Resolution failures are non-blocking — falls back to pulling the
        original image.
        """
        try:
            resolved = await self.resolve_image(image, timeout_sec=timeout_sec)
        except Exception:
            logger.warning("Image resolution failed for %s, pulling original", image, exc_info=True)
            resolved = image

        proc = await asyncio.create_subprocess_exec(
            "docker",
            "pull",
            resolved,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()

        result = subprocess.CompletedProcess(
            args=["docker", "pull", resolved],
            returncode=proc.returncode,
            stdout=stdout_bytes.decode(errors="replace") if stdout_bytes else "",
            stderr=stderr_bytes.decode(errors="replace") if stderr_bytes else "",
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"docker pull failed (exit {result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )

        return result

    async def resolve_dockerfile(
        self,
        dockerfile: Path | str,
        *,
        timeout_sec: float = _DEFAULT_PROBE_TIMEOUT_SEC,
    ) -> bool:
        """Rewrite ``FROM`` images in a Dockerfile to ROCK mirrors when available."""
        return await self._resolver.resolve_dockerfile(Path(dockerfile), timeout_sec=timeout_sec)

    async def resolve_compose(
        self,
        compose_path: Path | str,
        *,
        timeout_sec: float = _DEFAULT_PROBE_TIMEOUT_SEC,
    ) -> bool:
        """Rewrite ``image:`` fields in a compose file to ROCK mirrors when available."""
        return await resolve_compose(Path(compose_path), timeout_sec=timeout_sec, resolver=self._resolver)

    async def pull_compose(
        self,
        compose_path: Path | str,
        *,
        services: list[str] | None = None,
        project_name: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float = _DEFAULT_PROBE_TIMEOUT_SEC,
        extra_args: list[str] | None = None,
    ) -> subprocess.CompletedProcess:
        """Resolve images in a compose file to ROCK mirrors, then ``docker compose pull``."""
        return await compose_pull(
            Path(compose_path),
            services=services,
            project_name=project_name,
            env=env,
            timeout_sec=timeout_sec,
            extra_args=extra_args,
            resolver=self._resolver,
        )
