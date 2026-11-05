-- Sealing (docs/CRYPTO_SPEC.md section 5). The engine builds the sealed payload (the approval
-- payload plus kid, approvals and sealed_at), signs it with the platform key and calls
-- seal_dossier(). The database now checks the seal against what it already holds, so a bug in
-- the engine can't seal a root or signatures other than the frozen ones.

-- 1. The Merkle root of a list of leaf hashes (hex), exactly as CRYPTO_SPEC section 3: pairs
-- hashed left to right with a 0x01 prefix, an unpaired last node promoted unchanged.
create function public.merkle_root_hex(p_leaves text[]) returns text
language plpgsql immutable set search_path = '' as $$
declare
  v_level bytea[];
  v_next bytea[];
  v_n integer;
  i integer;
begin
  if coalesce(cardinality(p_leaves), 0) = 0 then
    return null;
  end if;
  select array_agg(decode(h, 'hex') order by n) into v_level
  from unnest(p_leaves) with ordinality as t(h, n);
  while cardinality(v_level) > 1 loop
    v_next := '{}';
    v_n := cardinality(v_level);
    i := 1;
    while i <= v_n loop
      if i < v_n then
        v_next := array_append(v_next, sha256('\x01'::bytea || v_level[i] || v_level[i + 1]));
      else
        v_next := array_append(v_next, v_level[i]);
      end if;
      i := i + 2;
    end loop;
    v_level := v_next;
  end loop;
  return encode(v_level[1], 'hex');
end;
$$;

-- 2. What the engine needs to seal: the stored passkey signatures and each credential's
-- public key (COSE, base64url).
create function public.seal_snapshot(p_dossier uuid) returns jsonb
language sql stable security definer set search_path = '' set timezone = 'UTC' as $$
  select public.approval_snapshot(p_dossier) || jsonb_build_object(
    'signatures', coalesce((
      select jsonb_agg(jsonb_build_object(
        'role', a.role, 'cred_id', a.cred_id, 'challenge', a.challenge,
        'authenticator_data', a.authenticator_data, 'client_data_json', a.client_data_json,
        'signature', a.signature, 'created_at', a.created_at, 'public_key', c.public_key)
        order by a.role)
      from public.approvals a left join public.webauthn_credentials c on c.id = a.cred_id
      where a.dossier_id = p_dossier), '[]'::jsonb))
$$;

-- 3. seal_dossier(), now checking the seal against the database. Same signature as before.
create or replace function public.seal_dossier(
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
  v_root text;
  v_sealed_at timestamptz;
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
  if p_payload ->> 'dossier_id' is distinct from d.id::text or p_payload ->> 'kid' is distinct from p_kid then
    raise exception 'the payload names another dossier or key' using errcode = 'check_violation';
  end if;
  if coalesce(length(p_signature), 0) = 0 then
    raise exception 'the seal has no signature' using errcode = 'check_violation';
  end if;

  -- The root must be the one over the leaf hashes frozen when the manager signed, in the
  -- spec's (ts, tx) order.
  if exists (select 1 from public.dossier_items where dossier_id = d.id and leaf_hash is null) then
    raise exception 'some ledger rows have no frozen leaf hash' using errcode = 'check_violation';
  end if;
  select public.merkle_root_hex(array_agg(leaf_hash order by ts, tx)) into v_root
  from public.dossier_items where dossier_id = d.id;
  if v_root is distinct from p_merkle_root then
    raise exception 'the merkle root doesn''t match the frozen ledger' using errcode = 'check_violation';
  end if;

  -- The payload's passkey signatures must be exactly the stored ones, no more and no fewer.
  if (select coalesce(jsonb_agg(jsonb_build_array(a.role, a.cred_id, a.authenticator_data,
                                                  a.client_data_json, a.signature) order by a.role),
                      '[]'::jsonb)
      from public.approvals a where a.dossier_id = d.id)
     is distinct from
     (select coalesce(jsonb_agg(jsonb_build_array(e ->> 'role', e ->> 'cred_id',
                                                  e ->> 'authenticatorData', e ->> 'clientDataJSON',
                                                  e ->> 'signature') order by e ->> 'role'),
                      '[]'::jsonb)
      from jsonb_array_elements(case when jsonb_typeof(p_payload -> 'approvals') = 'array'
                                     then p_payload -> 'approvals' else '[]'::jsonb end) e) then
    raise exception 'the payload''s approvals aren''t the stored passkey signatures'
      using errcode = 'check_violation';
  end if;

  begin
    v_sealed_at := (p_payload ->> 'sealed_at')::timestamptz;
  exception when others then
    v_sealed_at := null;
  end;
  if v_sealed_at is null then
    raise exception 'the payload has no valid sealed_at' using errcode = 'check_violation';
  end if;

  perform set_config('securepitch.transition', 'on', true);
  update public.dossiers set
    status = 'sealed', sealed_at = v_sealed_at, merkle_root = p_merkle_root, payload = p_payload,
    kid = p_kid, signature = p_signature, pdf_path = p_pdf_path, pdf_sha256 = p_pdf_sha256
  where id = d.id
  returning * into d;
  perform set_config('securepitch.transition', 'off', true);

  perform public.write_audit('dossier.sealed', null, d.club_id, d.id,
                             jsonb_build_object('kid', p_kid, 'merkle_root', p_merkle_root));
  return d;
end;
$$;

revoke execute on function public.merkle_root_hex(text[]), public.seal_snapshot(uuid)
  from public, anon, authenticated;
grant execute on function public.seal_snapshot(uuid) to service_role;
