import pytest
from unittest.mock import patch
from pydantic import ValidationError


class TestConfig:
    def test_loads_mock_provider(self):
        with patch.dict("os.environ", {
            "BOT_PROVIDER": "mock",
            "ANTHROPIC_API_KEY": "test-key",
        }):
            from config import Settings
            s = Settings()
            assert s.BOT_PROVIDER == "mock"

    def test_loads_vexa_provider(self):
        with patch.dict("os.environ", {
            "BOT_PROVIDER": "vexa",
            "ANTHROPIC_API_KEY": "test-key",
        }):
            from config import Settings
            s = Settings()
            assert s.BOT_PROVIDER == "vexa"

    def test_missing_api_key_defaults_to_empty_string(self):
        # ANTHROPIC_API_KEY defaults to "" so tests can import without a .env file.
        # The Anthropic client will reject an empty key at call time, not at startup.
        # _env_file=None bypasses the local .env so only env vars are consulted.
        import os
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            from config import Settings
            s = Settings(_env_file=None)
            assert s.ANTHROPIC_API_KEY == ""

    def test_default_model_is_opus(self):
        with patch.dict("os.environ", {
            "ANTHROPIC_API_KEY": "test-key",
        }):
            from config import Settings
            s = Settings()
            assert s.ANTHROPIC_MODEL == "claude-opus-4-8"

    def test_default_provider_is_mock(self):
        with patch.dict("os.environ", {
            "ANTHROPIC_API_KEY": "test-key",
        }):
            from config import Settings
            s = Settings(_env_file=None)
            assert s.BOT_PROVIDER == "mock"
