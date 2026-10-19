-- Proof that "delete my data" left nothing behind for one teacher (build plan 14.2).
--
-- Run it after a deletion, against the database the deletion ran on:
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -c "select set_config('anviq.teacher_id', '<teacher uuid>', false)" \
--     -f scripts/verify_deletion.sql
--
-- It finds every table with a teacher_id column by asking the catalogue, so a table added later
-- is covered without editing this file. Any surviving row aborts with the table named; a clean
-- run prints nothing. The teacher uuid is the one noted before the deletion: after it, the
-- teachers row is gone and nothing else maps a person to an id.

do $$
declare
    wanted_id uuid;
    keyed_table text;
    surviving bigint;
begin
    if coalesce(current_setting('anviq.teacher_id', true), '') = '' then
        raise exception 'set anviq.teacher_id to the teacher uuid before running this script';
    end if;
    wanted_id := current_setting('anviq.teacher_id')::uuid;

    select count(*) into surviving from teachers where id = wanted_id;
    if surviving > 0 then
        raise exception 'table teachers still holds % row(s) for %', surviving, wanted_id;
    end if;

    for keyed_table in
        select table_name
        from information_schema.columns
        where table_schema = current_schema() and column_name = 'teacher_id'
        order by table_name
    loop
        execute format('select count(*) from %I where teacher_id = $1', keyed_table)
            into surviving using wanted_id;
        if surviving > 0 then
            raise exception 'table % still holds % row(s) for %', keyed_table, surviving, wanted_id;
        end if;
    end loop;
end
$$;
