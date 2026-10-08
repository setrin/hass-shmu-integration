"""Validate a stable release before any tag or GitHub Release is created."""

import json
import os
import re
import subprocess
from pathlib import Path

VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def validate_release(version: str, manifest_version: str, tags: list[str], ref: str) -> str:
    """Require main, a matching stable manifest version, and a newer unused tag."""
    if ref != "refs/heads/main":
        raise ValueError("Releases must run from the main branch")
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError("Enter a stable version such as 0.1.1, without a v prefix")
    if version != manifest_version:
        raise ValueError(f"Requested {version}, but manifest.json contains {manifest_version}")
    tag = f"v{version}"
    if tag in tags or version in tags:
        raise ValueError(f"Version {version} already has a tag; use a new version")
    current = tuple(map(int, match.groups()))
    for existing in tags:
        if previous := VERSION.fullmatch(existing.removeprefix("v")):
            if current <= tuple(map(int, previous.groups())):
                raise ValueError(f"Version {version} must be newer than existing tag {existing}")
    return tag


def main():
    manifest = json.loads(Path("custom_components/shmu/manifest.json").read_text())
    tags = subprocess.check_output(["git", "tag", "--list"], text=True).splitlines()
    tag = validate_release(
        os.environ["RELEASE_VERSION"], manifest["version"], tags, os.environ["GITHUB_REF"]
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"tag={tag}\n")
    print(f"Validated {tag}; manifest version matches and tag is unused")


if __name__ == "__main__":
    main()
