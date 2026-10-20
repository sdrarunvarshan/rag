"""Production startup rejects a missing or default JWT secret. Local development does not."""

import pytest

from app import config

pytestmark = pytest.mark.unit


def test_production_rejects_the_default_secret(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "JWT_SECRET_KEY", config.DEFAULT_JWT_SECRET)
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        config.assert_production_secrets()


def test_production_rejects_an_empty_secret(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "JWT_SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        config.assert_production_secrets()


def test_production_accepts_a_real_secret(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "JWT_SECRET_KEY", "a-real-production-secret")
    config.assert_production_secrets()


def test_development_allows_the_local_default(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.setattr(config, "JWT_SECRET_KEY", config.DEFAULT_JWT_SECRET)
    config.assert_production_secrets()
