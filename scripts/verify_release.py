"""Verify version alignment and the contents of release distributions."""

from __future__ import annotations

import argparse
import re
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])


def _emacs_version() -> str:
    source = (ROOT / "integrations/emacs/friction.el").read_text()
    match = re.search(r"^;; Version: (\S+)$", source, re.MULTILINE)
    if match is None:
        raise RuntimeError("integrations/emacs/friction.el has no Version header")
    return match.group(1)


def _one_artifact(directory: Path, pattern: str) -> Path:
    artifacts = sorted(directory.glob(pattern))
    if len(artifacts) != 1:
        raise RuntimeError(
            f"expected exactly one {pattern} artifact, found {len(artifacts)}"
        )
    return artifacts[0]


def _verify_wheel(wheel: Path, version: str) -> None:
    expected = {
        "friction/interfaces/mcp/server.py",
        "friction/interfaces/tui/app.py",
        "friction/storage/migrations/script.py.mako",
        "friction/storage/migrations/versions/0001_initial.py",
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = sorted(expected - names)
        if missing:
            raise RuntimeError(f"wheel is missing packaged files: {missing}")
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise RuntimeError("wheel must contain exactly one METADATA file")
        metadata = Parser().parsestr(archive.read(metadata_names[0]).decode())

    if metadata["Version"] != version:
        raise RuntimeError(
            f"wheel version {metadata['Version']} does not match project {version}"
        )
    requirements = metadata.get_all("Requires-Dist", [])
    for dependency in ("mcp", "textual"):
        if not any(requirement.startswith(dependency) for requirement in requirements):
            raise RuntimeError(f"wheel metadata is missing {dependency} dependency")


def _verify_sdist(sdist: Path, version: str) -> None:
    root = f"friction-{version}"
    expected = {
        f"{root}/LICENSE",
        f"{root}/integrations/emacs/README.md",
        f"{root}/integrations/emacs/friction.el",
        f"{root}/pyproject.toml",
        f"{root}/src/friction/interfaces/mcp/server.py",
        f"{root}/src/friction/interfaces/tui/app.py",
    }
    with tarfile.open(sdist, "r:gz") as archive:
        missing = sorted(expected - set(archive.getnames()))
    if missing:
        raise RuntimeError(f"source distribution is missing files: {missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--tag", help="Optional release tag, for example v0.1.0")
    args = parser.parse_args()

    version = _project_version()
    if _emacs_version() != version:
        raise RuntimeError("Python project and Emacs package versions do not match")
    if args.tag is not None and args.tag.removeprefix("v") != version:
        raise RuntimeError(f"tag {args.tag} does not match project version {version}")

    wheel = _one_artifact(args.dist_dir, f"friction-{version}-*.whl")
    sdist = _one_artifact(args.dist_dir, f"friction-{version}.tar.gz")
    _verify_wheel(wheel, version)
    _verify_sdist(sdist, version)
    print(f"verified friction {version}: {wheel.name}, {sdist.name}")


if __name__ == "__main__":
    main()
