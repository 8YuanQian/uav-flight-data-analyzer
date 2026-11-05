import psycopg
from .connection import get_connection


def get_flight_records(limit):
    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("SELECT * FROM flight_analyses ORDER BY created_at DESC LIMIT %s;",(limit,))
            data = cursor.fetchall()
            return data
        

def save_flight_analysis(filename,summary):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO flight_analyses(
                        filename,
                        row_count,
                        average_height,
                        average_speed,
                        average_temperature,
                        max_height,
                        max_speed,
                        max_temperature,
                        minimum_battery)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id;""",
                        (filename,
                        summary["row_count"],
                        summary["average_height"],
                        summary["average_speed"],
                        summary["average_temperature"],
                        summary["max_height"],
                        summary["max_speed"],
                        summary["max_temperature"],
                        summary["minimum_battery"]))
            row = cursor.fetchone()
    return row[0]


class FlightAnalysisVersionConflict(Exception):
    """记录存在，但客户端提交的版本已经过期。"""


def update_flight_analysis(analysis_id, expected_version, filename, summary):
    """在同一条 UPDATE 中检查旧版本并递增；未命中时, 区分 404 和冲突。"""
    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """UPDATE flight_analyses
                   SET filename = %s,
                       row_count = %s,
                       average_height = %s,
                       average_speed = %s,
                       average_temperature = %s,
                       max_height = %s,
                       max_speed = %s,
                       max_temperature = %s,
                       minimum_battery = %s,
                       version = version + 1
                   WHERE id = %s AND version = %s
                   RETURNING *""",
                (
                    filename,
                    summary["row_count"],
                    summary["average_height"],
                    summary["average_speed"],
                    summary["average_temperature"],
                    summary["max_height"],
                    summary["max_speed"],
                    summary["max_temperature"],
                    summary["minimum_battery"],
                    analysis_id,
                    expected_version,
                ),
            )
            row = cursor.fetchone()
            if row is not None:
                return row

            cursor.execute("SELECT 1 FROM flight_analyses WHERE id = %s", (analysis_id,))
            if cursor.fetchone() is None:
                return None
            raise FlightAnalysisVersionConflict


def get_flight_analysis(analysis_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("SELECT * FROM flight_analyses WHERE id = %s",(analysis_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return row
