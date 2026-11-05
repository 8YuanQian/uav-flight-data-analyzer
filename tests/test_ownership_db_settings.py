# 只检查配置读取和测试库保护，不建立真实数据库连接。
import pytest

from verification.test_ownership_database import ownership_database_settings


def test_ownership_database_settings_use_runtime_environment(monkeypatch):
    monkeypatch.setenv("UAV_DB_HOST", "custom-postgres")
    monkeypatch.setenv("UAV_DB_PORT", "5544")
    monkeypatch.setenv("UAV_DB_NAME", "uav_project_test")
    monkeypatch.setenv("PASSWORD", "test-only-password")
    monkeypatch.setenv("PORT", "9999")

    assert ownership_database_settings() == {
        "host": "custom-postgres", "port": 5544, "dbname": "uav_project_test",
        "user": "postgres", "password": "test-only-password", "autocommit": True,
    }


def test_ownership_database_defaults_match_compose_services(monkeypatch):
    monkeypatch.setenv("UAV_DB_NAME", "uav_project_test")
    monkeypatch.setenv("PASSWORD", "test-only-password")
    for name in ("UAV_DB_HOST", "UAV_DB_PORT", "PORT"):
        monkeypatch.delenv(name, raising=False)

    settings = ownership_database_settings()
    assert (settings["host"], settings["port"]) == ("postgres", 5432)


@pytest.mark.parametrize("database", [None, "uav_project"])
def test_ownership_database_rejects_missing_or_production_database(monkeypatch, database):
    if database is None:
        monkeypatch.delenv("UAV_DB_NAME", raising=False)
    else:
        monkeypatch.setenv("UAV_DB_NAME", database)

    with pytest.raises(ValueError, match="只允许连接 uav_project_test"):
        ownership_database_settings()


def test_ownership_database_requires_password(monkeypatch):
    monkeypatch.setenv("UAV_DB_NAME", "uav_project_test")
    monkeypatch.setenv("UAV_DB_HOST", "postgres")
    monkeypatch.setenv("UAV_DB_PORT", "5432")
    monkeypatch.delenv("PASSWORD", raising=False)

    with pytest.raises(ValueError, match="PASSWORD"):
        ownership_database_settings()
