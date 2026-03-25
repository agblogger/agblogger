# Security Best Practices Review Against `main`

## Executive Summary

This review focused on the branch changes relative to `main`, especially the new GoatCounter analytics integration across the FastAPI backend, React admin UI, and deployment templates.

I found two security-relevant issues:

1. `SEC-001` (Medium): every public post/page request now creates an unbounded fire-and-forget analytics task, which enables low-cost availability pressure against both the app and the internal analytics sidecar.
2. `SEC-002` (Medium): the deployment changes mount the entire GoatCounter data volume into the main app container, so the web app can read and modify the GoatCounter API token and database, widening the blast radius of any app-container compromise.

I did not find an auth bypass on the new admin endpoints, and I did not find a frontend secret leak in the React analytics panel.

## Medium Severity

### SEC-001

- Rule ID: FASTAPI-DEPLOY-001 / availability hardening
- Severity: Medium
- Location:
  - `backend/services/analytics_service.py:271-301`
  - `backend/api/posts.py:692-752`
  - `backend/api/pages.py:35-59`
- Evidence:

```python
# backend/services/analytics_service.py
task = asyncio.create_task(_do_hit())
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

```python
# backend/api/posts.py
if post is not None:
    _fire_post_hit(request, session_factory, post.file_path, user)
```

```python
# backend/api/pages.py
fire_background_hit(
    request=request,
    session_factory=session_factory,
    path=f"/page/{page_id}",
    user=user,
)
```

- Impact: any unauthenticated client can force the server to enqueue a new DB session + outbound GoatCounter request for each public post/page hit. With no concurrency cap, queue bound, sampling, or rate limit, traffic spikes can accumulate large numbers of live tasks in `_background_tasks` and increase memory/socket pressure on both AgBlogger and GoatCounter.
- Fix: put hit recording behind a bounded queue or semaphore, and drop/shed work when the queue is saturated. A simple first step is a small `asyncio.Semaphore` around `_do_hit()` plus a counter/log when events are skipped under load.
- Mitigation: if an immediate code change is not possible, add reverse-proxy rate limiting on public post/page routes and consider sampling analytics writes rather than recording every request.
- False positive notes: this is less severe if the deployment already has strong edge rate limiting and traffic volume is very low, but the application code itself currently has no backpressure.

### SEC-002

- Rule ID: secret-boundary hardening / least privilege
- Severity: Medium
- Location:
  - `docker-compose.yml:8-12`
  - `docker-compose.yml:57-64`
  - `backend/services/analytics_service.py:38-39`
  - `goatcounter/entrypoint.sh:4-5`
  - `goatcounter/entrypoint.sh:31-32`
  - `cli/deploy_production.py:936-948`
  - `cli/deploy_production.py:986-997`
- Evidence:

```yaml
# docker-compose.yml
agblogger:
  volumes:
    - goatcounter-data:/data/goatcounter

goatcounter:
  volumes:
    - goatcounter-data:/data/goatcounter
```

```python
# backend/services/analytics_service.py
GOATCOUNTER_AUTH_FILE = "/data/goatcounter/token"
```

```sh
# goatcounter/entrypoint.sh
TOKEN_FILE="/data/goatcounter/token"
echo "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
```

- Impact: the main web app now has direct filesystem access to the GoatCounter token and database, so any app-container compromise can pivot into the analytics sidecar and tamper with analytics state. The token file permissions do not meaningfully isolate the secret from AgBlogger because the app container is explicitly given the same volume.
- Fix: keep the GoatCounter database private to the GoatCounter container and expose only the minimum credential needed to AgBlogger via a narrower mechanism, such as a dedicated read-only secret/file mount. Avoid sharing the full writable GoatCounter data volume with the application container.
- Mitigation: if the shared volume must remain temporarily, mount it read-only on the AgBlogger side if feasible, scope the GoatCounter token to the minimum required permissions, and remove `user: root` from deployment templates so file permissions provide some real separation.
- False positive notes: AgBlogger does need some credential to query GoatCounter, so some trust relationship is unavoidable. The issue is the current breadth of that trust: full shared volume access rather than a narrowly scoped secret handoff.

## Notes

- I did not find a direct client-side XSS issue in the new analytics admin React components.
- I did not find a missing auth dependency on the new `/api/admin/analytics/*` routes; they consistently use `require_admin`.
