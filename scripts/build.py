"""Package AgentLink for sharing, or install it into a ComfyUI custom_nodes folder.

    python scripts/build.py                      -> dist/ComfyUI-AgentLink-<version>.zip
    python scripts/build.py --install <custom_nodes dir>
"""
import argparse
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "ComfyUI-AgentLink"
SHIPPED = ["__init__.py", "pyproject.toml", "README.md", "LICENSE", "agentlink/*.py", "web/*.js", "docs/*.png"]


def shipped_files():
    return sorted(path for pattern in SHIPPED for path in ROOT.glob(pattern))


def build_zip():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    target = ROOT / "dist" / f"{NAME}-{version}.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in shipped_files():
            archive.write(path, f"{NAME}/{path.relative_to(ROOT).as_posix()}")
    return target


def install(custom_nodes):
    target = Path(custom_nodes) / NAME
    if target.exists():
        if not (target / "agentlink" / "server.py").exists():
            sys.exit(f"{target} exists and is not AgentLink; not touching it")
        shutil.rmtree(target)
    for path in shipped_files():
        destination = target / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", metavar="CUSTOM_NODES")
    options = parser.parse_args()
    print(install(options.install) if options.install else build_zip())
