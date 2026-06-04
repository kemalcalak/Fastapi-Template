---
allowed-tools: Bash(gh issue view:*), Bash(gh search:*), Bash(gh issue list:*), Bash(gh pr comment:*), Bash(gh pr diff:*), Bash(gh pr view:*), Bash(gh pr list:*), Bash(gh api:*)
description: Code review a pull request against Fastapi-Template conventions
disable-model-invocation: false
---

# /review — Fastapi-Template PR Review Pipeline

You are orchestrating a multi-agent code review pipeline for a pull request in the **Fastapi-Template** (FastAPI 0.129 + Python 3.12 + uv + async SQLAlchemy 2.0 + asyncpg + Pydantic v2 + Redis + slowapi + arq + Alembic + OpenTelemetry + Prometheus + Sentry + pytest) repository. Every agent is grounded in this repo's conventions, captured in `REVIEW.md` at the repo root.

## Inputs

- `$ARGUMENTS` may contain a PR number or URL. If empty, default to the PR for the current branch (resolve via `gh pr view --json number,url,headRefOid,baseRefName,state,isDraft,title,author,body`).
- All `gh` calls must use `--json` with explicit fields. Never parse human-readable output.

## Pipeline

Execute the eight steps below in order. Each step that says "spawn an agent" must use the Agent tool. Agent prompts are written in English (more reliable for model instructions); the final user-facing comment is in **Turkish** (the project's working language).

---

### Step 1 — Eligibility check (Sonnet)

Spawn a `general-purpose` agent with `model: "sonnet"`. Prompt:

> You are gating a code review. Decide whether this PR is eligible.
>
> Run `gh pr view <PR> --json state,isDraft,author,title,body,labels,headRefOid,baseRefName,url,comments` and respond with strict JSON:
> `{ "eligible": boolean, "reason": string, "headSha": string, "baseRef": string, "url": string, "owner": string, "repo": string, "number": number }`.
>
> Mark `eligible: false` if any of the following hold:
>
> - PR `state` is not `OPEN`
> - PR `isDraft` is `true`
> - The author login matches a bot pattern (`*[bot]`, `dependabot`, `renovate`, `github-actions`)
> - The title or body indicates an auto-generated release/version-bump (e.g., `chore(release):`, `Bump dependency`, "production deploy" merges)
> - There is already a comment from a previous `/review` run (search comment bodies for the marker `<!-- review:done -->`)
>
> Otherwise `eligible: true`. Return only the JSON.

If `eligible` is false, abort the pipeline and print the reason. Do not post any comment.

Capture `headSha`, `owner`, `repo`, `number`, `url` for later steps.

---

### Step 2 — REVIEW.md path discovery (Sonnet)

Spawn a `general-purpose` agent with `model: "sonnet"`. Prompt:

> Find the path to `REVIEW.md` at the repository root for the PR head SHA `<headSha>`. Use `gh api repos/<owner>/<repo>/contents/REVIEW.md?ref=<headSha> --jq '.path'`. If it does not exist at root, search the repo tree for any file named `REVIEW.md` via `gh api repos/<owner>/<repo>/git/trees/<headSha>?recursive=1 --jq '.tree[] | select(.path | endswith("REVIEW.md")) | .path'` and pick the shortest path.
>
> Return strict JSON: `{ "reviewMdPath": string | null }`.

If `reviewMdPath` is null, post a single comment to the PR explaining `REVIEW.md` could not be found and abort. Do not flag any issues without it (false-positive risk is too high).

---

### Step 3 — PR summary (Sonnet)

Spawn a `general-purpose` agent with `model: "sonnet"`. Prompt:

> Summarize the PR for downstream reviewers.
>
> Run `gh pr view <number> --json title,body,additions,deletions,changedFiles,files` and `gh pr diff <number>` (truncate to first ~3000 lines if larger).
>
> Output strict JSON:
>
> ```
> {
>   "title": string,
>   "intent": string,            // 1-2 sentences in English describing the change goal
>   "touchedAreas": string[],    // domain folders, e.g. ["app/api/routes", "app/services", "app/repositories", "app/models", "app/alembic/versions", "app/core"]
>   "changedFiles": [{ "path": string, "additions": number, "deletions": number, "status": string }],
>   "diffExcerpt": string        // truncated unified diff (max 80k chars), used by downstream agents
> }
> ```

Pass this object to the five parallel reviewers in Step 4.

---

### Step 4 — Five parallel Sonnet reviewers

> **Read-only mandate for every spawned agent (Steps 1–5).** Each agent's ONLY output is the JSON described in its prompt. An agent MUST NOT post, edit, or delete anything on the PR: never run `gh pr comment`, `gh issue comment`, `gh pr review`, or any `gh api` call with `-X POST`/`-X PATCH`/`-X PUT`/`-X DELETE`. Only the orchestrator posts, and only once, in Step 8. Any agent that writes to the PR is a pipeline violation and causes duplicate comments.

Spawn the following five agents **in parallel** in a single message, all with `subagent_type: "general-purpose"` and `model: "sonnet"`. Each must return strict JSON of the shape:

```json
{
  "issues": [
    {
      "file": "app/...",
      "startLine": 12,
      "endLine": 18,
      "category": "review-md-compliance | bug | history | past-comment | code-comment",
      "severity": "blocker | major | minor",
      "title": "Short Turkish phrase",
      "explanation": "Turkish, 1-3 sentences. Cite REVIEW.md section or concrete reasoning.",
      "evidence": "Optional verbatim quote from REVIEW.md or the changed code",
      "suggestion": "Turkish, one-line concrete fix"
    }
  ]
}
```

#### Agent #1 — REVIEW.md compliance

> You are auditing a Fastapi-Template PR against the repository's conventions captured in `REVIEW.md` at the repo root.
>
> 1. Fetch `REVIEW.md` content: `gh api repos/<owner>/<repo>/contents/<reviewMdPath>?ref=<headSha> --jq '.content' | base64 -d`.
> 2. Read the full PR diff (provided by the orchestrator as `diffExcerpt`, plus run `gh pr diff <number>` if needed).
> 3. For every **changed line** (only lines added or modified in this PR), check whether it violates a rule in REVIEW.md sections **3 (Konvansiyonlar)**, **4 (Anti-pattern'ler)** or **5 (Review'da KESİNLİKLE Flag'lenecekler)**.
> 4. Apply REVIEW.md section **6 (Görmezden Gelinecekler)** as a hard filter — if a finding falls under that list, drop it.
>
> Anchor every issue to a section/quote from REVIEW.md (`evidence` field). Do not invent rules. Do not flag pre-existing code that the PR did not touch. Output the JSON schema above — do NOT post or modify any PR comment; return only the JSON.

#### Agent #2 — Shallow bug scan (FastAPI + async SQLAlchemy + Pydantic v2 specific)

> You are looking for concrete FastAPI / async-SQLAlchemy / Pydantic / Python bugs in the changed lines of this Fastapi-Template PR.
>
> Read the diff via `gh pr diff <number>`. Only flag bugs in **added or modified lines**. Focus on:
>
> **Layer architecture (`api → services → repositories → models`):**
>
> - Route calling repository directly without going through a service.
> - Service calling another service (use `use_cases/` or repository).
> - `Depends()` placed in service or repository function signatures (only allowed in route handlers).
> - Business logic (validation, policy, transform) inside `api/routes/` instead of services.
> - Repository function raising `HTTPException` (HTTP semantics belong in service/route, not persistence).
> - Class-based service or repository (this repo uses pure async functions only).
>
> **Async / SQLAlchemy 2.0:**
>
> - Sync DB call (`session.query(...)` SQLAlchemy 1.x style; `session.execute(...)` not awaited).
> - `await` missing on an async call → coroutine returned to caller.
> - `expire_on_commit=False` overridden somewhere new.
> - N+1 query in a list endpoint (await inside a Python `for` over rows).
> - `with_for_update()` lock removed from concurrent-mutation paths (e.g., deactivate/reactivate).
> - New `create_async_engine`/`async_sessionmaker` instance outside `app/core/db.py`.
>
> **Auth & security:**
>
> - `jwt.encode/decode` placed outside `app/core/security.py`.
> - `bcrypt` bypass — password compared with `==` or hashed with anything other than `get_password_hash`.
> - Plain-text password being logged, returned in response, or written to error message.
> - Protected route missing `Depends(get_current_user)` / `CurrentUser` / `CurrentActiveUser` / `CurrentSuperUser`.
> - `is_token_blacklisted` check skipped in custom auth resolution.
> - Token (JWT) leaked into URL query, path, log, or HTTPException detail.
> - Cookie path/domain/HttpOnly/SameSite/Secure flags changed without coordination (`access_token` "/", `refresh_token` `f"{API_V1_STR}/auth/refresh"`).
> - `verify_token` called without `expected_type` enforcement — wrong-type tokens may be accepted.
> - Sensitive endpoint (login, forgot-password, reset, account delete/reactivate, admin mutations) missing rate-limit decorator.
> - Rate-limit decorator added but route signature is missing `request: Request` (slowapi cannot resolve scope → runtime exception).
> - New `Limiter(...)` instance created outside `app/core/rate_limit.py`.
>
> **Messages / i18n:**
>
> - Inline error string (`detail="User not found"`) instead of `ErrorMessages.X`.
> - Inline success string instead of `SuccessMessages.X`.
> - New constant used but not declared in `core/messages/error_message.py` or `success_message.py` → `AttributeError`.
> - Backend message in Turkish or other natural-language string instead of `error.<domain>.<reason>` i18n key format.
>
> **Pydantic v2 / schemas:**
>
> - ORM model returned directly as response (without `response_model` Pydantic schema mapping).
> - Schema missing `model_config = ConfigDict(from_attributes=True)` while reading from ORM.
> - `field_validator` raising with inline string instead of `ErrorMessages.X`.
> - Sensitive fields (`hashed_password`, `password`, JWT) leaking into a `*Public` schema.
> - `dict()` / `parse_obj()` (Pydantic v1 deprecated) instead of `model_dump()` / `model_validate()`.
>
> **Migrations & models:**
>
> - Model field/index/constraint changed but no new migration in `app/alembic/versions/`.
> - Partial index / GIN index in `__table_args__` removed (Alembic autogenerate would keep proposing drops).
> - `passive_deletes=True` relationship without `ondelete="CASCADE"` on the FK side.
> - Raw `op.execute(...)` in migration without idempotency/justification.
>
> **Config & env:**
>
> - `os.getenv(...)` / `os.environ[...]` direct usage — must go through `app.core.config.settings`.
> - New env field used in code but not added to `Settings` class → runtime `AttributeError`.
> - New `Settings` field but `.env.example` not updated.
> - Secret with literal default fallback (`os.getenv("SECRET_KEY", "default")`) — `_check_default_secret` is intentional.
>
> **Audit logging:**
>
> - `request.client.host` / `request.headers["user-agent"]` read manually inside route — must go through `log_activity` use case.
> - Critical mutation route missing `@audit_unexpected_failure` decorator.
>
> **Observability:**
>
> - Duplicate `Sentry.init(...)` / `TracerProvider(...)` outside `app/core/sentry.py` / `app/core/telemetry.py`.
> - `/metrics` `METRICS_TOKEN` Bearer enforcement loosened or removed.
> - `/metrics` or `/health` removed from instrumentation excluded list.
> - OTel opt-in env-gate (`OTEL_EXPORTER_OTLP_ENDPOINT`) removed.
>
> **Python / typing:**
>
> - New `Any` annotation (Pyright `reportAny=error`).
> - New unjustified `# type: ignore` (existing ones have inline rationale).
> - Relative import `from ..foo import bar` (Ruff TID252 disallows).
> - Function lacking docstring (CLAUDE.md hard rule).
> - Docstring written in a language other than English.
>
> **Tests:**
>
> - Test that hits real SMTP/Redis/Postgres (autouse fixtures `mock_email_send`, `fake_redis`, `override_get_db` overridden).
> - New endpoint without test (auth/security/account-mutation → major; otherwise minor).
> - Async test missing `pytest-asyncio` setup or breaking `asyncio_mode = "auto"` config.
>
> **Origin check / CORS:**
>
> - `allow_credentials=True` combined with `"*"` origin (middleware already raises `RuntimeError`, but if PR weakens that check → blocker).
> - Origin-check 404 response shape changed (it intentionally mirrors `RESOURCE_NOT_FOUND` to avoid leaking allowed origins).
>
> Use **REVIEW.md section 6 (Görmezden Gelinecekler)** as a filter — anything in that list must be dropped, even if technically suboptimal. Output strict JSON per the shared schema.

#### Agent #3 — Git blame & history

> Investigate whether the PR's changes contradict prior intent in the same files.
>
> For each changed file, run `gh api repos/<owner>/<repo>/commits?path=<path>&per_page=20 --jq '.[] | {sha,commit:.commit.message,author:.commit.author.name}'` and `gh pr list --state merged --search "<filename>" --json number,title,url --limit 10`.
>
> Flag an issue when:
>
> - The PR reverts a recent fix (commit message indicates a bug fix on the same lines/region within the last 90 days).
> - The PR re-introduces a pattern that a previous commit explicitly removed (look for `revert`, `fix`, `refactor` messages on the same path).
> - A recent commit on the same area suggests a constraint the PR may break (e.g., `app/main.py`, `app/api/deps.py`, `app/core/security.py`, `app/core/config.py`, `app/core/middleware.py`, `app/core/rate_limit.py`, `app/api/exception_handlers.py` are tightly coordinated — changes to one without the others may break a prior fix).
>
> Be conservative: only flag with `severity: major` or `blocker` if the contradiction is direct and the prior commit message is explicit. Otherwise omit. Output strict JSON.

#### Agent #4 — Past PR comments on touched files

> Discover whether reviewers previously raised concerns on the files this PR touches.
>
> For each changed file, run `gh search prs --repo <owner>/<repo> --json number,title,url "<filename>"` and for the top 5 results fetch `gh api repos/<owner>/<repo>/pulls/<n>/comments --jq '.[] | {path,line,body,user:.user.login}'`.
>
> Flag if:
>
> - A reviewer previously rejected an identical pattern that is being reintroduced here.
> - A previously-agreed convention (e.g., "use `ErrorMessages` not inline string", "go through service not repository", "no `Depends()` in services", "Alembic migration required for model change", "rate-limit decorator on sensitive endpoints", "log_activity for audit, not manual `request.client.host`") is being violated again.
>
> Quote the prior comment in `evidence`. Skip noise. Output strict JSON.

#### Agent #5 — Inline code-comment compliance & Python typing

> Audit comments, docstrings, and Python typing added by this PR. The repo style discourages narrating the obvious; use REVIEW.md section 5 (KESİNLİKLE Flag'lenecekler) and CLAUDE.md hard rules.
>
> Flag:
>
> - New comments that describe **what** the code does when the identifier already says it (`# fetch user — get_user_by_id(...)`).
> - Comments that reference the current ticket or PR (`# added for issue X`, `# per Ali's review`) — these rot in the codebase.
> - `TODO` / `FIXME` without a tracker reference or owner.
> - Stale comments that contradict adjacent code after the change.
> - **Function added without a docstring** ([CLAUDE.md:111](CLAUDE.md) hard rule — minimum one English line).
> - Docstring written in Turkish (or any non-English language).
> - New `Any` annotation introduced — Pyright `reportAny=error` will fail. Use `unknown`-ish patterns (generics, narrowing, `object`).
> - New unjustified `# type: ignore` — existing ones have rationale (`[prop-decorator]`, etc.).
> - Relative import `from ..foo import bar` (Ruff TID252).
> - Unused function argument without `_` prefix (Ruff ARG001).
> - `print(...)` left in production-impacting code (services, repositories, core/) — use `logging`.
> - `logger.info(token)` / similar token or password leakage into logs.
> - Function complexity exceeding ruff/pyproject limits (very long functions; split into use_case/repository helpers).
> - Inline error/success string `detail="..."` even in a docstring "raises" example — this normalises the anti-pattern.
>
> Do NOT flag commented-out code unless it is clearly leftover debug. Output strict JSON.

---

### Step 5 — Per-issue confidence scoring (Haiku)

Aggregate all `issues` from the five reviewers. For each issue, spawn a `general-purpose` agent with `model: "haiku"` (or batch them in a single Haiku call passing an array — preferred for speed; Haiku is sufficient for the 0/25/50/75/100 bucketing task). Prompt:

> Score the confidence that this is a real, actionable issue worth posting on a PR review.
>
> Use the rubric below — pick the closest band, then return the integer.
>
> - **0**: Not an issue. Misreads the diff, contradicts REVIEW.md "Görmezden Gelinecekler", or describes a hypothetical that the code does not actually do.
> - **25**: Probably noise. Generic best-practice rather than a repo-specific rule. Linter/Pyright would catch it.
> - **50**: Plausible but unverified. The reasoning is sound but lacks a direct REVIEW.md anchor or a concrete reproduction.
> - **75**: Likely correct. Anchored in REVIEW.md or a clear FastAPI/async-SQLAlchemy/Pydantic bug pattern, with a specific file:line reference; minor uncertainty about user intent.
> - **100**: Definitely correct. Bug or rule violation visible in the diff, with verbatim REVIEW.md quote or unambiguous reasoning. Suggested fix is concrete.
>
> Input: `{ issue: <issue-json>, reviewMdExcerpt: <relevant section> }`.
> Output strict JSON: `{ "confidence": 0|25|50|75|100, "reason": "one short sentence" }`. Return only the JSON — do NOT post or modify any PR comment.

---

### Step 6 — Filter

Drop every issue whose `confidence < 70`. The threshold is fixed.

With the rubric's 0/25/50/75/100 bands, a threshold of 70 admits the **75 ("Likely correct")** and **100 ("Definitely correct")** tiers and rejects everything ≤ 50.

If no issues remain, post a comment indicating a clean review (still mark with the `<!-- review:done -->` sentinel) and end.

---

### Step 7 — Re-check eligibility

Re-run Step 1 quickly (the PR may have been closed, marked draft, or already commented during the run). If now ineligible, abort without posting.

---

### Step 8 — Post the review comment

Build the comment in **Turkish**. For each surviving issue, generate a permanent GitHub link using the **full head SHA** captured in Step 1:

```
https://github.com/<owner>/<repo>/blob/<headSha>/<file>#L<startLine>-L<endLine>
```

Comment template:

```markdown
## /review — N bulgu

<!-- review:done -->

### 1. <issue.title>

**Dosya:** [<file>#L<startLine>-L<endLine>](<permalink>)
**Kategori:** <category> · **Önem:** <severity>

<issue.explanation>

> <issue.evidence>     (REVIEW.md alıntısı veya kod kanıtı — varsa)

**Öneri:** <issue.suggestion>

---

### 2. ...

---

🤖 Generated with [Claude Code](https://claude.ai/code)
```

If `N == 0`, the body is:

```markdown
## /review — temiz

<!-- review:done -->

Bu PR'da REVIEW.md kurallarına aykırı veya tespit edilebilir bir bug bulunamadı.

🤖 Generated with [Claude Code](https://claude.ai/code)
```

Post via:

```
gh pr comment <number> --body-file <tmpfile>
```

Use `--body-file` (not `--body`) to preserve markdown formatting and avoid shell-escaping issues.

---

## Hard rules for the orchestrator

- **Never edit files.** This command only reviews.
- **Only the orchestrator posts, and only in Step 8.** Spawned agents (Steps 1–5) are read-only: they return JSON and never call `gh pr comment`, `gh issue comment`, `gh pr review`, or a writing `gh api` (`-X POST/PATCH/PUT/DELETE`). If a sub-agent reports it already posted a comment, do not post again — verify the PR state and reconcile to exactly one correct comment.
- **Never post more than one comment per run.** All findings are batched into a single comment.
- **Never post without `REVIEW.md`** — abort instead. The whole pipeline relies on it for false-positive control.
- **Always use the full head SHA** in permalinks, captured at Step 1, even if the PR receives new commits during the run. The review applies to the SHA you actually read.
- **Never flag pre-existing code** the PR did not modify. The "changed lines" rule is non-negotiable for sections 3-5 of REVIEW.md.
- **Confidence threshold is 70**. Do not lower it; do not weight your own opinion against the Haiku score.
- **Do not skip Step 7.** A PR that flipped to draft or got closed mid-run must not receive a comment.
- **Agent prompts are English; the user-facing comment is Turkish.**
