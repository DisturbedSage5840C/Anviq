-- app_rw is created NOLOGIN by migration 0002; the demo gives it a password so the API runs
-- with table grants only, not as the database owner.
alter role app_rw login password :'pw';
