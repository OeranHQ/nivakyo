#!/usr/bin/env python3
"""Reject local planning files from the index and complete outgoing Git histories."""
import argparse
import re
import subprocess
import sys
from pathlib import PurePosixPath

PROTECTED_NAMES = {"project_brief.md", "learning_log.md", "source_plan.md", "mvp_review.md", "phase_status.json"}
PROTECTED_DIRS = {".local", "private", "plans", "project-plans", "roadmap", "phase-plans", "phases"}
DOCUMENT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".pdf", ".doc", ".docx"}
PLANNING_NAME = re.compile(r"(?:^|[._ -])(?:phases?(?:[-_ ]?[0-9]+)?|plans?|roadmaps?|schedules?)(?:[._ -]|$)")


def protected(path):
    p = PurePosixPath(path.lower())
    if any(part in PROTECTED_DIRS or re.fullmatch(r"phase[-_ ]?[0-9]+", part) for part in p.parts[:-1]):
        return True
    return (p.name in PROTECTED_NAMES or p.suffix == ".docx"
            or (p.suffix in DOCUMENT_EXTENSIONS and bool(PLANNING_NAME.search(p.stem))))


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, check=True)
    return result.stdout


def index_paths():
    return set(p.decode("utf-8", "surrogateescape") for p in git("ls-files", "--cached", "-z").split(b"\0") if p)


def history_paths(ref):
    # Inspect every tree, not just the final diff: deleted files remain in history.
    if ref.startswith("-"):
        raise ValueError("Invalid ref")
    commits = git("rev-list", ref, "--").decode().splitlines()
    paths = set()
    for commit in commits:
        paths.update(p.decode("utf-8", "surrogateescape") for p in
                     git("ls-tree", "-r", "--name-only", "-z", commit).split(b"\0") if p)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--ref", action="append")
    group.add_argument("--pre-push", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.staged:
            paths = index_paths()
        else:
            refs = args.ref or []
            if args.pre_push:
                for line in sys.stdin:
                    fields = line.split()
                    if len(fields) != 4:
                        raise ValueError("Malformed pre-push ref record")
                    if set(fields[1]) != {"0"}:
                        refs.append(fields[1])
            paths = set()
            for ref in refs:
                paths.update(history_paths(ref))
        blocked = sorted(p for p in paths if protected(p))
        if blocked:
            print("Publication blocked: local-only planning material is present:", file=sys.stderr)
            for path in blocked:
                print("  " + path, file=sys.stderr)
            print("Preserve a local copy; remove it from the unpublished index/history. Do not bypass this check.", file=sys.stderr)
            return 1
        print("Publication check passed: no protected planning files.")
        return 0
    except (subprocess.CalledProcessError, ValueError) as exc:
        print("Publication check could not verify history: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
