\set ON_ERROR_STOP on

-- Training-only PostgreSQL storage used by the disk-full exercise.
-- The business application and members table remain unchanged.
SELECT 'CREATE TABLESPACE training_disk_ts LOCATION ''/training-disk/pgspace'''
WHERE NOT EXISTS (
    SELECT 1 FROM pg_tablespace WHERE spcname = 'training_disk_ts'
)
\gexec

CREATE TABLE IF NOT EXISTS training_write_audit (
    observed_at   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    member_email  TEXT NOT NULL
) TABLESPACE training_disk_ts;

REVOKE ALL ON TABLE training_write_audit FROM PUBLIC;

CREATE OR REPLACE FUNCTION training_capture_member_insert()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO public.training_write_audit(member_email)
    VALUES (NEW.email);
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS training_member_insert_audit ON members;

CREATE TRIGGER training_member_insert_audit
AFTER INSERT ON members
FOR EACH ROW
EXECUTE FUNCTION training_capture_member_insert();
