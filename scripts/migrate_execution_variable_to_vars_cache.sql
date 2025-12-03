-- Migration: execution_variable -> vars_cache
-- Date: 2025-12-01
-- Description: Rename execution_variable table to vars_cache and add cache tracking columns

BEGIN;

-- 1. Rename table
ALTER TABLE noetl.execution_variable RENAME TO vars_cache;

-- 2. Rename primary key constraint
ALTER INDEX noetl.execution_variable_pkey RENAME TO vars_cache_pkey;

-- 3. Rename indexes
ALTER INDEX noetl.idx_execution_variable_source RENAME TO idx_vars_cache_source;
ALTER INDEX noetl.idx_execution_variable_type RENAME TO idx_vars_cache_type;

-- 4. Rename check constraint
ALTER TABLE noetl.vars_cache 
  RENAME CONSTRAINT execution_variable_variable_type_check TO vars_cache_type_check;

-- 5. Add access_count column
ALTER TABLE noetl.vars_cache 
  ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0;

-- 6. Rename updated_at to accessed_at
ALTER TABLE noetl.vars_cache 
  RENAME COLUMN updated_at TO accessed_at;

-- 7. Update type constraint to include iterator_state
ALTER TABLE noetl.vars_cache DROP CONSTRAINT IF EXISTS vars_cache_type_check;
ALTER TABLE noetl.vars_cache 
  ADD CONSTRAINT vars_cache_type_check 
  CHECK (variable_type IN ('user_defined', 'step_result', 'computed', 'iterator_state'));

-- 8. Rename columns to match new naming (var_* instead of variable_*)
ALTER TABLE noetl.vars_cache RENAME COLUMN variable_name TO var_name;
ALTER TABLE noetl.vars_cache RENAME COLUMN variable_type TO var_type;
ALTER TABLE noetl.vars_cache RENAME COLUMN variable_value TO var_value;

-- 9. Update constraint with new column name
ALTER TABLE noetl.vars_cache DROP CONSTRAINT IF EXISTS vars_cache_type_check;
ALTER TABLE noetl.vars_cache 
  ADD CONSTRAINT vars_cache_type_check 
  CHECK (var_type IN ('user_defined', 'step_result', 'computed', 'iterator_state'));

-- 10. Create new index on execution_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_vars_cache_execution ON noetl.vars_cache(execution_id);

COMMIT;

-- Verification queries
SELECT 
  'Table renamed successfully' as status,
  count(*) as row_count 
FROM noetl.vars_cache;

SELECT 
  column_name, 
  data_type, 
  is_nullable,
  column_default
FROM information_schema.columns 
WHERE table_schema = 'noetl' 
  AND table_name = 'vars_cache'
ORDER BY ordinal_position;

SELECT
  conname as constraint_name,
  contype as constraint_type,
  pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid = 'noetl.vars_cache'::regclass
ORDER BY conname;
