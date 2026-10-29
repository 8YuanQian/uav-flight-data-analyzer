-- Existing rows start at version 1; future updates compare and increment it atomically.
ALTER TABLE flight_analyses
ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 1;
