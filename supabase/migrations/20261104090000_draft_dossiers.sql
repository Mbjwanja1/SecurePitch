-- Creating draft dossiers from a parsed statement (engine: POST /v1/clubs/{club}/dossiers).

-- 1. Fees: a KES 250 transfer with a KES 7 charge keeps its fee on the same ledger row.
alter table public.dossier_items
  add column fee_cents bigint not null default 0 check (fee_cents >= 0);

-- 2. Fix: a draft dossier with rows couldn't be deleted. During the cascade the parent row is
-- already gone, so the guards saw "no parent" and refused. A parent can only be deleted while it
-- is a draft (guard_dossier_delete), so a missing parent on DELETE means that permitted cascade.
create or replace function public.guard_draft_only() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_status public.dossier_status;
begin
  v_status := public.dossier_status_of(public.parent_dossier(
    tg_table_name, to_jsonb(case when tg_op = 'INSERT' then new else old end)));
  if tg_op = 'DELETE' and v_status is null then
    return old;  -- cascade from deleting a draft dossier
  end if;
  if v_status is distinct from 'draft' then
    raise exception '% can only change while the dossier is a draft', tg_table_name
      using errcode = 'check_violation';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create or replace function public.guard_attestation() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_status public.dossier_status;
begin
  v_status := public.dossier_status_of(public.parent_dossier(
    tg_table_name, to_jsonb(case when tg_op = 'INSERT' then new else old end)));
  if tg_op = 'DELETE' and v_status is null then
    return old;  -- cascade from deleting a draft dossier
  end if;
  if v_status is null or v_status not in ('draft', 'submitted') then
    raise exception 'attestations are closed once the dossier is approved'
      using errcode = 'check_violation';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

-- 3. Create a draft dossier and all its ledger rows in one transaction (ADR 0002 rule 2).
-- Called only by the engine, which has re-parsed the statement and built p_items from it;
-- p_actor is the signed-in user from the web app's session (rules 5 and 7).
create function public.create_draft_dossier(
  p_club uuid,
  p_actor uuid,
  p_period_from date,
  p_period_to date,
  p_source_sha256 text,
  p_rows_total integer,
  p_integrity jsonb,
  p_items jsonb
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_id uuid;
  v_existing record;
  v_replaced boolean := false;
begin
  if public.member_role_of(p_club, p_actor) is distinct from 'manager' then
    raise exception 'only the club manager can create a dossier' using errcode = 'insufficient_privilege';
  end if;
  if jsonb_typeof(p_items) is distinct from 'array' or jsonb_array_length(p_items) = 0 then
    raise exception 'a dossier needs at least one ledger row' using errcode = 'check_violation';
  end if;

  -- One statement, one live dossier: replace an earlier draft, refuse anything further along.
  for v_existing in
    select id, status from public.dossiers
    where club_id = p_club and source_sha256 = p_source_sha256 and status <> 'revoked'
  loop
    if v_existing.status = 'draft' then
      delete from public.dossiers where id = v_existing.id;
      v_replaced := true;
    else
      raise exception 'this statement is already in a % dossier', v_existing.status
        using errcode = 'unique_violation';
    end if;
  end loop;

  insert into public.dossiers
    (club_id, period_from, period_to, source_sha256, rows_total, integrity, created_by)
  values
    (p_club, p_period_from, p_period_to, p_source_sha256, p_rows_total, p_integrity, p_actor)
  returning id into v_id;

  insert into public.dossier_items
    (dossier_id, club_id, tx, ts, amt_cents, fee_cents, dir, branch, category, cp_type, cp_ref,
     fixture_code, salt)
  select v_id, p_club, i.tx, i.ts, i.amt_cents, coalesce(i.fee_cents, 0), i.dir, i.branch,
         i.category, i.cp_type, i.cp_ref, i.fixture_code, i.salt
  from jsonb_to_recordset(p_items) as i(
    tx text, ts timestamptz, amt_cents bigint, fee_cents bigint, dir public.money_direction,
    branch public.leaf_branch, category public.item_category, cp_type public.counterparty_type,
    cp_ref text, fixture_code text, salt text);

  perform public.write_audit('dossier.created', p_actor, p_club, v_id,
    jsonb_build_object('items', jsonb_array_length(p_items), 'replaced_draft', v_replaced));
  return jsonb_build_object('dossier_id', v_id, 'replaced_draft', v_replaced);
end;
$$;

revoke execute on function public.create_draft_dossier(uuid, uuid, date, date, text, integer, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.create_draft_dossier(uuid, uuid, date, date, text, integer, jsonb, jsonb)
  to service_role;
