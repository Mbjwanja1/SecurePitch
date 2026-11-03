-- Core tables. Data model: docs/PLAN.md section 08; leaf fields: docs/CRYPTO_SPEC.md section 4.
--
-- Never stored anywhere: statement files or passwords, rows tagged personal, raw counterparty
-- phone numbers, receipt EXIF. Money is integer cents; hashes are lowercase hex.

create type public.member_role as enum ('manager', 'treasurer', 'captain');
create type public.dossier_status as enum ('draft', 'submitted', 'approved', 'sealed', 'revoked');
create type public.leaf_branch as enum ('A', 'B', 'I'); -- A merchant, B squad, I club income
create type public.money_direction as enum ('in', 'out');
create type public.item_category as enum (
  'transport', 'allowance', 'meals', 'kit', 'ground_hire', 'income', 'other'
);
create type public.counterparty_type as enum ('player', 'till', 'paybill', 'person');
create type public.attestation_kind as enum ('captain', 'corroboration');
create type public.attestation_method as enum ('passkey', 'link', 'callback');
create type public.attestation_response as enum ('confirmed', 'disputed');

create table public.clubs (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(name) between 2 and 120),
  legal_status text,
  governance_tier text,
  required_approvals smallint not null default 2 check (required_approvals between 1 and 3),
  created_at timestamptz not null default now()
);

create table public.club_members (
  club_id uuid not null references public.clubs (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  role public.member_role not null,
  display_name text not null,
  created_at timestamptz not null default now(),
  primary key (club_id, user_id)
);
create index club_members_user_idx on public.club_members (user_id);

-- Players are identified by HMAC keys of their phone numbers (keyed with ROSTER_PEPPER in the
-- engine); the raw number is never stored. player_code is the pseudonym used in dossiers.
create table public.roster_entries (
  id uuid primary key default gen_random_uuid(),
  club_id uuid not null references public.clubs (id) on delete cascade,
  player_code text not null check (player_code ~ '^P[0-9]{2,3}$'),
  full_name text not null,
  fkf_id text,
  phone_key text not null check (phone_key ~ '^[0-9a-f]{64}$'),
  mask_key text check (mask_key ~ '^[0-9a-f]{64}$'),
  is_minor boolean not null default false,
  consent_by text not null,
  consent_at timestamptz not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (club_id, player_code),
  unique (club_id, phone_key)
);

create table public.fixtures (
  id uuid primary key default gen_random_uuid(),
  club_id uuid not null references public.clubs (id) on delete cascade,
  fixture_code text not null,
  match_date date not null,
  opponent text,
  venue text,
  unique (club_id, fixture_code)
);

create table public.dossiers (
  id uuid primary key default gen_random_uuid(),
  club_id uuid not null references public.clubs (id) on delete cascade,
  period_from date not null,
  period_to date not null,
  status public.dossier_status not null default 'draft',
  source_sha256 text check (source_sha256 ~ '^[0-9a-f]{64}$'),
  rows_total integer check (rows_total >= 0),
  integrity jsonb,
  merkle_root text check (merkle_root ~ '^[0-9a-f]{64}$'),
  payload jsonb,
  kid text,
  signature text,
  pdf_path text,
  pdf_sha256 text check (pdf_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid references auth.users (id),
  created_at timestamptz not null default now(),
  submitted_at timestamptz,
  approved_at timestamptz,
  sealed_at timestamptz,
  revoked_at timestamptz,
  revoke_reason text,
  check (period_to >= period_from),
  -- A sealed or revoked dossier always carries its seal.
  check (status not in ('sealed', 'revoked')
         or (merkle_root is not null and payload is not null and signature is not null
             and kid is not null and sealed_at is not null)),
  check (status <> 'revoked' or (revoked_at is not null and length(revoke_reason) > 0))
);
create index dossiers_club_idx on public.dossiers (club_id, status);

-- One disclosed club row = one Merkle leaf. club_id is copied from the dossier so row-level
-- security can check it without a join.
create table public.dossier_items (
  id uuid primary key default gen_random_uuid(),
  dossier_id uuid not null references public.dossiers (id) on delete cascade,
  club_id uuid not null references public.clubs (id) on delete cascade,
  tx text not null check (tx ~ '^[A-Z0-9]{10}$'),
  ts timestamptz not null,
  amt_cents bigint not null check (amt_cents > 0 and amt_cents <= 9007199254740991),
  dir public.money_direction not null,
  branch public.leaf_branch not null,
  category public.item_category not null,
  cp_type public.counterparty_type not null,
  cp_ref text not null,
  fixture_code text,
  salt text not null check (salt ~ '^[A-Za-z0-9_-]{16,}$'),
  leaf_hash text check (leaf_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  unique (dossier_id, tx)
);
create index dossier_items_dossier_idx on public.dossier_items (dossier_id);

create table public.planned_spends (
  id uuid primary key default gen_random_uuid(),
  dossier_id uuid not null references public.dossiers (id) on delete cascade,
  club_id uuid not null references public.clubs (id) on delete cascade,
  supplier text not null,
  till text not null check (till ~ '^[0-9]{5,7}$'),
  amt_cents bigint not null check (amt_cents > 0),
  purpose text not null
);

create table public.receipts (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null unique references public.dossier_items (id) on delete cascade,
  club_id uuid not null references public.clubs (id) on delete cascade,
  image_sha256 text not null check (image_sha256 ~ '^[0-9a-f]{64}$'),
  thumb_path text not null,
  created_at timestamptz not null default now()
);

-- Attestation links are bearer tokens: only their SHA-256 is stored, they expire and are
-- single-use.
create table public.attestations (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references public.dossier_items (id) on delete cascade,
  club_id uuid not null references public.clubs (id) on delete cascade,
  kind public.attestation_kind not null,
  method public.attestation_method not null,
  token_hash text unique check (token_hash ~ '^[0-9a-f]{64}$'),
  expires_at timestamptz,
  used_at timestamptz,
  response public.attestation_response,
  cred_id text,
  recorded_by uuid references auth.users (id),
  created_at timestamptz not null default now(),
  check (method = 'callback' or (token_hash is not null and expires_at is not null)),
  check ((response is null) = (used_at is null))
);
create index attestations_item_idx on public.attestations (item_id);

-- Passkey signatures over the dossier payload digest (docs/CRYPTO_SPEC.md section 6).
create table public.approvals (
  id uuid primary key default gen_random_uuid(),
  dossier_id uuid not null references public.dossiers (id) on delete cascade,
  club_id uuid not null references public.clubs (id) on delete cascade,
  user_id uuid not null references auth.users (id),
  role public.member_role not null check (role in ('manager', 'treasurer')),
  challenge text not null check (challenge ~ '^[0-9a-f]{64}$'),
  cred_id text not null,
  authenticator_data text not null,
  client_data_json text not null,
  signature text not null,
  created_at timestamptz not null default now(),
  unique (dossier_id, role)
);

create table public.webauthn_credentials (
  id text primary key, -- credential ID, base64url
  user_id uuid not null references auth.users (id) on delete cascade,
  public_key text not null,
  sign_count bigint not null default 0,
  transports text[],
  created_at timestamptz not null default now()
);
create index webauthn_credentials_user_idx on public.webauthn_credentials (user_id);
