CREATE TABLE uav_demo (id INTEGER PRIMARY KEY,filename TEXT,average_height DOUBLE PRECISION);
INSERT INTO uav_demo (id,filename,average_height)
    VALUES (1,'first_file',100.00);
INSERT INTO uav_demo (id,filename,average_height)
    VALUES (2,'second_file',101.02);


CREATE TABLE flight_analyses (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filename TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INTEGER NOT NULL,
    average_height DOUBLE PRECISION NOT NULL,
    average_speed DOUBLE PRECISION NOT NULL,
    average_temperature DOUBLE PRECISION NOT NULL,
    max_height DOUBLE PRECISION NOT NULL,
    max_speed DOUBLE PRECISION NOT NULL,
    max_temperature DOUBLE PRECISION NOT NULL,
    minimum_battery DOUBLE PRECISION NOT NULL
);

INSERT INTO flight_analyses (filename,row_count,average_height,average_speed,average_temperature,max_height,max_speed,max_temperature,minimum_battery)
VALUES ('DELETE_file_first',10,95.05,11,23,12,21,53,20);


SELECT * FROM flight_analyses WHERE id = 2;
SELECT * FROM flight_analyses WHERE filename = 'analysis_file_first';
SELECT * FROM flight_analyses ORDER BY created_at DESC LIMIT 2;


UPDATE flight_analyses set filename = 'UPEATE_file_second' WHERE id = 5;
DELETE FROM flight_analyses WHERE filename = 'DELETE_file_first'; 
