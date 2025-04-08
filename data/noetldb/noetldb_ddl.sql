SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

CREATE EXTENSION IF NOT EXISTS plpython3u WITH SCHEMA pg_catalog;

-- Table to test data loading/exporting
CREATE TABLE IF NOT EXISTS :"SCHEMA_NAME".test_data_table (
    id SERIAL PRIMARY KEY,                    -- Auto-incrementing primary key
    name TEXT NOT NULL,                       -- Text data
    age INTEGER,                              -- Integer for numerical data
    created_at TIMESTAMP DEFAULT now(),       -- Timestamp with default current time
    is_active BOOLEAN DEFAULT true,           -- Boolean flag
    meta_data JSONB,                          -- JSONB for structured data
    description TEXT                          -- Text field to test large multi-line data
);

COMMENT ON TABLE :"SCHEMA_NAME".test_data_table IS 'Table for testing data loading and exporting with multiline support.';
COMMENT ON COLUMN :"SCHEMA_NAME".test_data_table.meta_data IS 'Contains JSONB data for structured information.';
COMMENT ON COLUMN :"SCHEMA_NAME".test_data_table.description IS 'Contains large multiline text data for validation purposes.';

INSERT INTO :"SCHEMA_NAME".test_data_table (name, age, meta_data, description)
VALUES
('Alice', 30, '{"key_1": "value_1", "key_2": 123}'::jsonb, 'Line 1\nLine 2\nLine 3'),
('Bob', 25, '{"key_1": "value_2", "key_2": 456}'::jsonb, 'This is a\nmultiline description\nfor Bob.'),
('Charlie', 40, '{"key_1": "value_3", "key_3": "extra_key"}'::jsonb, 'Description\nwith only two lines.'),
('Daisy', 35, '{"key_4": "value_4", "nested_key": {"inner_key": "value"}}'::jsonb, 'Another\nexample\nof multiline text.'),
('Eva', NULL, NULL, 'NULL JSON\nand AGE values.');