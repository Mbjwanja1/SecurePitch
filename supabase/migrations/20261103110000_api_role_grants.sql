-- Explicit table privileges for the API roles.
--
-- Our Supabase project grants NO table privileges to anon, authenticated or service_role by
-- default (found when the first migrations were applied on 2026-11-03: the engine's secret key
-- got "permission denied for table clubs", and signed-in users couldn't read anything).
-- Row-level security still decides WHICH rows each role sees; these grants decide whether the
-- role may touch the table at all. Every future migration that adds a table must grant
-- explicitly in the same way (see supabase/README.md).

-- Engine (service role): full table access. It bypasses row-level security, so the rules in
-- ADR 0002 (explicit p_actor / p_club, checked inside functions) apply to everything it does.
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

-- Signed-in users: read through row-level security. Their writes were granted table by table
-- (and column by column for ledger rows) in 20261103090200_rls.sql.
grant select on
  public.clubs, public.club_members, public.roster_entries, public.fixtures, public.dossiers,
  public.dossier_items, public.planned_spends, public.receipts, public.approvals,
  public.webauthn_credentials, public.audit_log
to authenticated;
-- public.attestations: column-level SELECT (without token_hash) was granted in the RLS migration.

-- Anonymous visitors: still no table access. They can only call public.public_dossier().
