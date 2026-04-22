# Skill: Systematic Debugging
# Invoke: "use the debug skill"

## Rule
Identify root cause before writing any fix. A fix without confirmed root cause is a guess.

## Process
1. **State the symptom precisely** — observed vs. expected, one sentence.
2. **Find the failure boundary** — which layer? Run smallest possible reproduction.
3. **Form a hypothesis** — "I think X is caused by Y because Z."
4. **Verify the hypothesis** — add a log or assertion. Do not fix yet.
5. **Fix the confirmed root cause** — targeted, not defensive.
6. **Verify the fix** — original reproduction passes, full test suite clean.
7. **Capture the learning** — add to CHECKPOINT.md, say "save this to memory" if reusable.

## Common failure patterns — application stack

| Symptom | Likely cause |
|---|---|
| `422 Unprocessable Entity` on a route | Pydantic validation — check request body shape vs schema |
| `session.refresh()` AttributeError | Forgot to call refresh after commit |
| Empty `content` from trafilatura | Page is JS-rendered (needs Puppeteer) or paywalled |
| feedparser returns no entries | Feed URL redirects — use trafilatura to discover real feed URL |
| Alembic `can't locate revision` | Migration file deleted or not committed |
| TanStack Query stale data after mutation | Missing `queryClient.invalidateQueries` in `onSuccess` |
| Vite proxy 502 | Backend not running on :8000, or wrong proxy target in vite.config.ts |

## Common failure patterns — Docker Compose (dev)

| Symptom | Likely cause |
|---|---|
| `docker compose up` hangs on backend | Template's healthcheck waiting on DB that's still initialising — check `docker compose logs db` |
| Generated TS client has empty types | Missing `response_model=` on a route; regenerate after fixing |
| 401 on every request in dev | JWT expired, or `.env` missing `SECRET_KEY`; template defaults it but check |

## Common failure patterns — Podman / rootless (production only)

| Symptom | Likely cause | Fix |
|---|---|---|
| `permission denied` on volume mount | Missing `:Z` SELinux flag | Add `:Z` to volume in compose override |
| Container exits immediately | Check logs: `podman logs <name>` | Often a missing env var or failed healthcheck |
| Port 80/443 bind fails | `ip_unprivileged_port_start` not set | Run sysctl setup as root (see podman-setup.md) |
| Inter-container name resolution fails | pasta networking (Podman 5+) limits loopback | Ensure same podman network; use service name not `localhost` |
| `XDG_RUNTIME_DIR not set` | Missing env var for rootless session | Add to `.bashrc`: `export XDG_RUNTIME_DIR=/run/user/$(id -u)` |
| Containers stop on logout | Linger not enabled | `loginctl enable-linger labrat` as root |
| `sudo podman` fails or behaves oddly | Running rootful instead of rootless | Never use `sudo` with Podman — always run as labrat directly |
| `su - labrat && podman` fails | `su` breaks user namespace for rootless | SSH directly as labrat instead |
| Volume data missing after restart | Wrong volume path assumed | Rootless volumes live at `~/.local/share/containers/storage/volumes/` |

## Checking container logs
```bash
# Dev (Docker)
docker compose logs backend          # full logs
docker compose logs -f backend       # follow

# Prod (Podman)
podman ps                            # get container names
podman logs llamapack_backend_1      # full logs
podman logs -f llamapack_backend_1   # follow
podman inspect <name>                # full container config (useful for mount debugging)
```
