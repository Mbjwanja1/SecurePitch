-- Row-level security and dossier-lifecycle tests. Run by supabase/tests/run.sh against a
-- throwaway Postgres with supabase_stub.sql and all migrations applied. Any failed check
-- raises an exception and stops the run (ON_ERROR_STOP).
\set ON_ERROR_STOP 1
\set QUIET 1

-- Test helpers ---------------------------------------------------------------------------------
create schema tests;
grant usage on schema tests to anon, authenticated, service_role;

create function tests.act_as(p_user uuid, p_role text) returns void language sql as $$
  select set_config('request.jwt.claims',
                    json_build_object('sub', p_user, 'role', p_role)::text, false)
$$;

create function tests.ok(p_cond boolean, p_label text) returns void language plpgsql as $$
begin
  if p_cond is not true then raise exception 'FAIL: %', p_label; end if;
  raise notice 'ok   %', p_label;
end $$;

create function tests.rows(p_sql text, p_expected int, p_label text) returns void
language plpgsql as $$
declare n int;
begin
  execute format('with q as (%s) select count(*) from q', p_sql) into n;
  if n <> p_expected then
    raise exception 'FAIL: % (expected % rows, got %)', p_label, p_expected, n;
  end if;
  raise notice 'ok   %', p_label;
end $$;

create function tests.denied(p_sql text, p_label text) returns void language plpgsql as $$
begin
  begin
    execute p_sql;
  exception when others then
    raise notice 'ok   % (refused: %)', p_label, sqlerrm;
    return;
  end;
  raise exception 'FAIL: % (expected to be refused, but it ran)', p_label;
end $$;

grant execute on all functions in schema tests to anon, authenticated, service_role;

-- Write the first half of the audit trail in Kenyan time and the rest in UTC, so the chain
-- must verify the same from either (PR 8 review, finding 1).
set timezone = 'Africa/Nairobi';

-- Seed data (as the database owner) ------------------------------------------------------------
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000a', 'manager@lionesses.test'),
  ('00000000-0000-0000-0000-00000000000b', 'treasurer@lionesses.test'),
  ('00000000-0000-0000-0000-00000000000c', 'captain@lionesses.test'),
  ('00000000-0000-0000-0000-00000000000d', 'manager@otherclub.test');

insert into public.clubs (id, name) values
  ('10000000-0000-0000-0000-000000000001', 'Synthetic Lionesses FC'),
  ('10000000-0000-0000-0000-000000000002', 'Other Club FC');

insert into public.club_members (club_id, user_id, role, display_name) values
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000000a', 'manager', 'Coach'),
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000000b', 'treasurer', 'Treasurer'),
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000000c', 'captain', 'Captain'),
  ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-00000000000d', 'manager', 'Other coach');

insert into public.roster_entries (club_id, player_code, full_name, phone_key, consent_by, consent_at)
values ('10000000-0000-0000-0000-000000000001', 'P07', 'Synthetic Player', repeat('ab', 32),
        'player', now());

insert into public.dossiers (id, club_id, period_from, period_to) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '2026-10-01', '2026-10-31'),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '2026-10-01', '2026-10-31'),
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000001', '2026-11-01', '2026-11-30');

insert into public.dossier_items (id, dossier_id, club_id, tx, ts, amt_cents, dir, branch, category,
                                  cp_type, cp_ref, salt) values
  ('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001',
   '10000000-0000-0000-0000-000000000001', 'SJK3ABC12D', '2026-10-17 07:15+03', 25000, 'out',
   'B', 'transport', 'player', 'hmac:' || repeat('ab', 32), 'q3VbZ0xPa2N1dGVzdA'),
  ('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001',
   '10000000-0000-0000-0000-000000000001', 'SJL7KIT01Q', '2026-10-20 15:42+03', 2200000, 'out',
   'A', 'kit', 'till', '512345', 'c2FsdC1mb3Ita2l0');

insert into public.attestations (item_id, club_id, kind, method, token_hash, expires_at) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'captain',
   'link', repeat('cd', 32), now() + interval '72 hours');

\warn '--- anonymous visitor'
reset role; select tests.act_as(null, 'anon'); set role anon;
select tests.denied('select * from public.clubs', 'anon cannot read clubs');
select tests.denied('select * from public.dossiers', 'anon cannot read dossiers');
select tests.denied('select * from public.roster_entries', 'anon cannot read the roster');
select tests.denied('select * from public.audit_log', 'anon cannot read the audit log');
select tests.ok(public.public_dossier('20000000-0000-0000-0000-000000000001') is null,
                'public_dossier hides a draft');
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'submitted', null)$$, 'anon cannot change dossier status');

\warn '--- manager of another club'
reset role; select tests.act_as('00000000-0000-0000-0000-00000000000d', 'authenticated');
set role authenticated;
select tests.rows('select * from public.dossiers', 1, 'sees only their own club''s dossier');
select tests.rows($$select * from public.dossier_items$$, 0, 'sees no rows from another club');
select tests.rows('select * from public.roster_entries', 0, 'sees no other club''s roster');
select tests.rows($$update public.dossier_items set category = 'other' returning 1$$, 0,
                  'cannot re-tag another club''s rows');

\warn '--- captain'
reset role; select tests.act_as('00000000-0000-0000-0000-00000000000c', 'authenticated');
set role authenticated;
select tests.rows('select * from public.dossier_items', 2, 'captain sees the club ledger');
select tests.rows('select * from public.roster_entries', 0, 'captain cannot see player personal data');
select tests.rows($$update public.dossier_items set category = 'meals' returning 1$$, 0,
                  'captain cannot re-tag rows');
select tests.rows('select id, kind, response from public.attestations', 1,
                  'captain sees attestation status');
select tests.denied('select token_hash from public.attestations',
                    'nobody in the browser can read attestation token hashes');

\warn '--- manager'
reset role; select tests.act_as('00000000-0000-0000-0000-00000000000a', 'authenticated');
set role authenticated;
select tests.rows('select * from public.roster_entries', 1, 'manager sees the roster');
select tests.rows($$update public.dossier_items set category = 'allowance'
                    where tx = 'SJK3ABC12D' returning 1$$, 1, 'manager re-tags a draft row');
select tests.denied($$update public.dossier_items set amt_cents = 1 where tx = 'SJK3ABC12D'$$,
                    'manager cannot edit an amount from the statement');
select tests.denied($$insert into public.dossier_items (dossier_id, club_id, tx, ts, amt_cents,
                    dir, branch, category, cp_type, cp_ref, salt) values
                    ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
                     'SFAKE00001', now(), 100, 'out', 'B', 'meals', 'person', 'x', 'c2FsdC1mb3Ita2l0')$$,
                    'manager cannot add rows that weren''t in the statement');
select tests.denied($$update public.dossiers set status = 'approved'$$,
                    'manager cannot change status directly');
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'submitted', '00000000-0000-0000-0000-00000000000a')$$,
                    'browser users cannot call the state machine directly');
select tests.denied($$insert into public.audit_log (action, hash) values ('forged', 'x')$$,
                    'manager cannot write to the audit log');
select tests.denied($$insert into public.webauthn_credentials (id, user_id, public_key)
                    values ('cred-self', '00000000-0000-0000-0000-00000000000a', 'unverified-key')$$,
                    'a browser cannot save a passkey without server-side verification');

\warn '--- engine (service role): submit'
reset role; select tests.act_as(null, 'service_role'); set role service_role;
select tests.rows('select * from public.dossiers', 3, 'the engine can read every dossier');
select tests.rows('select token_hash from public.attestations', 1,
                  'the engine can read attestation token hashes (browsers can''t)');
select tests.rows('select * from public.audit_log', 0, 'the engine can read the audit log');
select tests.denied($$update public.dossiers set status = 'submitted'
                    where id = '20000000-0000-0000-0000-000000000001'$$,
                    'even the engine cannot change status without the state machine');
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'submitted', '00000000-0000-0000-0000-00000000000a')$$,
                    'submit refused without the manager''s passkey signature');
insert into public.approvals (dossier_id, club_id, user_id, role, challenge, cred_id,
                              authenticator_data, client_data_json, signature)
values ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-00000000000a', 'manager', repeat('ef', 32), 'cred-m', 'ad', 'cd', 'sig');
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'submitted', '00000000-0000-0000-0000-00000000000c')$$,
                    'the captain cannot submit');
select tests.ok((public.transition_dossier('20000000-0000-0000-0000-000000000001', 'submitted',
                 '00000000-0000-0000-0000-00000000000a')).status = 'submitted',
                'the manager submits');

\warn '--- after submission'
reset role; select tests.act_as('00000000-0000-0000-0000-00000000000a', 'authenticated');
set role authenticated;
select tests.denied($$update public.dossier_items set category = 'meals' where tx = 'SJK3ABC12D'$$,
                    'ledger rows freeze once submitted');
reset role; set role service_role;
select tests.denied($$delete from public.approvals$$, 'approvals can''t be removed');

\warn '--- engine: approve'
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'approved', '00000000-0000-0000-0000-00000000000b')$$,
                    'approve refused without the treasurer''s signature');
insert into public.approvals (dossier_id, club_id, user_id, role, challenge, cred_id,
                              authenticator_data, client_data_json, signature)
values ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-00000000000b', 'treasurer', repeat('ef', 32), 'cred-t', 'ad', 'cd', 'sig');
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'approved', '00000000-0000-0000-0000-00000000000b')$$,
                    'approve refused while an attestation is unanswered');
update public.attestations set response = 'confirmed', used_at = now();
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'approved', '00000000-0000-0000-0000-00000000000a')$$,
                    'the manager cannot approve their own dossier');
select tests.ok((public.transition_dossier('20000000-0000-0000-0000-000000000001', 'approved',
                 '00000000-0000-0000-0000-00000000000b')).status = 'approved',
                'the treasurer approves');
select tests.denied($$update public.attestations set response = 'disputed'$$,
                    'attestations close once approved');

\warn '--- engine: seal'
set timezone = 'UTC';
select tests.denied($$select public.seal_dossier('20000000-0000-0000-0000-000000000001',
                    repeat('11', 32), '{"merkle_root": "different"}'::jsonb, 'local-dev', 'sig',
                    'dossiers/x.pdf', repeat('22', 32))$$,
                    'seal refused when the payload''s root doesn''t match');
select tests.ok((public.seal_dossier('20000000-0000-0000-0000-000000000001', repeat('11', 32),
                 jsonb_build_object('merkle_root', repeat('11', 32)), 'local-dev', 'sig',
                 'dossiers/x.pdf', repeat('22', 32))).status = 'sealed', 'the engine seals');
select tests.denied($$update public.dossiers set payload = '{}'::jsonb
                    where id = '20000000-0000-0000-0000-000000000001'$$,
                    'a sealed payload can''t be edited, even by the engine');
select tests.denied($$delete from public.dossiers where id = '20000000-0000-0000-0000-000000000001'$$,
                    'a sealed dossier can''t be deleted');
select tests.denied($$update public.dossier_items set dossier_id = '20000000-0000-0000-0000-000000000003'
                    where tx = 'SJK3ABC12D'$$,
                    'a sealed row can''t be moved into a draft dossier');
select tests.denied($$update public.attestations set item_id = '30000000-0000-0000-0000-000000000002'$$,
                    'an attestation can''t be moved to another row');
select tests.denied($$insert into public.dossier_items (dossier_id, club_id, tx, ts, amt_cents, dir,
                    branch, category, cp_type, cp_ref, salt) values
                    ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002',
                     'SCLUBMIX01', now(), 100, 'out', 'B', 'meals', 'person', 'x', 'c2FsdC1mb3Ita2l0')$$,
                    'a row''s club must match its dossier''s club');
select tests.ok((select count(*) from public.dossier_items
                 where dossier_id = '20000000-0000-0000-0000-000000000003') = 0,
                'nothing was moved or added to the draft');

\warn '--- public verifier'
reset role; select tests.act_as(null, 'anon'); set role anon;
select tests.ok(public.public_dossier('20000000-0000-0000-0000-000000000001') ->> 'status' = 'sealed',
                'anyone can fetch a sealed dossier by ID');
select tests.ok(public.public_dossier('20000000-0000-0000-0000-000000000001') ? 'signature',
                'the public record includes the signature');
select tests.ok(not (public.public_dossier('20000000-0000-0000-0000-000000000001') ? 'source_sha256'),
                'the public record leaves out internal fields');

\warn '--- revoke'
reset role; set role service_role;
select tests.denied($$select public.transition_dossier('20000000-0000-0000-0000-000000000001',
                    'revoked', '00000000-0000-0000-0000-00000000000b', '  ')$$,
                    'revoking needs a reason');
select tests.ok((public.transition_dossier('20000000-0000-0000-0000-000000000001', 'revoked',
                 '00000000-0000-0000-0000-00000000000b', 'Duplicate of the November dossier')).status
                 = 'revoked', 'the treasurer revokes with a reason');
select tests.denied($$update public.dossiers set revoke_reason = 'changed'
                    where id = '20000000-0000-0000-0000-000000000001'$$,
                    'a revoked dossier never changes');

\warn '--- draft dossiers (create_draft_dossier)'
reset role;  -- helpers are created as the owner, then the checks run as the engine
create function tests.items(p_tx_prefix text) returns jsonb language sql as $$
  select jsonb_build_array(
    jsonb_build_object('tx', p_tx_prefix || '0000001', 'ts', '2026-11-07 07:15:00+03', 'amt_cents', 25000,
      'fee_cents', 700, 'dir', 'out', 'branch', 'B', 'category', 'transport', 'cp_type', 'player',
      'cp_ref', 'P01', 'fixture_code', 'MD5-2026-11-07', 'salt', 'c2FsdC1mb3ItZHJhZnQ'),
    jsonb_build_object('tx', p_tx_prefix || '0000002', 'ts', '2026-11-07 11:30:00+03', 'amt_cents', 180000,
      'dir', 'out', 'branch', 'A', 'category', 'meals', 'cp_type', 'till', 'cp_ref', '5123456',
      'salt', 'c2FsdC1mb3ItZHJhZnQy'))
$$;
grant execute on function tests.items(text) to service_role;
create table tests.ids (label text primary key, id uuid);
grant all on tests.ids to service_role;
select tests.act_as(null, 'service_role'); set role service_role;
select tests.denied($$select public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
                    '00000000-0000-0000-0000-00000000000c', '2026-11-01', '2026-11-30', repeat('a1', 32),
                    40, '{}'::jsonb, tests.items('SDA'))$$, 'only the manager can create a draft');
select tests.denied($$select public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
                    '00000000-0000-0000-0000-00000000000a', '2026-11-01', '2026-11-30', repeat('a1', 32),
                    40, '{}'::jsonb, '[]'::jsonb)$$, 'a draft needs at least one row');
insert into tests.ids select 'first', (public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-00000000000a', '2026-11-01', '2026-11-30', repeat('a1', 32), 40,
  '{"score_bp": 9500}'::jsonb, tests.items('SDA')) ->> 'dossier_id')::uuid;
select tests.rows($$select * from public.dossier_items where dossier_id = (select id from tests.ids where label = 'first')$$,
                  2, 'the manager creates a draft with its rows');
select tests.ok((select fee_cents from public.dossier_items where tx = 'SDA0000001') = 700,
                'the fee is stored with its transfer');
select tests.ok((select status from public.dossiers where id = (select id from tests.ids where label = 'first')) = 'draft',
                'a new dossier starts as a draft');
select tests.ok((public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
                 '00000000-0000-0000-0000-00000000000a', '2026-11-01', '2026-11-30', repeat('a1', 32), 40,
                 '{}'::jsonb, tests.items('SDA')) ->> 'replaced_draft')::boolean,
                'saving the same statement again replaces the earlier draft');
select tests.rows($$select * from public.dossiers where source_sha256 = repeat('a1', 32)$$, 1,
                  'only one draft per statement remains');
select tests.rows($$select * from public.dossiers where id = (select id from tests.ids where label = 'first')$$, 0,
                  'the replaced draft and its rows were deleted (cascade fix)');
insert into tests.ids select 'second', id from public.dossiers where source_sha256 = repeat('a1', 32);
insert into public.approvals (dossier_id, club_id, user_id, role, challenge, cred_id,
                              authenticator_data, client_data_json, signature)
select id, '10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000000a', 'manager',
       repeat('ef', 32), 'cred-m', 'ad', 'cd', 'sig' from tests.ids where label = 'second';
select public.transition_dossier((select id from tests.ids where label = 'second'), 'submitted',
                                 '00000000-0000-0000-0000-00000000000a');
select tests.denied($$select public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
                    '00000000-0000-0000-0000-00000000000a', '2026-11-01', '2026-11-30', repeat('a1', 32),
                    40, '{}'::jsonb, tests.items('SDB'))$$,
                    'a statement already in a submitted dossier is refused');
reset role;  -- as the owner, so only the unique index can refuse it
select tests.denied($$insert into public.dossiers (club_id, period_from, period_to, source_sha256)
                    values ('10000000-0000-0000-0000-000000000001', '2026-11-01', '2026-11-30',
                            repeat('a1', 32))$$,
                    'a second live dossier for one statement is refused by the database');
select tests.act_as('00000000-0000-0000-0000-00000000000a', 'authenticated'); set role authenticated;
select tests.denied($$select public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
                    '00000000-0000-0000-0000-00000000000a', '2026-11-01', '2026-11-30', repeat('b2', 32),
                    40, '{}'::jsonb, tests.items('SDC'))$$,
                    'browsers cannot call create_draft_dossier directly');
reset role; select tests.act_as(null, 'service_role'); set role service_role;

\warn '--- passkey approvals (approve_dossier)'
reset role;
create function tests.leaves(p_keys text[]) returns jsonb language sql as $$
  select coalesce(jsonb_object_agg(k, repeat(right(k, 1), 64)), '{}'::jsonb) from unnest(p_keys) k
$$;
-- Sign as p_actor with passkey p_cred. The fingerprint defaults to the current one.
create function tests.approve(p_actor uuid, p_cred text, p_count bigint,
                              p_challenge text default repeat('c1', 32),
                              p_leaves jsonb default tests.leaves('{SPA0000001,SPA0000002}'),
                              p_fingerprint text default null) returns jsonb
language sql as $$
  select public.approve_dossier(d, p_actor,
    coalesce(p_fingerprint, public.approval_snapshot(d) ->> 'fingerprint'),
    p_challenge, p_leaves, p_cred, 'authdata', 'clientdata', 'sig', p_count)
  from (select id as d from tests.ids where label = 'pk') x
$$;
grant execute on all functions in schema tests to service_role;
select tests.act_as(null, 'service_role'); set role service_role;

insert into tests.ids select 'pk', (public.create_draft_dossier('10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-00000000000a', '2026-12-01', '2026-12-31', repeat('e5', 32), 30,
  '{"score_bp": 9500}'::jsonb, tests.items('SPA')) ->> 'dossier_id')::uuid;
-- One receipt per ledger row (receipts.item_id is unique), so approval_content()'s join can't
-- repeat a row and the leaf count always equals the row count.
reset role;
insert into public.receipts (item_id, club_id, image_sha256, thumb_path)
select id, club_id, repeat('9d', 32), 'receipts/t1.jpg' from public.dossier_items where tx = 'SPA0000001';
select tests.denied($$insert into public.receipts (item_id, club_id, image_sha256, thumb_path)
                    select id, club_id, repeat('9e', 32), 'receipts/t2.jpg'
                    from public.dossier_items where tx = 'SPA0000001'$$,
                    'a ledger row can''t have a second receipt');
select tests.ok((select jsonb_array_length(public.approval_content(id) -> 'items') from tests.ids
                 where label = 'pk') = 2, 'a row with a receipt still appears once in the payload');
select tests.act_as(null, 'service_role'); set role service_role;
select public.add_passkey('00000000-0000-0000-0000-00000000000a', 'cred-manager', 'cose-m', 0, '{internal}');
select public.add_passkey('00000000-0000-0000-0000-00000000000b', 'cred-treasurer', 'cose-t', 5, null);
select tests.denied($$select public.add_passkey('00000000-0000-0000-0000-00000000000c', 'cred-manager',
                    'cose-x', 0, null)$$, 'a passkey ID can only be registered once');
select tests.ok((select (s ->> 'status') = 'draft' and jsonb_array_length(s -> 'items') = 2
                        and (s ->> 'fingerprint') ~ '^[0-9a-f]{64}$'
                 from (select public.approval_snapshot(id) s from tests.ids where label = 'pk') x),
                'the engine reads the rows and a fingerprint to build the challenge from');

select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000b', 'cred-treasurer', 6)$$,
                    'the treasurer can''t submit a draft');
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000a', 'cred-treasurer', 6)$$,
                    'the manager can''t sign with someone else''s passkey');
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000a', 'cred-manager', 0,
                    p_leaves => tests.leaves('{SPA0000001}'))$$, 'every row needs its leaf hash');
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000a', 'cred-manager', 0,
                    p_leaves => tests.leaves('{SPA0000001,SPA0000002,SPA0000003}'))$$,
                    'leaf hashes for rows that don''t exist are refused');
-- The manager edits a row after the engine built the challenge, then the signature arrives.
reset role;
create temporary table stale as
  select public.approval_snapshot(id) ->> 'fingerprint' as fp from tests.ids where label = 'pk';
grant select on stale to service_role;
update public.dossier_items set category = 'kit' where tx = 'SPA0000002';
select tests.act_as(null, 'service_role'); set role service_role;
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000a', 'cred-manager', 0,
                    p_fingerprint => (select fp from stale))$$,
                    'a signature over the rows as they were before an edit is refused');
select tests.ok((select status from public.dossiers d join tests.ids i on i.id = d.id
                 where i.label = 'pk') = 'draft', 'refused signatures change nothing');

select tests.ok((tests.approve('00000000-0000-0000-0000-00000000000a', 'cred-manager', 0) ->> 'status')
                = 'submitted', 'the manager''s passkey signature submits the dossier');
select tests.rows($$select * from public.dossier_items i join tests.ids t on t.id = i.dossier_id
                    where t.label = 'pk' and i.leaf_hash = repeat(right(i.tx, 1), 64)$$, 2,
                  'leaf hashes are frozen with the manager''s signature');
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000a', 'cred-manager', 1)$$,
                    'the manager can''t sign twice');
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000b', 'cred-treasurer', 6,
                    p_challenge => repeat('c2', 32), p_leaves => null)$$,
                    'the treasurer must sign exactly what the manager signed');
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000b', 'cred-treasurer', 5,
                    p_leaves => null)$$, 'a passkey counter that doesn''t go up is refused (cloned key)');
select tests.ok((tests.approve('00000000-0000-0000-0000-00000000000b', 'cred-treasurer', 6, p_leaves => null)
                 ->> 'status') = 'approved', 'the treasurer''s passkey signature approves it');
select tests.ok((select sign_count from public.webauthn_credentials where id = 'cred-treasurer') = 6,
                'the passkey''s counter is stored');
select tests.rows($$select * from public.approvals a join tests.ids t on t.id = a.dossier_id
                    where t.label = 'pk' and a.challenge = repeat('c1', 32)$$, 2,
                  'both approvals record the same challenge');
select tests.denied($$select tests.approve('00000000-0000-0000-0000-00000000000b', 'cred-treasurer', 7,
                    p_leaves => null)$$, 'an approved dossier takes no more signatures');
reset role; select tests.act_as('00000000-0000-0000-0000-00000000000a', 'authenticated'); set role authenticated;
select tests.denied($$select public.approval_snapshot((select id from public.dossiers limit 1))$$,
                    'browsers cannot read approval snapshots');
select tests.denied($$select public.approve_dossier(gen_random_uuid(), '00000000-0000-0000-0000-00000000000a',
                    repeat('0', 64), repeat('c1', 32), null, 'cred-manager', 'a', 'c', 's', 9)$$,
                    'browsers cannot record approvals');
select tests.denied($$select public.add_passkey('00000000-0000-0000-0000-00000000000a', 'cred-new', 'k', 0, null)$$,
                    'browsers cannot register passkeys directly');
select tests.denied($$insert into public.webauthn_credentials (id, user_id, public_key)
                    values ('cred-sneaky', '00000000-0000-0000-0000-00000000000a', 'k')$$,
                    'browsers cannot insert passkeys into the table either');
reset role; select tests.act_as(null, 'service_role'); set role service_role;

\warn '--- audit log'
select tests.rows($$select * from public.audit_log
                    where dossier_id = '20000000-0000-0000-0000-000000000001'$$, 4,
                  'submit, approve, seal and revoke were each logged');
select tests.denied('update public.audit_log set action = ''edited''',
                    'audit entries can''t be edited, even by the engine');
select tests.denied('delete from public.audit_log', 'audit entries can''t be deleted');
select tests.ok(public.verify_audit_chain() is null, 'the audit hash chain is intact (UTC session)');
set timezone = 'Africa/Nairobi';
select tests.ok(public.verify_audit_chain() is null,
                'the chain verifies the same from a Kenyan-time session');
set timezone = 'UTC';
reset role;
-- Simulate tampering by a database superuser who switches the protection off.
alter table public.audit_log disable trigger audit_log_no_update_delete;
update public.audit_log set details = '{"reason": "edited"}' where action = 'dossier.revoked';
alter table public.audit_log enable trigger audit_log_no_update_delete;
select tests.ok(public.verify_audit_chain() is not null,
                'tampering with an entry is detected by the hash chain');

\warn 'ALL DATABASE TESTS PASSED'
