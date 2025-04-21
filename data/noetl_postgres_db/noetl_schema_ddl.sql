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

-- Table to test data loading/exporting
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

-- resource categories
CREATE TABLE resource_type (
    name TEXT PRIMARY KEY
);

-- source can be 'inline', 'gcs', 'filesystem', etc.
-- resource_location like GCS URL.
-- payload is DSL JSON for that version.
-- meta is for resource related metadata.
CREATE TABLE catalog (
    resource_path     TEXT     NOT NULL,
    resource_type     TEXT     NOT NULL REFERENCES resource_type(name),
    resource_version  TEXT     NOT NULL,
    source            TEXT     NOT NULL DEFAULT 'inline',
    resource_location TEXT,
    payload           JSONB    NOT NULL,
    meta              JSONB,
    timestamp         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (resource_path, resource_version)
);

-- event categories
CREATE TABLE event_type (
    name TEXT PRIMARY KEY,
    template TEXT NOT NULL
);

CREATE TABLE event (
    event_id         TEXT         NOT NULL,
    event_type       TEXT         NOT NULL REFERENCES event_type(name),
    resource_path    TEXT         NOT NULL,
    resource_version TEXT         NOT NULL,
    payload          JSONB,
    meta             JSONB,
    timestamp        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    FOREIGN KEY (resource_path, resource_version)
        REFERENCES catalog(resource_path, resource_version)
) PARTITION BY RANGE (timestamp);

-- partition of the event table
CREATE TABLE event_2025_04 PARTITION OF event
FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');

CREATE TABLE event_2025_05 PARTITION OF event
FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');

CREATE TABLE event_2025_06 PARTITION OF event
FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');

CREATE TABLE event_2025_07 PARTITION OF event
FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');

CREATE TABLE event_2025_08 PARTITION OF event
FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');

CREATE TABLE event_2025_09 PARTITION OF event
FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');

CREATE TABLE event_2025_10 PARTITION OF event
FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');

CREATE TABLE event_2025_11 PARTITION OF event
FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');

CREATE TABLE event_2025_12 PARTITION OF event
FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

INSERT INTO resource_type (name) VALUES
    ('playbook'),
    ('workflow'),
    ('target'),
    ('step'),
    ('task'),
    ('action');

INSERT INTO event_type (name, template) VALUES
    ('REGISTERED',          'Resource {{ resource_path }} version {{ resource_version }} was registered.'),
    ('UPDATED',             'Resource {{ resource_path }} version {{ resource_version }} was updated.'),
    ('UNCHANGED',           'Resource {{ resource_path }} already registered.'),
    ('EXECUTION_STARTED',   'Execution started for {{ resource_path }}.'),
    ('EXECUTION_FAILED',    'Execution failed for {{ resource_path }}.'),
    ('EXECUTION_COMPLETED', 'Execution completed for {{ resource_path }}.');

