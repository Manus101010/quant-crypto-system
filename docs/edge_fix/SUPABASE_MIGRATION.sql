-- Edge fix (28 Oct 2026): take profit while trailing for Distribution Short (2R).
-- Run once in the Supabase SQL editor. Until it runs, triggers/supastore.py drops
-- the column from writes (logs a warning) and the TP still lives in condition_json,
-- so the live monitor keeps working before and after.
alter table public.triggers add column if not exists tp double precision;
