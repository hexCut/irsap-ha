"""Check a GitHub release before HACS users get it.

Run by .github/workflows/release-check.yml when a release is published.
Reads the release from the environment (TAG, PRERELEASE) and the checked-out
tagged commit, and fails if:

- the tag is not vX.Y, vX.Y.Z or a beta like vX.YbN;
- custom_components/irsap_ha/manifest.json at that commit has another version;
- a beta is not marked as pre-release, or a stable version is;
- a beta was not published from `dev`, or a stable version from `main`.

Usage outside CI (from the repository root, after `git fetch origin`):
    TAG=v1.6b8 PRERELEASE=true python .github/scripts/check_release.py
"""

import json
import os
import re
import subprocess
import sys

MANIFEST = "custom_components/irsap_ha/manifest.json"
TAG_PATTERN = re.compile(r"^v(\d+\.\d+(?:\.\d+)?)(b\d+)?$")


def branches_containing(commit):
    out = subprocess.run(
        ["git", "branch", "-r", "--contains", commit],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        line.strip().removeprefix("origin/")
        for line in out.splitlines()
        if "->" not in line  # skip "origin/HEAD -> origin/main"
    }


def check(tag, prerelease, manifest_version, branches):
    """Return the list of problems (empty if the release is consistent)."""
    problems = []

    match = TAG_PATTERN.match(tag)
    if not match:
        problems.append(
            f"Tag `{tag}` is not in the expected form: `v1.6` or `v1.6.1` for a "
            "release, `v1.6b8` for a beta (lowercase `v` at the start)."
        )
        return problems

    version = tag[1:]
    is_beta = match.group(2) is not None

    if manifest_version != version:
        problems.append(
            f"`{MANIFEST}` at this commit says `{manifest_version}`, but the tag "
            f"is `{tag}`. Update the manifest on the branch **before** "
            "publishing the release."
        )

    if is_beta and not prerelease:
        problems.append(
            f"`{tag}` is a beta but the release is not marked as pre-release: "
            "HACS would offer it to every user."
        )
    if not is_beta and prerelease:
        problems.append(
            f"`{tag}` is a stable version but the release is marked as "
            "pre-release."
        )

    expected = "dev" if is_beta else "main"
    if expected not in branches:
        found = ", ".join(sorted(branches)) or "no branch"
        problems.append(
            f"The tagged commit is on {found}, not on `{expected}`. "
            f"{'Betas' if is_beta else 'Stable releases'} must be published "
            f"with target `{expected}`."
        )

    return problems


def main():
    tag = os.environ["TAG"]
    prerelease = os.environ.get("PRERELEASE", "false").lower() == "true"

    with open(MANIFEST, encoding="utf-8") as f:
        manifest_version = json.load(f).get("version")

    problems = check(tag, prerelease, manifest_version, branches_containing("HEAD"))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if problems:
        lines = [f"## ❌ Release `{tag}` is inconsistent", ""]
        lines += [f"- {p}" for p in problems]
        lines += [
            "",
            "The release has been turned back into a **draft**, so HACS users "
            "won't get it. Fix the problems, then delete the draft release and "
            "its tag and publish it again.",
        ]
        for p in problems:
            print(f"::error::{p}")
    else:
        lines = [f"## ✅ Release `{tag}` is consistent", ""]
        lines.append(f"Manifest `{manifest_version}`, published from the right branch.")
        print(f"Release {tag} OK (manifest {manifest_version})")

    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
