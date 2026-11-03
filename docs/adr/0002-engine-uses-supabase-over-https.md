# ADR 0002: The engine talks to Supabase over HTTPS only

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decider:** Chris Waweru, with the team

## Context

The build plan had the engine write to Postgres directly (`app/db.py` with psycopg and `DATABASE_URL`). Testing on 2026-11-03 showed the team's usual network **blocks outbound ports 5432 and 6543** (Postgres) and **7844** (Cloudflare Tunnel), while port 443 works. A neutral port-5432 test server also timed out, so this is the network, not Supabase. The Day 9 field venue and the demo venue could do the same. At the time of this decision, no engine code talks to the database yet, so nothing needs rework.

## Decision

1. **The engine reaches Supabase only over HTTPS (port 443)**, through the Data API (PostgREST) and Auth API with the secret key (`SUPABASE_SERVICE_ROLE_KEY`). No Postgres driver in the engine.
2. **Anything that must happen all-or-nothing is a Postgres function**, called over HTTPS (`POST /rest/v1/rpc/<name>`). Postgres runs each call as one transaction. The plan already puts the dossier state machine in one (`transition_dossier`); sealing and approval writes follow the same pattern.
3. **`DATABASE_URL` is for migrations only.** Run them from a network that allows port 5432 (a phone hotspot works), or paste the SQL into the Supabase SQL editor, which runs over HTTPS. `tools/check_infra.py` reports the database login as a **warning**, not a failure.
4. **On restrictive networks, the engine laptop uses a phone hotspot.** Only that laptop's own outbound connection matters (443 and 7844); the other devices can stay on the venue Wi-Fi.

## Consequences

- Good: the engine works on any network that allows HTTPS, which removes a demo-day failure mode.
- Good: one protocol and one credential for the engine; no connection pool to manage.
- Good: multi-step rules live in the database next to the row-level security that guards them, so the web app and engine can't apply them differently.
- Cost: the engine can't run several separate queries inside a transaction it controls. Anything that needs that becomes a Postgres function, written as part of the migrations.
- Cost: the secret key bypasses row-level security, so engine code must scope every query by club itself. Reviews should check this.
- Risk register: add "venue network blocks 7844" (mitigation: hotspot for the engine laptop; pre-sealed dossier and recorded demo as fallback).
