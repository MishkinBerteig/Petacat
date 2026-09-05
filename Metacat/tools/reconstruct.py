#!/usr/bin/env python3
"""Download Metacat 1.2, apply the bundled diffs, and verify the result."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile


BUNDLE = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_digest(path, expected):
    if digest(path) != expected:
        raise ValueError(f"SHA-256 mismatch: {path}")


def safe_path(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or '..' in path.parts:
        raise ValueError(f"Unsafe archive or manifest path: {name}")
    return root.joinpath(*path.parts)


def verify(root, files):
    entries = list(root.rglob('*'))
    for path in entries:
        if path.is_symlink():
            raise ValueError(f"Not a regular file or directory: {path}")
    actual = {p.relative_to(root).as_posix() for p in entries if not p.is_dir()}
    if actual != set(files):
        raise ValueError(f"File inventory mismatch: missing={sorted(set(files) - actual)}, "
                         f"extra={sorted(actual - set(files))}")
    for name, info in files.items():
        path = safe_path(root, name)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Not a regular file: {path}")
        check_digest(path, info['sha256'])
        if bool(path.stat().st_mode & 0o111) != info['executable']:
            raise ValueError(f"Executable permission mismatch: {path}")


def extract(archive, root, upstream):
    prefix = upstream['archive_root'] + '/'
    seen = set()
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if member.isdir() and member.name.rstrip('/') == upstream['archive_root']:
                continue
            if not member.name.startswith(prefix) or not member.isfile():
                raise ValueError(f"Unexpected archive member: {member.name}")
            name = member.name[len(prefix):]
            if name not in upstream['files'] or name in seen:
                raise ValueError(f"Unexpected or duplicate source file: {name}")
            seen.add(name)
            path = safe_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source:
                path.write_bytes(source.read())
            path.chmod(0o755 if upstream['files'][name]['executable'] else 0o644)
    verify(root, upstream['files'])


def reconstruct(archive, output, manifest):
    if output.exists() or output.is_symlink():
        raise ValueError(f"Refusing to replace existing destination: {output}")
    check_digest(archive, manifest['upstream']['sha256'])
    for patch in manifest['patches']:
        check_digest(safe_path(BUNDLE, patch['path']), patch['sha256'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.metacat-', dir=output.parent) as temp:
        root = Path(temp) / 'source'
        root.mkdir()
        extract(archive, root, manifest['upstream'])
        for patch in manifest['patches']:
            subprocess.run(['patch', '-p1', '-f', '-F', '0', '-i',
                            str(safe_path(BUNDLE, patch['path']))], cwd=root, check=True)
        for name, info in manifest['reconstructed_files'].items():
            safe_path(root, name).chmod(0o755 if info['executable'] else 0o644)
        verify(root, manifest['reconstructed_files'])
        root.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Previously downloaded Metacat-1.2.tgz')
    parser.add_argument('--output', type=Path, help='New directory for reconstructed source')
    parser.add_argument('--verify', type=Path, help='Verify an existing pristine reconstruction')
    args = parser.parse_args()
    manifest = json.loads((BUNDLE / 'manifest.json').read_text())
    if args.verify:
        if args.archive or args.output:
            parser.error('--verify cannot be combined with --archive or --output')
        verify(args.verify.resolve(), manifest['reconstructed_files'])
        print(f"Verified {len(manifest['reconstructed_files'])} files: {args.verify}")
        return
    if not args.output:
        parser.error('--output is required unless using --verify')
    # Keep downloads explicit and checksummed; --archive permits offline rebuilds.
    with tempfile.TemporaryDirectory(prefix='metacat-download-') as temp:
        archive = args.archive
        if archive is None:
            archive = Path(temp) / 'Metacat-1.2.tgz'
            subprocess.run(['curl', '-fL', '--connect-timeout', '20', '--max-time', '180',
                            manifest['upstream']['url'], '-o', str(archive)], check=True)
        reconstruct(archive.resolve(), args.output.absolute(), manifest)
    print(f"Verified {len(manifest['reconstructed_files'])} files: {args.output}")


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        raise SystemExit(str(exc)) from exc
