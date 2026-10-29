import os
import psycopg

PASSWORD = os.getenv("PASSWORD")
DB_NAME = os.getenv("UAV_DB_NAME","uav_project")
PORT = os.getenv("PORT",5433)

def get_connection():
    conn = psycopg.connect(host="localhost",port=PORT,dbname=DB_NAME,user="postgres",password=PASSWORD)
    return conn


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


def get_flight_analysis(analysis_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("SELECT * FROM flight_analyses WHERE id = %s",(analysis_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return row
