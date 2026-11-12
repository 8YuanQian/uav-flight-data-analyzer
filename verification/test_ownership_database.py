# 可选实库验证：只连接测试库，所有示例行在同一个外层事务中回滚。
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from src.auth.data_scope import use_data_user
from src.database import flight_record_repository as flights
from src.database import uav_repository as uavs


def ownership_database_settings():
    # 只读取运行环境，不隐式使用正式 .env，也不连接宿主机的旧映射端口。
    database = os.getenv("UAV_DB_NAME")
    if database != "uav_project_test":
        raise ValueError("实库权限测试只允许连接 uav_project_test")
    host = os.getenv("UAV_DB_HOST", "postgres").strip()
    port = int(os.getenv("UAV_DB_PORT", os.getenv("PORT", "5432")))
    password = os.getenv("PASSWORD")
    if not host or not 1 <= port <= 65535:
        raise ValueError("数据库主机或端口配置无效")
    if not password:
        raise ValueError("实库权限测试需要 PASSWORD 环境变量")
    return {
        "host": host, "port": port, "dbname": database, "user": "postgres",
        "password": password, "autocommit": True,
    }


@pytest.mark.skipif(os.getenv("RUN_OWNERSHIP_DB_TEST") != "1", reason="显式启用测试库权限验证")
def test_two_users_are_isolated_and_database_rejects_mismatched_owner(monkeypatch):
    connection = psycopg.connect(**ownership_database_settings())
    assert connection.info.dbname == "uav_project_test"
    with connection:
        before = connection.execute("SELECT count(*) FROM users").fetchone()[0]
        with connection.transaction(force_rollback=True):
            @contextmanager
            def nested_connection():
                with connection.transaction():
                    yield connection
            monkeypatch.setattr(flights, "get_connection", nested_connection)
            monkeypatch.setattr(uavs, "get_connection", nested_connection)
            suffix = uuid4().hex
            ids = [
                connection.execute("INSERT INTO users(username) VALUES(%s) RETURNING id",
                                   (f"permission-{name}-{suffix}",)).fetchone()[0]
                for name in ("alice", "bob")
            ]
            start = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
            group = {
                "uav_code": f"PERM-{suffix}-A", "uav_model": "M", "manufacturer": "Maker",
                "csv_flight_id": "group-1", "start_time": start,
                "end_time": start + timedelta(minutes=30), "duration_minutes": 30,
                "row_count": 2, "average_height": 20, "max_height": 25,
                "average_speed": 8, "max_speed": 10, "battery_start": 90,
                "battery_end": 80, "minimum_battery": 80, "average_temperature": 25,
                "max_temperature": 27, "anomaly_status": "normal", "anomaly_reason": None,
            }
            with use_data_user(ids[0]):
                first = flights.save_flight_groups("permissions.csv", [group])[0]
                assert uavs.get_user_uav(first["uav_id"]) is not None
                assert flights.get_flight_by_id(first["id"], user_id=ids[0])["id"] == first["id"]
            with use_data_user(ids[1]):
                second = flights.save_flight_groups("permissions.csv", [
                    {**group, "uav_code": f"PERM-{suffix}-B"}
                ])[0]
                assert flights.get_flight_by_id(first["id"], user_id=ids[1]) is None
                assert uavs.get_user_uav(first["uav_id"]) is None
                assert flights.get_recent_flights(10, uav_id=first["uav_id"], user_id=ids[1]) == []
                assert [r["id"] for r in flights.get_recent_flights(10, user_id=ids[1])] == [second["id"]]
                assert flights.update_flight_record(first["id"], 1, "forged.csv", group) is None
                with pytest.raises(uavs.UavOwnershipConflict):
                    flights.save_flight_groups("forged.csv", [group])
                assert not flights.user_owns_flight_records([first["id"]], user_id=ids[1])
                from app import tasks
                from unittest.mock import MagicMock
                report = MagicMock()
                monkeypatch.setattr(tasks, "generate_flight_report", report)
                with pytest.raises(ValueError, match="does not exist"):
                    tasks._generate_report(first["id"], None)
                report.assert_not_called()
            # 复合外键阻止绕过仓储函数把记录写到别人的飞行器下。
            columns = ("uav_id", "filename", "user_id", *flights.RECORD_COLUMNS)
            values = (first["uav_id"], "forged.csv", ids[1], *(group[c] for c in flights.RECORD_COLUMNS))
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with connection.transaction():
                    connection.execute(
                        f"INSERT INTO flight_records ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
                        values,
                    )
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO uavs(uav_code,uav_model,manufacturer) VALUES(%s,'M','Maker')",
                        (f"PERM-{suffix}-NO-OWNER",),
                    )
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == before

