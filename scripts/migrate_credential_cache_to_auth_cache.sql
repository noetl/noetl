-- Migration: Rename credential_cache to auth_cache
-- Date: 2025-12-01
-- Purpose: Simplify table name to single-word convention

-- Step 1: Check if old table exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables 
               WHERE table_schema = 'noetl' 
               AND table_name = 'credential_cache') THEN
        
        -- Step 2: Rename table
        ALTER TABLE noetl.credential_cache RENAME TO auth_cache;
        RAISE NOTICE 'Table renamed: credential_cache -> auth_cache';
        
        -- Step 3: Rename indexes
        ALTER INDEX IF EXISTS noetl.credential_cache_pkey 
            RENAME TO auth_cache_pkey;
        ALTER INDEX IF EXISTS noetl.idx_credential_cache_credential 
            RENAME TO idx_auth_cache_credential;
        ALTER INDEX IF EXISTS noetl.idx_credential_cache_execution 
            RENAME TO idx_auth_cache_execution;
        ALTER INDEX IF EXISTS noetl.idx_credential_cache_expires 
            RENAME TO idx_auth_cache_expires;
        ALTER INDEX IF EXISTS noetl.idx_credential_cache_parent_execution 
            RENAME TO idx_auth_cache_parent_execution;
        ALTER INDEX IF EXISTS noetl.idx_credential_cache_type 
            RENAME TO idx_auth_cache_type;
        
        RAISE NOTICE 'Indexes renamed';
        
        -- Step 4: Rename constraints
        ALTER TABLE noetl.auth_cache 
            RENAME CONSTRAINT credential_cache_cache_type_check 
            TO auth_cache_cache_type_check;
        ALTER TABLE noetl.auth_cache 
            RENAME CONSTRAINT credential_cache_scope_type_check 
            TO auth_cache_scope_type_check;
        
        RAISE NOTICE 'Constraints renamed';
        RAISE NOTICE 'Migration completed successfully!';
        
    ELSIF EXISTS (SELECT 1 FROM information_schema.tables 
                  WHERE table_schema = 'noetl' 
                  AND table_name = 'auth_cache') THEN
        RAISE NOTICE 'Table auth_cache already exists, migration not needed';
    ELSE
        RAISE NOTICE 'Neither credential_cache nor auth_cache exists';
    END IF;
END $$;

-- Step 5: Verify new table structure
\d noetl.auth_cache
