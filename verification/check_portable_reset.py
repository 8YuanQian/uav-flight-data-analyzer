# 仅用于独立的临时部署验证；不允许指向日常正式或测试项目。
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--project", required=True)
    options = parser.parse_args()
    directory = options.directory.resolve(strict=True)
    if (not options.project.startswith("uav-portable-check-")
            or not directory.name.startswith("portable_stack_")):
        raise RuntimeError("只允许操作本次创建的独立验证项目")
    compose = ["docker", "compose", "-p", options.project]
    for filename in ("compose.yaml", "compose.test.yaml", "compose.local.yaml", "compose.test.local.yaml"):
        compose += ["-f", filename]

    def command(arguments):
        result = subprocess.run(arguments, cwd=directory, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    def sql(database, statement):
        assert database in {"uav_project", "uav_project_test"}
        return command(compose + ["exec", "-T", "postgres", "psql", "-U", "postgres",
                                   "-d", database, "-XAt", "-v", "ON_ERROR_STOP=1", "-c", statement])

    def redis(number, *arguments):
        assert number in range(6)
        return command(compose + ["exec", "-T", "redis", "redis-cli", "-n", str(number), *arguments])

    def python(service, source, one_off=False):
        assert service in {"worker", "worker-test"}
        arguments = ["run", "--rm", "--no-deps", "-T"] if one_off else ["exec", "-T"]
        return command(compose + arguments + [service, "python", "-c", source])

    assert sql("uav_project", "SELECT count(*) FROM users") == "0", "验证库必须从空数据开始"
    assert sql("uav_project_test", "SELECT count(*) FROM users") == "0", "验证库必须从空数据开始"
    sql("uav_project", "INSERT INTO users(username) VALUES('keep-formal')")
    sql("uav_project_test", "INSERT INTO users(username) VALUES('remove-test')")
    for number in range(6):
        redis(number, "SET", "portable-verification", str(number))
    python("worker", "from pathlib import Path; Path('/app/upload_spool/formal.csv').write_text('keep')", True)
    python("worker-test", "from pathlib import Path; Path('/app/upload_spool/test.csv').write_text('remove')")
    config = json.loads(command(compose + ["config", "--format", "json"]))
    volumes = [value["name"] for value in config["volumes"].values() if "name" in value]
    volumes = [name for name in volumes if name.endswith(("postgres_data", "redis_data", "csv_uploads", "csv_test_uploads", "tokenizer_cache"))]
    before_secret = (directory / ".env.test").read_bytes()
    migration_count = sql("uav_project_test", "SELECT count(*) FROM checkpoint_migrations")
    reset = ["powershell.exe", "-NoProfile", "-File", "scripts/reset_test_environment.ps1",
             "-ProjectName", options.project, "-UseLocalCache"]
    command(reset)
    assert sql("uav_project_test", "SELECT count(*) FROM users") == "1", "预览不能清数据"
    assert (directory / ".env.test").read_bytes() == before_secret
    command(reset + ["-Execute"])
    assert sql("uav_project_test", "SELECT count(*) FROM users") == "0"
    assert sql("uav_project", "SELECT username FROM users") == "keep-formal"
    assert sql("uav_project_test", "SELECT count(*) FROM checkpoint_migrations") == migration_count
    assert (directory / ".env.test").read_bytes() != before_secret
    for number in range(6):
        expected = str(number) if number < 3 else ""
        assert redis(number, "GET", "portable-verification") == expected
    assert python("worker", "from pathlib import Path; print(Path('/app/upload_spool/formal.csv').read_text())", True) == "keep"
    assert python("worker-test", "from pathlib import Path; print(len(list(Path('/app/upload_spool').iterdir())))") == "0"
    for volume in volumes:
        assert command(["docker", "volume", "inspect", "--format", "{{.Name}}", volume]) == volume
    print("PASS: 预览无写入；执行只清测试库、Redis /3～/5 和测试 CSV；正式数据、正式 CSV、迁移记录及全部已用数据卷保留；测试服务恢复。")


if __name__ == "__main__":
    main()
