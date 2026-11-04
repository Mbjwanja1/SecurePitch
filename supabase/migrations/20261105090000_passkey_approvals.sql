-- Passkey approvals (docs/adr/0003-passkey-approvals.md, docs/CRYPTO_SPEC.md section 6).
--
-- The engine builds the approval payload from approval_snapshot(), uses its SHA-256 as the
-- WebAuthn challenge, verifies the approver's passkey assertion, then calls approve_dossier().
-- approve_dossier() re-checks under a lock that nothing changed in between, records the
-- signature and moves the dossier on, in one transaction.

-- 1. Everything the approval payload is built from, in a fixed order. Leaf hashes are left out:
-- they're derived from this content and written when the manager signs.
create function public.approval_content(p_dossier uuid) returns jsonb
language sql stable security definer set search_path = '' set timezone = 'UTC' as $$
  select jsonb_build_object(
    'dossier', jsonb_build_object(
      'id', d.id, 'club_id', d.club_id, 'club_name', c.name,
      'period_from', d.period_from, 'period_to', d.period_to,
      'source_sha256', d.source_sha256, 'rows_total', d.rows_total, 'integrity', d.integrity),
    'items', coalesce((
      select jsonb_agg(jsonb_build_object(
        'tx', i.tx, 'ts', i.ts, 'amt_cents', i.amt_cents, 'fee_cents', i.fee_cents,
        'dir', i.dir, 'branch', i.branch, 'category', i.category, 'cp_type', i.cp_type,
        'cp_ref', i.cp_ref, 'fixture_code', i.fixture_code, 'salt', i.salt,
        'receipt_sha256', r.image_sha256) order by i.tx)
      from public.dossier_items i left join public.receipts r on r.item_id = i.id
      where i.dossier_id = d.id), '[]'::jsonb),
    'planned_spends', coalesce((
      select jsonb_agg(jsonb_build_object(
        'supplier', p.supplier, 'till', p.till, 'amt_cents', p.amt_cents, 'purpose', p.purpose)
        order by p.till, p.amt_cents, p.supplier, p.purpose)
      from public.planned_spends p where p.dossier_id = d.id), '[]'::jsonb))
  from public.dossiers d join public.clubs c on c.id = d.club_id
  where d.id = p_dossier
$$;

create function public.approval_fingerprint(p_content jsonb) returns text
language sql immutable set search_path = '' as $$
  select encode(sha256(convert_to(p_content::text, 'UTF8')), 'hex')
$$;

-- 2. What the engine reads before building the challenge.
create function public.approval_snapshot(p_dossier uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare
  v_content jsonb := public.approval_content(p_dossier);
begin
  if v_content is null then
    raise exception 'dossier not found' using errcode = 'no_data_found';
  end if;
  return v_content || jsonb_build_object(
    'status', (select status from public.dossiers where id = p_dossier),
    'fingerprint', public.approval_fingerprint(v_content),
    'manager_challenge',
      (select challenge from public.approvals where dossier_id = p_dossier and role = 'manager'),
    'approvals', coalesce((
      select jsonb_agg(jsonb_build_object('role', a.role, 'user_id', a.user_id,
                                          'created_at', a.created_at) order by a.created_at)
      from public.approvals a where a.dossier_id = p_dossier), '[]'::jsonb));
end;
$$;

-- 3. Record a verified passkey signature and move the dossier on: draft -> submitted (manager)
-- or submitted -> approved (treasurer). Called only by the engine after it has verified the
-- assertion against the challenge it built from approval_snapshot().
create function public.approve_dossier(
  p_dossier uuid,
  p_actor uuid,
  p_fingerprint text,
  p_challenge text,
  p_leaf_hashes jsonb,       -- {tx: leaf hash hex}; required when the manager signs
  p_cred_id text,
  p_authenticator_data text,
  p_client_data_json text,
  p_signature text,
  p_sign_count bigint
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  d public.dossiers;
  v_role public.member_role;
  v_stored_count bigint;
  v_items integer;
  v_hashed integer;
begin
  select * into d from public.dossiers where id = p_dossier for update;
  if not found then
    raise exception 'dossier not found' using errcode = 'no_data_found';
  end if;
  v_role := public.member_role_of(d.club_id, p_actor);
  if d.status = 'draft' and v_role is distinct from 'manager' then
    raise exception 'only the club manager can submit' using errcode = 'insufficient_privilege';
  elsif d.status = 'submitted' and v_role is distinct from 'treasurer' then
    raise exception 'only the club treasurer can approve' using errcode = 'insufficient_privilege';
  elsif d.status not in ('draft', 'submitted') then
    raise exception 'this dossier isn''t waiting for a signature (it''s %)', d.status
      using errcode = 'check_violation';
  end if;

  -- The passkey must be the signer's own, and its counter must never go backwards (a cloned
  -- authenticator). Authenticators that don't count report 0 every time.
  select sign_count into v_stored_count from public.webauthn_credentials
  where id = p_cred_id and user_id = p_actor for update;
  if not found then
    raise exception 'that passkey isn''t registered to you' using errcode = 'insufficient_privilege';
  end if;
  if (p_sign_count > 0 or v_stored_count > 0) and p_sign_count <= v_stored_count then
    raise exception 'this passkey''s signature counter went backwards' using errcode = 'check_violation';
  end if;

  -- Nothing may have changed since the challenge was built.
  if public.approval_fingerprint(public.approval_content(d.id)) is distinct from p_fingerprint then
    raise exception 'the dossier changed while you were signing; review it and sign again'
      using errcode = 'serialization_failure';
  end if;
  if p_challenge !~ '^[0-9a-f]{64}$' then
    raise exception 'malformed challenge' using errcode = 'check_violation';
  end if;

  if d.status = 'draft' then
    -- Freeze the leaf hashes with the manager's signature: one for every row, none extra.
    update public.dossier_items i set leaf_hash = p_leaf_hashes ->> i.tx where i.dossier_id = d.id;
    select count(*), count(leaf_hash) into v_items, v_hashed
    from public.dossier_items where dossier_id = d.id;
    if v_items = 0 or v_hashed <> v_items
       or (select count(*) from jsonb_object_keys(coalesce(p_leaf_hashes, '{}'::jsonb))) <> v_items then
      raise exception 'leaf hashes don''t match the ledger rows' using errcode = 'check_violation';
    end if;
  elsif p_challenge is distinct from
        (select challenge from public.approvals where dossier_id = d.id and role = 'manager') then
    -- Rows freeze at submission, so this only fails if something bypassed that.
    raise exception 'the treasurer must sign exactly what the manager signed'
      using errcode = 'check_violation';
  end if;

  update public.webauthn_credentials set sign_count = p_sign_count where id = p_cred_id;
  insert into public.approvals (dossier_id, club_id, user_id, role, challenge, cred_id,
                                authenticator_data, client_data_json, signature)
  values (d.id, d.club_id, p_actor, v_role, p_challenge, p_cred_id,
          p_authenticator_data, p_client_data_json, p_signature);
  d := public.transition_dossier(
    d.id, case when d.status = 'draft' then 'submitted' else 'approved' end::public.dossier_status,
    p_actor);
  return jsonb_build_object('dossier_id', d.id, 'status', d.status, 'role', v_role);
end;
$$;

-- 4. Register a passkey the engine has verified.
create function public.add_passkey(
  p_actor uuid, p_cred_id text, p_public_key text, p_sign_count bigint, p_transports text[]
) returns void
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.webauthn_credentials (id, user_id, public_key, sign_count, transports)
  values (p_cred_id, p_actor, p_public_key, p_sign_count, p_transports);
  perform public.write_audit('passkey.added', p_actor, null, null,
                             jsonb_build_object('cred_id', p_cred_id));
exception when unique_violation then
  raise exception 'this passkey is already registered' using errcode = 'unique_violation';
end;
$$;

revoke execute on function public.approval_content(uuid), public.approval_fingerprint(jsonb),
  public.approval_snapshot(uuid),
  public.approve_dossier(uuid, uuid, text, text, jsonb, text, text, text, text, bigint),
  public.add_passkey(uuid, text, text, bigint, text[])
  from public, anon, authenticated;
grant execute on function public.approval_snapshot(uuid),
  public.approve_dossier(uuid, uuid, text, text, jsonb, text, text, text, text, bigint),
  public.add_passkey(uuid, text, text, bigint, text[])
  to service_role;
