-- Append-only, hash-chained audit log.
--
-- Triggers refuse UPDATE, DELETE and TRUNCATE for everyone, including the service role (which
-- bypasses row-level security but not triggers). Each row's hash covers the previous row's
-- hash, so editing or removing an entry breaks the chain, which verify_audit_chain() detects.

create table public.audit_log (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  actor uuid,
  action text not null,
  club_id uuid,
  dossier_id uuid,
  details jsonb not null default '{}'::jsonb,
  prev_hash text,
  hash text not null
);
create index audit_log_club_idx on public.audit_log (club_id, id);

create function public.audit_log_chain() returns trigger
language plpgsql
set search_path = ''
as $$
begin
  -- Serialise inserts so two concurrent writers can't both chain onto the same row.
  perform pg_advisory_xact_lock(hashtext('public.audit_log'));
  select l.hash into new.prev_hash from public.audit_log l order by l.id desc limit 1;
  new.at := now();
  new.hash := encode(sha256(convert_to(
    coalesce(new.prev_hash, '') || '|' || jsonb_build_object(
      'at', new.at, 'actor', new.actor, 'action', new.action,
      'club_id', new.club_id, 'dossier_id', new.dossier_id, 'details', new.details
    )::text, 'UTF8')), 'hex');
  return new;
end;
$$;

create trigger audit_log_chain before insert on public.audit_log
  for each row execute function public.audit_log_chain();

create function public.audit_log_append_only() returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'audit_log is append-only' using errcode = 'insufficient_privilege';
end;
$$;

create trigger audit_log_no_update_delete before update or delete on public.audit_log
  for each row execute function public.audit_log_append_only();
create trigger audit_log_no_truncate before truncate on public.audit_log
  for each statement execute function public.audit_log_append_only();

-- Recomputes every hash; returns the id of the first broken row, or null if the chain holds.
create function public.verify_audit_chain() returns bigint
language plpgsql
stable
set search_path = ''
as $$
declare
  r record;
  expected_prev text := null;
begin
  for r in select * from public.audit_log order by id loop
    if r.prev_hash is distinct from expected_prev
       or r.hash <> encode(sha256(convert_to(
            coalesce(r.prev_hash, '') || '|' || jsonb_build_object(
              'at', r.at, 'actor', r.actor, 'action', r.action,
              'club_id', r.club_id, 'dossier_id', r.dossier_id, 'details', r.details
            )::text, 'UTF8')), 'hex') then
      return r.id;
    end if;
    expected_prev := r.hash;
  end loop;
  return null;
end;
$$;

-- Internal helper used by the other database functions.
create function public.write_audit(
  p_action text, p_actor uuid, p_club uuid, p_dossier uuid, p_details jsonb default '{}'::jsonb
) returns void
language sql
security definer
set search_path = ''
as $$
  insert into public.audit_log (action, actor, club_id, dossier_id, details)
  values (p_action, p_actor, p_club, p_dossier, coalesce(p_details, '{}'::jsonb));
$$;
