# ADR 0001: Run the engine in Docker Desktop, reached through Cloudflare Tunnel

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decider:** Chris Waweru, with the team

## Context

The Python engine handles the most sensitive data in the system: decrypted M-Pesa statements. The plan's original options were AWS Lambda with `/dev/shm`, or Railway. Neither is on the approved resource list. The approved host is Docker Desktop on a team laptop. The web app runs on Vercel and must call the engine over HTTPS, and passkeys require HTTPS on phones.

## Decision

1. Run the engine as a container in Docker Desktop with a **read-only root filesystem** and a **RAM-backed `tmpfs` at `/tmp`**. Any attempt to write a statement to disk fails with a permission error, and anything that must be a file lives only in memory.
2. Run `cloudflared` as a second container in the same `docker-compose.yml`. It opens an outbound-only tunnel and gives the engine a public HTTPS URL. No inbound ports are opened on the laptop.
3. Every engine route except `/health` requires the `X-Internal-Key` header, because the tunnel makes the engine reachable from the internet.
4. Disable WSL swap (`swap=0`) so RAM-backed data isn't paged to disk.

## Consequences

- Good: the "never written to disk" claim is enforced by the operating system, which is a stronger story for judges than a code convention. No new accounts or costs.
- Good: the same image runs in CI, locally and in the demo.
- Cost: the laptop must be on, awake and online during testing, the Day 9 field visit and the demo. Disable sleep on that laptop during those sessions.
- Cost: a quick tunnel's URL changes when the `cloudflared` container restarts. Restart only the `engine` service during development so the URL stays stable; update `ENGINE_URL` in Vercel when it does change.
- Cost: AWS credentials are a sign-only access key in `.env`, not a role (see `docs/INFRA_SETUP.md` step 4).
- Roadmap: move the same image to a managed container host (ECS Fargate or similar) with an IAM role and a named tunnel or load balancer.
