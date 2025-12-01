-- Sample SQL script for testing script attribute from file source
-- This script demonstrates basic table operations

-- Create a test table
DROP TABLE IF EXISTS public.script_test;

CREATE TABLE public.script_test (
    id SERIAL PRIMARY KEY,
    message TEXT NOT NULL,
    source VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert test data
INSERT INTO public.script_test (message, source)
VALUES
    ('Script execution test - file source', 'file'),
    ('External SQL script loaded successfully', 'file'),
    ('NoETL script attribute working', 'file');

-- Return count
SELECT COUNT(*) as total_records, 'file' as script_source
FROM public.script_test;
