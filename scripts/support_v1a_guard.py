"""The one flag that lets a tool read the support-v1a study, or a file derived from it.

The study ``studies/support-v1a/`` was recorded on the Metacat build WITHOUT the known-failure
fixes (``Metacat/patches/fixes/``), so it is not patched Metacat's behaviour. The study is kept,
and it is used only when the user specifically asks for it (ruling of 2026-11-08). Three tools
read it, directly or through the files derived from it, and each refuses unless it is given
``--user-asked-for-support-v1a``:

* ``scripts/compare_frequencies.py support-v1a`` (reads the study's archive);
* ``scripts/compare_to_metacat.py`` (its default reference, ``measurements/reference/``, is derived
  from the study; so is any other reference directory whose files record the study as their source);
* ``scripts/make_reference_sets.py`` (reads the study's archive and writes the derived files).

The flag has the same name in all three. Nothing under ``tests/`` reads the study or a derived file.
"""

from __future__ import annotations

import json
import os

FLAG = "--user-asked-for-support-v1a"
DEST = "user_asked_for_support_v1a"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDY_ARCHIVE = os.path.join(ROOT, "studies", "support-v1a", "data", "main.tar.gz")
DERIVED_DIRECTORY = os.path.join(ROOT, "measurements", "reference")


def add_flag(parser) -> None:
    parser.add_argument(
        FLAG, dest=DEST, action="store_true",
        help="required to read the support-v1a study or a file derived from it: that study was "
             "recorded on the Metacat build without the known-failure fixes, and it is used only "
             "when the user specifically asks for it")


def refusal(what: str) -> str:
    return (f"refusing to {what}: it reads the support-v1a study, or a file derived from it. "
            "That study was recorded on the Metacat build without the known-failure fixes "
            "(Metacat/patches/fixes/), so it is not patched Metacat's behaviour. It is kept, and it is "
            "used only when the user specifically asks for it. If the user has asked, run again with "
            f"{FLAG}.")


def require(parser, args, what: str) -> None:
    """Stop (``parser.error``, exit status 2) unless the flag was given."""
    if not getattr(args, DEST, False):
        parser.error(refusal(what))


def same_path(a, b) -> bool:
    return os.path.realpath(str(a)) == os.path.realpath(str(b))


def is_study_archive(path) -> bool:
    return same_path(path, STUDY_ARCHIVE)


def is_derived_directory(directory) -> bool:
    """True for ``measurements/reference/``, and for a directory whose single-run sets name the
    support-v1a study as their source (a copy of the derived files)."""
    if same_path(directory, DERIVED_DIRECTORY):
        return True
    path = os.path.join(str(directory), "single-run-sets.json")
    try:
        with open(path) as handle:
            source = json.load(handle).get("source", {})
    except (OSError, ValueError, AttributeError):
        return False
    return "support-v1a" in json.dumps(source)
