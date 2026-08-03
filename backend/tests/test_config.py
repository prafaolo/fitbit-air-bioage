from bioage.config import Settings


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/bioage"
    assert settings.google_client_id == "abc.apps.googleusercontent.com"


def test_scheduler_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    assert Settings().sync_schedule_enabled is False


def test_is_google_configured_false_when_credentials_absent(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert Settings().is_google_configured is False


def test_is_google_configured_true_when_both_present(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shh")
    assert Settings().is_google_configured is True
