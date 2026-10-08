"""Guard against publishing the wrong version, branch, or an older release."""

import pytest

from scripts.validate_release import validate_release


def test_initial_release():
    assert validate_release("0.1.0", "0.1.0", [], "refs/heads/main") == "v0.1.0"


def test_numeric_version_order():
    assert validate_release("0.10.0", "0.10.0", ["v0.9.0"], "refs/heads/main") == "v0.10.0"


@pytest.mark.parametrize(
    ("version", "manifest", "tags", "ref"),
    [
        ("v0.1.0", "0.1.0", [], "refs/heads/main"),
        ("0.1.0", "0.2.0", [], "refs/heads/main"),
        ("0.1.0", "0.1.0", ["v0.1.0"], "refs/heads/main"),
        ("0.1.0", "0.1.0", ["0.1.0"], "refs/heads/main"),
        ("0.1.0", "0.1.0", ["v0.2.0"], "refs/heads/main"),
        ("0.1.0", "0.1.0", [], "refs/heads/feature"),
        ("0.1.0rc1", "0.1.0rc1", [], "refs/heads/main"),
        ("01.1.0", "01.1.0", [], "refs/heads/main"),
        ("0.1.0\nmalicious", "0.1.0", [], "refs/heads/main"),
    ],
)
def test_invalid_release(version, manifest, tags, ref):
    with pytest.raises(ValueError):
        validate_release(version, manifest, tags, ref)
