-- Row-level security. Club members see their own club's data; only specific roles may change
-- it; the anonymous role gets no table access at all (the public verifier uses
-- public_dossier(), defined in the next migration). The service role (engine) bypasses RLS,
-- so engine code must scope every query by club (ADR 0002).

-- Helpers. SECURITY DEFINER so policies on club_members don't recurse into themselves.
create function public.is_club_member(p_club uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.club_members m where m.club_id = p_club and m.user_id = auth.uid()
  )
$$;

create function public.has_club_role(p_club uuid, p_roles public.member_role[]) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.club_members m
    where m.club_id = p_club and m.user_id = auth.uid() and m.role = any (p_roles)
  )
$$;

-- Postgres lets everyone execute new functions by default. Lock every function down, then
-- grant back only what each role needs.
revoke execute on all functions in schema public from public, anon, authenticated;
grant execute on function public.is_club_member(uuid) to authenticated;
grant execute on function public.has_club_role(uuid, public.member_role[]) to authenticated;

-- Enable RLS everywhere and remove the anonymous role's table access entirely.
alter table public.clubs enable row level security;
alter table public.club_members enable row level security;
alter table public.roster_entries enable row level security;
alter table public.fixtures enable row level security;
alter table public.dossiers enable row level security;
alter table public.dossier_items enable row level security;
alter table public.planned_spends enable row level security;
alter table public.receipts enable row level security;
alter table public.attestations enable row level security;
alter table public.approvals enable row level security;
alter table public.webauthn_credentials enable row level security;
alter table public.audit_log enable row level security;

revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;

-- Signed-in users only read, except where a policy below grants writes. Writes by the engine
-- go through the service role; state changes go through functions (next migration).
revoke insert, update, delete, truncate on all tables in schema public from authenticated;

-- clubs, club_members: read your own club. Membership is managed by admins (service role).
create policy clubs_read on public.clubs for select to authenticated
  using (public.is_club_member(id));
create policy club_members_read on public.club_members for select to authenticated
  using (public.is_club_member(club_id));

-- Roster: personal data of players, so managers and treasurers only (not captains).
grant insert, update, delete on public.roster_entries to authenticated;
create policy roster_officials on public.roster_entries for all to authenticated
  using (public.has_club_role(club_id, '{manager,treasurer}'))
  with check (public.has_club_role(club_id, '{manager,treasurer}'));

-- Fixtures: everyone in the club reads; officials edit.
grant insert, update, delete on public.fixtures to authenticated;
create policy fixtures_read on public.fixtures for select to authenticated
  using (public.is_club_member(club_id));
create policy fixtures_insert on public.fixtures for insert to authenticated
  with check (public.has_club_role(club_id, '{manager,treasurer}'));
create policy fixtures_update on public.fixtures for update to authenticated
  using (public.has_club_role(club_id, '{manager,treasurer}'))
  with check (public.has_club_role(club_id, '{manager,treasurer}'));
create policy fixtures_delete on public.fixtures for delete to authenticated
  using (public.has_club_role(club_id, '{manager,treasurer}'));

-- Dossiers: read-only for members; created by the engine, moved through states by functions.
create policy dossiers_read on public.dossiers for select to authenticated
  using (public.is_club_member(club_id));

-- Ledger rows: members read. The manager may re-tag a row (category, branch, fixture) or drop
-- it while the dossier is a draft (enforced by trigger). Amounts, dates and receipt numbers
-- come from the statement and can't be edited from the browser.
grant update (category, branch, fixture_code), delete on public.dossier_items to authenticated;
create policy items_read on public.dossier_items for select to authenticated
  using (public.is_club_member(club_id));
create policy items_manager_update on public.dossier_items for update to authenticated
  using (public.has_club_role(club_id, '{manager}'))
  with check (public.has_club_role(club_id, '{manager}'));
create policy items_manager_delete on public.dossier_items for delete to authenticated
  using (public.has_club_role(club_id, '{manager}'));

-- Planned spends (dossier page 1): the manager maintains them while the dossier is a draft.
grant insert, update, delete on public.planned_spends to authenticated;
create policy planned_read on public.planned_spends for select to authenticated
  using (public.is_club_member(club_id));
create policy planned_manager_write on public.planned_spends for all to authenticated
  using (public.has_club_role(club_id, '{manager}'))
  with check (public.has_club_role(club_id, '{manager}'));

-- Receipts and approvals: members read; written by the engine after it verifies the image or
-- passkey signature.
create policy receipts_read on public.receipts for select to authenticated
  using (public.is_club_member(club_id));
create policy approvals_read on public.approvals for select to authenticated
  using (public.is_club_member(club_id));

-- Attestations: members see status, never the token hash.
revoke select on public.attestations from authenticated;
grant select (id, item_id, club_id, kind, method, expires_at, used_at, response, recorded_by,
              created_at) on public.attestations to authenticated;
create policy attestations_read on public.attestations for select to authenticated
  using (public.is_club_member(club_id));

-- Passkeys: you see your own.
create policy webauthn_own on public.webauthn_credentials for select to authenticated
  using (user_id = auth.uid());

-- Audit log: members read their club's entries. Nobody writes directly.
create policy audit_read on public.audit_log for select to authenticated
  using (club_id is not null and public.is_club_member(club_id));
