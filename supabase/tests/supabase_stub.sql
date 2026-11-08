-- TEST ONLY. Recreates the small part of Supabase our migrations depend on, so they can be
-- tested against a plain Postgres container. Never run this against the real project.

create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
grant anon, authenticated, service_role to postgres;

create schema auth;
create table auth.users (
  id uuid primary key,
  email text unique
);

-- Same logic as Supabase's own auth.uid() and auth.role(): read the request's JWT claims.
create function auth.uid() returns uuid language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$$;

create function auth.role() returns text language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )
$$;

grant usage on schema auth to anon, authenticated, service_role;
grant execute on all functions in schema auth to anon, authenticated, service_role;

-- The API roles can use the schema but get NO automatic table privileges. This matches our
-- project (checked on the live database, 2026-11-03): it was created without Supabase's
-- "grant new tables to the API roles" default. An earlier version of this stub granted
-- everything by default, which hid missing GRANTs that broke the real database, so every
-- privilege must now come from the migrations themselves.
grant usage on schema public to anon, authenticated, service_role;

-- Supabase Storage keeps its buckets here. Only the columns our migrations write.
create schema storage;
create table storage.buckets (
  id text primary key,
  name text not null unique,
  public boolean default false,
  file_size_limit bigint,
  allowed_mime_types text[]
);
grant usage on schema storage to service_role;
grant select on storage.buckets to service_role;
