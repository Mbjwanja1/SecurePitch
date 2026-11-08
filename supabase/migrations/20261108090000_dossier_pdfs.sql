-- The sealed dossier PDF (docs/CRYPTO_SPEC.md section 5). After sealing, the engine renders the
-- PDF from the sealed payload, uploads it to a private bucket and records its path and SHA-256
-- with attach_dossier_pdf(). The PDF isn't signed (it carries the seal's QR code, so its hash
-- can't be signed into it); the verifier page compares a PDF a sponsor was given with the hash.

-- 1. A private bucket. No storage policies: browsers can't list or read it, only the engine's
-- service role, which checks club membership before handing a PDF to anyone.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('dossier-pdfs', 'dossier-pdfs', false, 10485760, array['application/pdf'])
on conflict (id) do nothing;

-- 2. A sealed dossier may gain its PDF once, and nothing else about it may change. Same rules as
-- before otherwise (20261103090300_dossier_rules.sql).
create or replace function public.guard_dossier_update() returns trigger
language plpgsql set search_path = '' as $$
begin
  if old.status = 'revoked' then
    raise exception 'a revoked dossier can''t change' using errcode = 'insufficient_privilege';
  end if;
  if old.status = 'sealed' and new.status = 'sealed'
     and current_setting('securepitch.attach_pdf', true) = 'on'
     and old.pdf_path is null and old.pdf_sha256 is null
     and new.pdf_path is not null and new.pdf_sha256 is not null
     and (to_jsonb(new) - '{pdf_path,pdf_sha256}'::text[])
         = (to_jsonb(old) - '{pdf_path,pdf_sha256}'::text[]) then
    return new;
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

-- 3. Record a sealed dossier's PDF: once, at the path the engine always uses
-- (<club>/<dossier>/<sha256>.pdf, so a retry can never overwrite the file a hash refers to).
create function public.attach_dossier_pdf(
  p_dossier uuid,
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
  if d.status <> 'sealed' then
    raise exception 'only a sealed dossier gets a PDF (this one is %)', d.status
      using errcode = 'check_violation';
  end if;
  if d.pdf_sha256 is not null then
    raise exception 'this dossier already has its PDF' using errcode = 'unique_violation';
  end if;
  if coalesce(p_pdf_sha256, '') !~ '^[0-9a-f]{64}$' then
    raise exception 'the PDF hash must be a SHA-256 in lowercase hex' using errcode = 'check_violation';
  end if;
  if p_pdf_path is distinct from format('%s/%s/%s.pdf', d.club_id, d.id, p_pdf_sha256) then
    raise exception 'the PDF must be stored at <club>/<dossier>/<sha256>.pdf'
      using errcode = 'check_violation';
  end if;

  perform set_config('securepitch.attach_pdf', 'on', true);
  update public.dossiers set pdf_path = p_pdf_path, pdf_sha256 = p_pdf_sha256
  where id = d.id
  returning * into d;
  perform set_config('securepitch.attach_pdf', 'off', true);

  perform public.write_audit('dossier.pdf_attached', null, d.club_id, d.id,
                             jsonb_build_object('pdf_sha256', p_pdf_sha256));
  return d;
end;
$$;

revoke execute on function public.attach_dossier_pdf(uuid, text, text)
  from public, anon, authenticated;
grant execute on function public.attach_dossier_pdf(uuid, text, text) to service_role;
