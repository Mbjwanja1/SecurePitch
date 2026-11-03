-- Dossier lifecycle rules, enforced in the database for every caller (ADR 0002):
--
--   draft -> submitted -> approved -> sealed -> revoked
--
-- * Ledger rows, planned spends and receipts can change only while the dossier is a draft.
-- * Attestations can change until the dossier is approved.
-- * Approvals are never edited or removed.
-- * A sealed dossier can only be revoked, and a revoked one never changes again.
-- * Status changes happen only through transition_dossier() and seal_dossier(), which check
--   the actor's role, write the audit log, and run as one transaction.

-- Draft-only / until-approved guards ---------------------------------------------------------

create function public.dossier_status_of(p_dossier uuid) returns public.dossier_status
language sql stable security definer set search_path = '' as $$
  select status from public.dossiers where id = p_dossier
$$;

-- SECURITY DEFINER: reads the dossier's status even where the caller can't execute
-- dossier_status_of() or see the parent row.
create function public.guard_draft_only() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_dossier uuid;
begin
  if tg_table_name = 'receipts' then
    select i.dossier_id into v_dossier from public.dossier_items i
    where i.id = coalesce(new.item_id, old.item_id);
  else
    v_dossier := coalesce(new.dossier_id, old.dossier_id);
  end if;
  if public.dossier_status_of(v_dossier) is distinct from 'draft' then
    raise exception '% can only change while the dossier is a draft', tg_table_name
      using errcode = 'check_violation';
  end if;
  return coalesce(new, old);
end;
$$;

create trigger dossier_items_draft_only before insert or update or delete on public.dossier_items
  for each row execute function public.guard_draft_only();
create trigger planned_spends_draft_only before insert or update or delete on public.planned_spends
  for each row execute function public.guard_draft_only();
create trigger receipts_draft_only before insert or update or delete on public.receipts
  for each row execute function public.guard_draft_only();

-- SECURITY DEFINER: reads the dossier's status even where the caller can't execute
-- dossier_status_of() or see the parent row.
create function public.guard_attestation() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_status public.dossier_status;
begin
  select d.status into v_status
  from public.dossier_items i join public.dossiers d on d.id = i.dossier_id
  where i.id = coalesce(new.item_id, old.item_id);
  if v_status not in ('draft', 'submitted') then
    raise exception 'attestations are closed once the dossier is approved'
      using errcode = 'check_violation';
  end if;
  return coalesce(new, old);
end;
$$;

create trigger attestations_until_approved before insert or update or delete on public.attestations
  for each row execute function public.guard_attestation();

create function public.guard_approvals_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'approvals are signatures and can''t be changed or removed'
    using errcode = 'insufficient_privilege';
end;
$$;

create trigger approvals_immutable before update or delete on public.approvals
  for each row execute function public.guard_approvals_immutable();

-- Dossier row protection --------------------------------------------------------------------

create function public.guard_dossier_update() returns trigger
language plpgsql set search_path = '' as $$
begin
  if old.status = 'revoked' then
    raise exception 'a revoked dossier can''t change' using errcode = 'insufficient_privilege';
  end if;
  if old.status = 'sealed' and (
       new.status <> 'revoked'
       or (to_jsonb(new) - '{status,revoked_at,revoke_reason}'::text[])
          <> (to_jsonb(old) - '{status,revoked_at,revoke_reason}'::text[])) then
    raise exception 'a sealed dossier can only be revoked' using errcode = 'insufficient_privilege';
  end if;
  if new.status <> old.status
     and current_setting('securepitch.transition', true) is distinct from 'on' then
    raise exception 'change dossier status with transition_dossier() or seal_dossier()'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end;
$$;

create trigger dossiers_guard_update before update on public.dossiers
  for each row execute function public.guard_dossier_update();

create function public.guard_dossier_delete() returns trigger
language plpgsql set search_path = '' as $$
begin
  if old.status <> 'draft' then
    raise exception 'only draft dossiers can be deleted' using errcode = 'insufficient_privilege';
  end if;
  return old;
end;
$$;

create trigger dossiers_guard_delete before delete on public.dossiers
  for each row execute function public.guard_dossier_delete();

-- State machine -------------------------------------------------------------------------------

create function public.member_role_of(p_club uuid, p_user uuid) returns public.member_role
language sql stable security definer set search_path = '' as $$
  select role from public.club_members where club_id = p_club and user_id = p_user
$$;

-- Called by the backend after it has verified the actor's passkey signature (for submit and
-- approve). p_actor is the signed-in user the backend is acting for.
create function public.transition_dossier(
  p_dossier uuid,
  p_to public.dossier_status,
  p_actor uuid,
  p_reason text default null
) returns public.dossiers
language plpgsql security definer set search_path = '' as $$
declare
  d public.dossiers;
  v_role public.member_role;
begin
  select * into d from public.dossiers where id = p_dossier for update;
  if not found then
    raise exception 'dossier % not found', p_dossier using errcode = 'no_data_found';
  end if;
  v_role := public.member_role_of(d.club_id, p_actor);

  if d.status = 'draft' and p_to = 'submitted' then
    if v_role is distinct from 'manager' then
      raise exception 'only the club manager can submit' using errcode = 'insufficient_privilege';
    end if;
    if not exists (select 1 from public.approvals where dossier_id = d.id and role = 'manager') then
      raise exception 'the manager''s passkey signature is missing' using errcode = 'check_violation';
    end if;
    if not exists (select 1 from public.dossier_items where dossier_id = d.id) then
      raise exception 'a dossier needs at least one ledger row' using errcode = 'check_violation';
    end if;
  elsif d.status = 'submitted' and p_to = 'approved' then
    if v_role is distinct from 'treasurer' then
      raise exception 'only the club treasurer can approve' using errcode = 'insufficient_privilege';
    end if;
    if not exists (select 1 from public.approvals where dossier_id = d.id and role = 'treasurer') then
      raise exception 'the treasurer''s passkey signature is missing' using errcode = 'check_violation';
    end if;
    if exists (select 1 from public.attestations where club_id = d.club_id
               and item_id in (select id from public.dossier_items where dossier_id = d.id)
               and (response is null or response = 'disputed')) then
      raise exception 'some attestations are unanswered or disputed' using errcode = 'check_violation';
    end if;
  elsif d.status = 'sealed' and p_to = 'revoked' then
    if v_role is null or v_role not in ('manager', 'treasurer') then
      raise exception 'only the manager or treasurer can revoke' using errcode = 'insufficient_privilege';
    end if;
    if coalesce(length(trim(p_reason)), 0) = 0 then
      raise exception 'a reason is required to revoke' using errcode = 'check_violation';
    end if;
  else
    raise exception 'can''t move a dossier from % to %', d.status, p_to
      using errcode = 'check_violation';
  end if;

  perform set_config('securepitch.transition', 'on', true);
  update public.dossiers set
    status = p_to,
    submitted_at = case when p_to = 'submitted' then now() else submitted_at end,
    approved_at = case when p_to = 'approved' then now() else approved_at end,
    revoked_at = case when p_to = 'revoked' then now() else revoked_at end,
    revoke_reason = case when p_to = 'revoked' then trim(p_reason) else revoke_reason end
  where id = d.id
  returning * into d;
  perform set_config('securepitch.transition', 'off', true);

  perform public.write_audit('dossier.' || p_to::text, p_actor, d.club_id, d.id,
                             jsonb_build_object('reason', p_reason));
  return d;
end;
$$;

-- Called by the engine once it has built the Merkle tree, signed the payload and stored the PDF.
-- Sets the seal and the status in one transaction.
create function public.seal_dossier(
  p_dossier uuid,
  p_merkle_root text,
  p_payload jsonb,
  p_kid text,
  p_signature text,
  p_pdf_path text,
  p_pdf_sha256 text
) returns public.dossiers
language plpgsql security definer set search_path = '' as $$
declare
  d public.dossiers;
begin
  select * into d from public.dossiers where id = p_dossier for update;
  if not found then
    raise exception 'dossier % not found', p_dossier using errcode = 'no_data_found';
  end if;
  if d.status <> 'approved' then
    raise exception 'only an approved dossier can be sealed (this one is %)', d.status
      using errcode = 'check_violation';
  end if;
  if p_payload ->> 'merkle_root' is distinct from p_merkle_root then
    raise exception 'the payload''s merkle_root doesn''t match' using errcode = 'check_violation';
  end if;

  perform set_config('securepitch.transition', 'on', true);
  update public.dossiers set
    status = 'sealed', sealed_at = now(), merkle_root = p_merkle_root, payload = p_payload,
    kid = p_kid, signature = p_signature, pdf_path = p_pdf_path, pdf_sha256 = p_pdf_sha256
  where id = d.id
  returning * into d;
  perform set_config('securepitch.transition', 'off', true);

  perform public.write_audit('dossier.sealed', null, d.club_id, d.id,
                             jsonb_build_object('kid', p_kid, 'merkle_root', p_merkle_root));
  return d;
end;
$$;

-- Public verifier ------------------------------------------------------------------------------

-- The only thing the anonymous role can call. Returns a sealed or revoked dossier by ID (no
-- listing), with just the fields a sponsor needs to verify it.
create function public.public_dossier(p_id uuid) returns jsonb
language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'id', d.id, 'club', c.name, 'period_from', d.period_from, 'period_to', d.period_to,
    'status', d.status, 'payload', d.payload, 'kid', d.kid, 'signature', d.signature,
    'pdf_sha256', d.pdf_sha256, 'sealed_at', d.sealed_at, 'revoked_at', d.revoked_at,
    'revoke_reason', d.revoke_reason
  )
  from public.dossiers d join public.clubs c on c.id = d.club_id
  where d.id = p_id and d.status in ('sealed', 'revoked')
$$;

-- Permissions: lock everything down, then grant back the minimum.
revoke execute on all functions in schema public from public, anon, authenticated;
grant execute on function public.is_club_member(uuid) to authenticated;
grant execute on function public.has_club_role(uuid, public.member_role[]) to authenticated;
grant execute on function public.public_dossier(uuid) to anon, authenticated;
grant execute on function public.transition_dossier(uuid, public.dossier_status, uuid, text)
  to service_role;
grant execute on function public.seal_dossier(uuid, text, jsonb, text, text, text, text)
  to service_role;
grant execute on function public.verify_audit_chain() to service_role;
