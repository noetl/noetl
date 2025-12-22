-- Migration: execution_variable -> transient
-- Date: 2025-12-01
-- Description: Rename execution_variable table to transient and add cache tracking columns

BEGIN;

-- 1. Rename table
ALTER TABLE noetl.execution_variable RENAME TO transient;

-- 2. Rename primary key constraint
ALTER INDEX noetl.execution_variable_pkey RENAME TO transient_pkey;

-- 3. Rename indexes
ALTER INDEX noetl.idx_execution_variable_source RENAME TO idx_transient_source;
ALTER INDEX noetl.idx_execution_variable_type RENAME TO idx_transient_type;

-- 4. Rename check constraint
ALTER TABLE noetl.transient 
  RENAME CONSTRAINT execution_variable_variable_type_check TO transient_type_check;

-- 5. Add access_count column
ALTER TABLE noetl.transient 
  ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0;

-- 6. Rename updated_at to accessed_at
ALTER TABLE noetl.transient 
  RENAME COLUMN updated_at TO accessed_at;

-- 7. Update type constraint to include iterator_state
ALTER TABLE noetl.transient DROP CONSTRAINT IF EXISTS transient_type_check;
ALTER TABLE noetl.transient 
  ADD CONSTRAINT transient_type_check 
  CHECK (variable_type IN ('user_defined', 'step_result', 'computed', 'iterator_state'));

-- 8. Rename columns to match new naming (var_* instead of variable_*)
ALTER TABLE noetl.transient RENAME COLUMN variable_name TO var_name;
ALTER TABLE noetl.transient RENAME COLUMN variable_type TO var_type;
ALTER TABLE noetl.transient RENAME COLUMN variable_value TO var_value;

-- 9. Update constraint with new column name
ALTER TABLE noetl.transient DROP CONSTRAINT IF EXISTS transient_type_check;
ALTER TABLE noetl.transient 
  ADD CONSTRAINT transient_type_check 
  CHECK (var_type IN ('user_defined', 'step_result', 'computed', 'iterator_state'));

-- 10. Create new index on execution_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_transient_execution ON noetl.transient(execution_id);

COMMIT;

-- Verification queries
SELECT 
  'Table renamed successfully' as status,
  count(*) as row_count 
FROM noetl.transient;

SELECT 
  column_name, 
  data_type, 
  is_nullable,
  column_default
FROM information_schema.columns 
WHERE table_schema = 'noetl' 
  AND table_name = 'transient'
ORDER BY ordinal_position;

SELECT
  conname as constraint_name,
  contype as constraint_type,
  pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid = 'noetl.transient'::regclass
ORDER BY conname;
