#!/usr/bin/env python3
"""Download Metacat 1.2, apply the bundled diffs, and verify the result.

The bundle has two patch groups.  The first (``patches/*.patch``) gives the reference
reconstruction behind Petacat's published studies, and is what ``--output`` builds and
``--verify`` accepts.  The second (``patches/fixes/*.patch``) fixes the three reference
crashes in KNOWN-FAILURES.md; it is applied only when asked for, with ``--fixes`` at
reconstruction or ``--apply-fixes`` on an existing reference tree, verified with
``--verify DIR --fixes``, and taken off again with ``--remove-fixes``.
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


def _run_patches(root, patches, reverse=False, bundle=BUNDLE):
    """Apply (or reverse) patches without fuzz, each after a dry run of itself, so a
    patch that does not fit leaves the tree untouched."""
    for patch in patches:
        check_digest(safe_path(bundle, patch['path']), patch['sha256'])
    for patch in (reversed(patches) if reverse else patches):
        command = ['patch', '-p1', '-f', '-F', '0', '-s'] + (['-R'] if reverse else [])
        source = ['-i', str(safe_path(bundle, patch['path']))]
        subprocess.run(command + ['--dry-run'] + source, cwd=root, check=True)
        subprocess.run(command + source, cwd=root, check=True)


def apply_fixes(root, manifest, bundle=BUNDLE):
    """Apply the second patch group to a verified reference tree, in place."""
    verify(root, manifest['reconstructed_files'])
    _run_patches(root, manifest['fix_patches'], bundle=bundle)
    for name, info in manifest['fixed_files'].items():
        safe_path(root, name).chmod(0o755 if info['executable'] else 0o644)
    verify(root, fixed_inventory(manifest))


def remove_fixes(root, manifest, bundle=BUNDLE):
    """Take the second patch group off a verified fixed tree, in place."""
    verify(root, fixed_inventory(manifest))
    _run_patches(root, manifest['fix_patches'], reverse=True, bundle=bundle)
    for name, info in manifest['reconstructed_files'].items():
        safe_path(root, name).chmod(0o755 if info['executable'] else 0o644)
    verify(root, manifest['reconstructed_files'])


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


def reconstruct(archive, output, manifest, fixes=False):
    if output.exists() or output.is_symlink():
        raise ValueError(f"Refusing to replace existing destination: {output}")
    check_digest(archive, manifest['upstream']['sha256'])
    for patch in manifest['patches'] + (manifest['fix_patches'] if fixes else []):
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
        if fixes:
            apply_fixes(root, manifest)
        root.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', type=Path, help='Previously downloaded Metacat-1.2.tgz')
    parser.add_argument('--output', type=Path, help='New directory for reconstructed source')
    parser.add_argument('--verify', type=Path, help='Verify an existing pristine reconstruction')
    parser.add_argument('--fixes', action='store_true',
                        help='With --output: also apply the second patch group (the '
                             'known-failure fixes).  With --verify: expect it applied.')
    parser.add_argument('--apply-fixes', type=Path, metavar='DIR',
                        help='Apply the second patch group to a verified reference tree')
    parser.add_argument('--remove-fixes', type=Path, metavar='DIR',
                        help='Take the second patch group off a verified fixed tree')
    args = parser.parse_args()
    manifest = json.loads((BUNDLE / 'manifest.json').read_text())
    count = len(manifest['reconstructed_files'])
    modes = [m for m in (args.verify, args.output, args.apply_fixes, args.remove_fixes) if m]
    if len(modes) > 1:
        parser.error('choose one of --output, --verify, --apply-fixes, --remove-fixes')
    if (args.apply_fixes or args.remove_fixes) and (args.archive or args.fixes):
        parser.error('--apply-fixes and --remove-fixes take no other options')
    if args.apply_fixes:
        root = args.apply_fixes.resolve()
        if describe(root, manifest) == 'fixes':
            raise ValueError(f"{args.apply_fixes} already has the known-failure fixes")
        apply_fixes(root, manifest)
        print(f"Applied the known-failure fixes; verified {count} files: {args.apply_fixes}")
        return
    if args.remove_fixes:
        root = args.remove_fixes.resolve()
        if describe(root, manifest) == 'reference':
            raise ValueError(f"{args.remove_fixes} is already the reference reconstruction")
        remove_fixes(root, manifest)
        print(f"Removed the known-failure fixes; verified {count} files: {args.remove_fixes}")
        return
    if args.verify:
        if args.archive:
            parser.error('--verify cannot be combined with --archive or --output')
        root = args.verify.resolve()
        expected = fixed_inventory(manifest) if args.fixes else manifest['reconstructed_files']
        try:
            verify(root, expected)
        except ValueError as exc:
            state = describe(root, manifest)
            if state == 'fixes':
                raise ValueError(f"{exc}\n{args.verify} has the known-failure fixes (the second "
                                 "patch group) applied: it is not the reference reconstruction. "
                                 "Verify it with --verify DIR --fixes, or take the fixes off "
                                 "with --remove-fixes DIR.") from exc
            if state == 'reference':
                raise ValueError(f"{exc}\n{args.verify} is the reference reconstruction, without "
                                 "the known-failure fixes; apply them with --apply-fixes DIR.") from exc
            raise
        if args.fixes:
            print(f"Verified {count} files with the known-failure fixes: {args.verify}")
        else:
            print(f"Verified {count} files: {args.verify}")
        return
    if not args.output:
        parser.error('--output is required unless using --verify, --apply-fixes or --remove-fixes')
    # Keep downloads explicit and checksummed; --archive permits offline rebuilds.
    with tempfile.TemporaryDirectory(prefix='metacat-download-') as temp:
        archive = args.archive
        if archive is None:
            archive = Path(temp) / 'Metacat-1.2.tgz'
            subprocess.run(['curl', '-fL', '--connect-timeout', '20', '--max-time', '180',
                            manifest['upstream']['url'], '-o', str(archive)], check=True)
        reconstruct(archive.resolve(), args.output.absolute(), manifest, fixes=args.fixes)
    if args.fixes:
        print(f"Verified {count} files with the known-failure fixes: {args.output}")
    else:
        print(f"Verified {count} files: {args.output}")


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        raise SystemExit(str(exc)) from exc
