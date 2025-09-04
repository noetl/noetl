SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
-- SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

CREATE EXTENSION IF NOT EXISTS plpython3u WITH SCHEMA pg_catalog;

SET search_path TO :"SCHEMA_NAME", pg_catalog;

CREATE TABLE IF NOT EXISTS test_data_table (
    id SERIAL PRIMARY KEY,                    -- Auto-incrementing primary key
    name TEXT NOT NULL,                       -- Text data
    age INTEGER,                              -- Integer for numerical data
    created_at TIMESTAMP DEFAULT now(),       -- Timestamp with default current time
    is_active BOOLEAN DEFAULT true,           -- Boolean flag
    meta_data JSONB,                          -- JSONB for structured data
    description TEXT                          -- Text field to test large multi-line data
);

COMMENT ON TABLE test_data_table IS 'Table for testing data loading and exporting with multiline support.';
COMMENT ON COLUMN test_data_table.meta_data IS 'Contains JSONB data for structured information.';
COMMENT ON COLUMN test_data_table.description IS 'Contains large multiline text data for validation purposes.';

INSERT INTO test_data_table (name, age, meta_data, description)
VALUES
('Alice', 30, '{"key_1": "value_1", "key_2": 123}'::jsonb, 'Line 1\nLine 2\nLine 3'),
('Bob', 25, '{"key_1": "value_2", "key_2": 456}'::jsonb, 'This is a\nmultiline description\nfor Bob.'),
('Charlie', 40, '{"key_1": "value_3", "key_3": "extra_key"}'::jsonb, 'Description\nwith only two lines.'),
('Daisy', 35, '{"key_4": "value_4", "nested_key": {"inner_key": "value"}}'::jsonb, 'Another\nexample\nof multiline text.'),
('Eva', NULL, NULL, 'NULL JSON\nand AGE values.');

-- CREATE TABLE IF NOT EXISTS resource (
--     name TEXT PRIMARY KEY
-- );
--
-- CREATE TABLE IF NOT EXISTS catalog (
--     resource_path     TEXT     NOT NULL,
--     resource_type     TEXT     NOT NULL REFERENCES resource(name),
--     resource_version  TEXT     NOT NULL,
--     source            TEXT     NOT NULL DEFAULT 'inline',
--     resource_location TEXT,
--     content           TEXT,
--     payload           JSONB    NOT NULL,
--     meta              JSONB,
--     template          TEXT,
--     timestamp         TIMESTAMPTZ NOT NULL DEFAULT now(),
--     PRIMARY KEY (resource_path, resource_version)
-- );
--
--
-- CREATE TABLE IF NOT EXISTS event_log (
--     execution_id VARCHAR,
--     event_id VARCHAR,
--     parent_event_id VARCHAR,
--     timestamp TIMESTAMP,
--     event_type VARCHAR,
--     node_id VARCHAR,
--     node_name VARCHAR,
--     node_type VARCHAR,
--     status VARCHAR,
--     duration DOUBLE PRECISION,
--     input_context TEXT,
--     output_result TEXT,
--     metadata TEXT,
--     error TEXT,
--     loop_id VARCHAR,
--     loop_name VARCHAR,
--     iterator VARCHAR,
--     items TEXT,
--     current_index INTEGER,
--     current_item TEXT,
--     results TEXT,
--     worker_id VARCHAR,
--     distributed_state VARCHAR,
--     context_key VARCHAR,
--     context_value TEXT,
--     PRIMARY KEY (execution_id, event_id)
-- );
--
-- CREATE TABLE IF NOT EXISTS workflow (
--     execution_id VARCHAR,
--     step_id VARCHAR,
--     step_name VARCHAR,
--     step_type VARCHAR,
--     description TEXT,
--     raw_config TEXT,
--     PRIMARY KEY (execution_id, step_id)
-- );
--
-- CREATE TABLE IF NOT EXISTS workbook (
--     execution_id VARCHAR,
--     task_id VARCHAR,
--     task_name VARCHAR,
--     task_type VARCHAR,
--     raw_config TEXT,
--     PRIMARY KEY (execution_id, task_id)
-- );
--
-- CREATE TABLE IF NOT EXISTS workload (
--     execution_id VARCHAR,
--     timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
--     data TEXT,
--     PRIMARY KEY (execution_id)
-- );
--
-- CREATE TABLE IF NOT EXISTS transition (
--     execution_id VARCHAR,
--     from_step VARCHAR,
--     to_step VARCHAR,
--     condition TEXT,
--     with_params TEXT,
--     PRIMARY KEY (execution_id, from_step, to_step, condition)
-- );
