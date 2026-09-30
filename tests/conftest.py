import pytest

from core import groq_client, storage
from core.config import Settings


def no_network(messages, settings):
    raise AssertionError("Tests must not call the model.")


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    monkeypatch.setenv("RFP_DB", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("LLM_MODE", "offline")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(groq_client, "ask", no_network)
    storage.prepare_database()
    yield tmp_path / "test.sqlite"


@pytest.fixture
def offline():
    return Settings(api_key="", model="test-model", live=False)


@pytest.fixture
def fake_live():
    return Settings(api_key="gsk_test_secret_value", model="test-model", live=True)
