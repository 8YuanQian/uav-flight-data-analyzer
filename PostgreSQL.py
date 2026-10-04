import psycopg
import os


PASSWORD = os.getenv("PASSWORD")

value = ("insert_filename_first",20,10,13,15,56,88,46,None)
try:
    with psycopg.connect(host="localhost",dbname="uav_project",user="postgres",password=PASSWORD) as conn:
        with conn.cursor() as cursor:
            cursor.execute("""INSERT INTO flight_analyses (
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
                        RETURNING id""",
                        value)
            row = cursor.fetchone()
except psycopg.Error as e:
    print(f"Database error {e}")

print(f"INSERT successful id is {row[0]}")

# cursor.execute("SELECT * FROM flight_analyses WHERE id = 1;")
# row = cursor.fetchone()
# print(row)
# row = cursor.fetchone()
# print(f"Inserted analysis id: {row[0]}")
# conn.commit()
# cursor.close()
# conn.close()
