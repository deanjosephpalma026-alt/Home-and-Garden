-- Non-breaking migration for shared auth support on riders.
-- Existing rider login by contact remains valid; email is added for Supabase parity.

ALTER TABLE riders
ADD COLUMN IF NOT EXISTS email VARCHAR(100) DEFAULT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS riders_email_unique_idx
ON riders (email)
WHERE email IS NOT NULL;

UPDATE riders
SET email = NULL
WHERE email = '';