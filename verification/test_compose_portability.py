# 验证实际合并结果，防止测试服务继承正式数据库、JWT 或文件卷。
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from scripts import prepare_models


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def compose_directory(tmp_path):
    for name in ("compose.yaml", "compose.test.yaml", "compose.local.yaml", "compose.test.local.yaml"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    (tmp_path / ".env").write_text(
        "PASSWORD=verification-only\nJWT_SECRET_KEY=" + "formal-" * 8 + "\n", encoding="utf-8"
    )
    (tmp_path / ".env.test").write_text("JWT_SECRET_KEY=" + "test-" * 8 + "\n", encoding="utf-8")
    return tmp_path


def configuration(directory, local=False):
    command = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.test.yaml"]
    if local:
        command += ["-f", "compose.local.yaml", "-f", "compose.test.local.yaml"]
    command += ["--profile", "testing", "config", "--format", "json"]
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PASSWORD", "JWT_SECRET_KEY", "COMPOSE_PROJECT_NAME",
                                  "COMPOSE_FILE", "UAV_API_PORT", "UAV_TEST_API_PORT"}}
    result = subprocess.run(command, cwd=directory, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("local", [False, True])
def test_formal_and_test_services_remain_isolated(compose_directory, local):
    config = configuration(compose_directory, local)
    services = config["services"]
    for name, database, databases, csv_volume in (
        ("api", "uav_project", (0, 1, 2), "csv_uploads"),
        ("worker", "uav_project", (0, 1, 2), "csv_uploads"),
        ("api-test", "uav_project_test", (3, 4, 5), "csv_test_uploads"),
        ("worker-test", "uav_project_test", (3, 4, 5), "csv_test_uploads"),
    ):
        service = services[name]
        environment = service["environment"]
        assert environment["UAV_DB_HOST"] == "postgres"
        assert environment["UAV_DB_NAME"] == database
        for variable, number in zip(("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "REDIS_CACHE_URL"), databases):
            assert environment[variable] == f"redis://redis:6379/{number}"
        mounts = {mount["target"]: mount for mount in service["volumes"]}
        assert mounts["/app/upload_spool"]["source"] == csv_volume
        assert "/app/logs_original" not in mounts
        assert "/UAV_project/logs" not in mounts["/app/logs"]["source"].replace("\\", "/")
        assert service["depends_on"]["db-init"]["condition"] == "service_completed_successfully"
        assert service["depends_on"]["model-init"]["condition"] == "service_completed_successfully"
        if local:
            assert mounts["/models-cache"]["source"].replace("\\", "/") == "E:/CodexEnv/cache/huggingface-docker"
        else:
            assert mounts["/models-cache"]["type"] == "volume"
    assert services["api"]["environment"]["JWT_SECRET_KEY"] != services["api-test"]["environment"]["JWT_SECRET_KEY"]
    assert services["api-test"]["environment"]["JWT_SECRET_KEY"] == services["worker-test"]["environment"]["JWT_SECRET_KEY"]
    assert services["api"]["ports"][0]["published"] == "8002"
    assert services["api-test"]["ports"][0]["published"] == "8003"
    assert not any(network.get("external") for network in config["networks"].values())
    assert services["postgres"]["image"] == "pgvector/pgvector:pg17"


def test_complete_cache_does_not_trigger_download(monkeypatch):
    run = []
    monkeypatch.setattr(prepare_models.subprocess, "run", lambda *args, **kwargs: (
        run.append(kwargs) or SimpleNamespace(returncode=0)
    ))
    monkeypatch.setattr(prepare_models, "load_resources", lambda: pytest.fail("完整缓存不应重新下载"))
    prepare_models.main()
    assert len(run) == 1
    assert run[0]["env"]["HF_HUB_OFFLINE"] == "1"


def test_missing_cache_is_prepared_then_verified_offline(monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(("check", kwargs))
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0)
    monkeypatch.setattr(prepare_models.subprocess, "run", run)
    monkeypatch.setattr(prepare_models, "load_resources", lambda: calls.append(("prepare", {})))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    prepare_models.main()
    assert [name for name, _ in calls] == ["check", "prepare", "check"]
    assert calls[-1][1]["check"] is True


def test_model_preparation_failure_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(prepare_models.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    def failed():
        raise RuntimeError("模拟资源下载失败")
    monkeypatch.setattr(prepare_models, "load_resources", failed)
    with pytest.raises(RuntimeError, match="资源下载失败"):
        prepare_models.main()
