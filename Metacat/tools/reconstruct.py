#!/usr/bin/env python3
"""Download Metacat 1.2, apply the bundled diffs, and verify the result.

The bundle has two patch groups.  The first (``patches/*.patch``) gives the reference
reconstruction, which is only the intermediate step of building the tree: it is never left
behind as a usable tree.  The second (``patches/fixes/*.patch``) fixes the crashes listed in
KNOWN-FAILURES.md, and the group keeps growing.  ``--output`` builds the patched tree, which
is the only Metacat there is, and ``--verify`` accepts only that tree.  ``--apply-fixes`` brings
a tree left over from before to the patched state.  Nothing takes the fixes off.
"""

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


def fixed_inventory(manifest):
    """The reconstructed inventory with the second patch group applied."""
    files = dict(manifest['reconstructed_files'])
    files.update(manifest.get('fixed_files', {}))
    return files


def _run_patches(root, patches, bundle=BUNDLE):
    """Apply patches without fuzz, each after a dry run of itself, so a patch that does not
    fit leaves the tree untouched."""
    for patch in patches:
        check_digest(safe_path(bundle, patch['path']), patch['sha256'])
    for patch in patches:
        command = ['patch', '-p1', '-f', '-F', '0', '-s']
        source = ['-i', str(safe_path(bundle, patch['path']))]
        subprocess.run(command + ['--dry-run'] + source, cwd=root, check=True)
        subprocess.run(command + source, cwd=root, check=True)


def apply_fixes(root, manifest, bundle=BUNDLE):
    """Apply the second patch group to a verified reference tree, in place.  This is the last
    step of building the patched tree, and the way to bring an older reference tree up."""
    verify(root, manifest['reconstructed_files'])
    _run_patches(root, manifest['fix_patches'], bundle=bundle)
    for name, info in manifest['fixed_files'].items():
        safe_path(root, name).chmod(0o755 if info['executable'] else 0o644)
    verify(root, fixed_inventory(manifest))


def describe(root, manifest):
    """'reference', 'fixes', or None for a tree that is neither."""
    for state, files in (('reference', manifest['reconstructed_files']),
                         ('fixes', fixed_inventory(manifest))):
        try:
            verify(root, files)
            return state
        except ValueError:
            pass
    return None


def reconstruct(archive, output, manifest):
    """Build the patched tree: upstream, the first patch group, then the second.  The
    reference reconstruction exists only inside the temporary directory."""
    if output.exists() or output.is_symlink():
        raise ValueError(f"Refusing to replace existing destination: {output}")
    check_digest(archive, manifest['upstream']['sha256'])
    for patch in manifest['patches'] + manifest['fix_patches']:
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
        apply_fixes(root, manifest)
        root.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', type=Path, help='Previously downloaded Metacat-1.2.tgz')
    parser.add_argument('--output', type=Path, help='New directory for reconstructed source')
    parser.add_argument('--verify', type=Path, help='Verify an existing patched reconstruction')
    parser.add_argument('--apply-fixes', type=Path, metavar='DIR',
                        help='Bring a leftover reference tree (without the second patch '
                             'group) to the patched state')
    args = parser.parse_args()
    manifest = json.loads((BUNDLE / 'manifest.json').read_text())
    count = len(manifest['reconstructed_files'])
    modes = [m for m in (args.verify, args.output, args.apply_fixes) if m]
    if len(modes) > 1:
        parser.error('choose one of --output, --verify, --apply-fixes')
    if args.apply_fixes and args.archive:
        parser.error('--apply-fixes takes no other options')
    if args.apply_fixes:
        root = args.apply_fixes.resolve()
        if describe(root, manifest) == 'fixes':
            raise ValueError(f"{args.apply_fixes} already has the known-failure fixes")
        apply_fixes(root, manifest)
        print(f"Applied the known-failure fixes; verified {count} files: {args.apply_fixes}")
        return
    if args.verify:
        if args.archive:
            parser.error('--verify cannot be combined with --archive or --output')
        root = args.verify.resolve()
        try:
            verify(root, fixed_inventory(manifest))
        except ValueError as exc:
            if describe(root, manifest) == 'reference':
                raise ValueError(f"{exc}\n{args.verify} is an old reference reconstruction, "
                                 "without the known-failure fixes.  It is not Metacat: bring it "
                                 "up with --apply-fixes DIR.") from exc
            raise
        print(f"Verified {count} files with the known-failure fixes: {args.verify}")
        return
    if not args.output:
        parser.error('--output is required unless using --verify or --apply-fixes')
    # Keep downloads explicit and checksummed; --archive permits offline rebuilds.
    with tempfile.TemporaryDirectory(prefix='metacat-download-') as temp:
        archive = args.archive
        if archive is None:
            archive = Path(temp) / 'Metacat-1.2.tgz'
            subprocess.run(['curl', '-fL', '--connect-timeout', '20', '--max-time', '180',
                            manifest['upstream']['url'], '-o', str(archive)], check=True)
        reconstruct(archive.resolve(), args.output.absolute(), manifest)
    print(f"Verified {count} files with the known-failure fixes: {args.output}")


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        raise SystemExit(str(exc)) from exc
