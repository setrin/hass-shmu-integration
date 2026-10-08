"""Shared captured SHMÚ fixtures. No live network is needed for tests."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_data():
    def load(name):
        return json.loads((FIXTURES / f"{name}.json").read_text())

    return load


@pytest.fixture(autouse=True)
def aiohttp_mock_compatibility(monkeypatch):
    """aioresponses 0.7.9 predates aiohttp 3.14's required stream_writer argument.

    Supply the missing mock-only argument; production HTTP behavior is unchanged.
    """
    import inspect
    from unittest.mock import Mock

    from aiohttp import ClientResponse

    original = ClientResponse.__init__
    if "stream_writer" in inspect.signature(original).parameters:

        def init(self, *args, **kwargs):
            kwargs.setdefault("stream_writer", Mock(output_size=0))
            original(self, *args, **kwargs)

        monkeypatch.setattr(ClientResponse, "__init__", init)
