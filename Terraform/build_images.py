#!/usr/bin/env python3
"""Build deployment images using explicit clean contexts; never push or call AWS."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from fnmatch import fnmatch

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'api': ['requirements/runtime.lock', 'requirements/build.lock', 'pyproject.toml', 'README.md', 'src', 'config'],
    'kevin': ['prototypes/kevin/requirements.txt', 'prototypes/kevin/mel_agent', 'prototypes/kevin/app', 'prototypes/kevin/reports', 'prototypes/kevin/mockup'],
    'farmerloop': ['farmerloop/pyproject.toml', 'farmerloop/README.md', 'farmerloop/src'],
}

def stage_context(name: str, context: Path) -> None:
    """Copy only tracked inputs, excluding secret/cache filenames even if tracked."""
    files = subprocess.check_output(['git', 'ls-files', '-z', '--', *SOURCES[name], 'data/participant-pack'], cwd=ROOT, text=True).split('\0')
    ignored = ('__pycache__', '*.pyc', '.env*', '.aws', '.venv', '.git', '*.pem', '*.key', '*credentials*', '*.egg-info')
    for file in filter(None, files):
        relative = Path(file)
        if any(fnmatch(part, pattern) for part in relative.parts for pattern in ignored):
            continue
        src, dest = ROOT/relative, context/relative
        if src.is_symlink() or not src.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Build inputs must be regular files inside the checkout')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def build(name: str, tag: str) -> None:
    with tempfile.TemporaryDirectory(prefix='team41-image-') as directory:
        context = Path(directory)
        stage_context(name, context)
        shutil.copy2(ROOT/'Terraform/images'/f'{name}.Dockerfile', context/'Dockerfile')
        subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '--tag', tag, str(context)], check=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', choices=SOURCES)
    parser.add_argument('--tag', required=True, help='Local tag, or destination ECR repository plus a unique release tag. This command never pushes.')
    args = parser.parse_args()
    build(args.runtime, args.tag)
