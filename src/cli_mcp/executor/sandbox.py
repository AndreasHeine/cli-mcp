"""Container sandboxing for CLI execution.

The CLI binary itself runs inside a container started by docker or podman, so a
misconfigured tool cannot touch the host. The chosen image must contain the CLI;
for image-less workflows the image can be built to bundle it.
"""

from __future__ import annotations

from pathlib import Path

from cli_mcp.config.settings import SandboxSettings


def sandbox_argv(argv: list[str], sandbox: SandboxSettings, cwd: Path | None = None) -> list[str]:
    """Wrap *argv* in a ``docker``/``podman`` run invocation."""
    prefix = [sandbox.backend, "run", "--rm"]
    if not sandbox.network:
        prefix.append("--network=none")
    if sandbox.workdir_mount and cwd is not None:
        prefix.extend(["--workdir", sandbox.container_workdir, "-v", f"{cwd}:{sandbox.container_workdir}"])
    prefix.extend(sandbox.extra_args)
    prefix.append(sandbox.image)
    return [*prefix, *argv]


def sandbox_available(backend: str) -> bool:
    """Whether the container backend binary is on PATH."""
    import shutil

    return shutil.which(backend) is not None
