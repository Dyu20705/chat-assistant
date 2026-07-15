# Repository Agent Guide

## Project purpose

`Dyu20705/chat-assistant` currently contains a single-file Discord/Ollama bot. The managed roadmap proposes migrating it into Quân Sư, a transport-neutral local AI gateway for `Dyu20705/my-discord-bot`, which remains the only Discord runtime and Discord-token owner. Generic advisor chat, the Health Assistant extension, and the concrete transport remain proposals until their owning issues and human approval gates are complete.

The current `bot.py` is legacy behavior, not the target architecture. Do not treat its Discord commands, memory, attachment handling, or direct Ollama calls as the future gateway contract.

## Architecture boundaries

- `my-discord-bot` owns Discord connectivity, tokens, command registration, Discord authorization, interaction acknowledgement, cooldowns, attachment download policy, and Discord presentation.
- Under the accepted four-repository boundary, `chat-assistant` owns transport-neutral gateway orchestration, protocol envelopes, caller-context validation, capability routing, request correlation, deadlines, cancellation, back-pressure, dependency health, safe gateway errors, and public language/game assistant adapters. Issue #2 still owns the concrete transport, and generic advisor behavior requires separate approval.
- `lang-assistant` and `game-assistant` own their domain rules, prompts, model calls, private data, persistence, migrations, validation, and public application-service contracts.
- Issue #24 proposes adding `health-assistant` under the same domain-ownership rule. Until approved, health is not part of the accepted architecture. If enabled later, it must fail closed and retain stricter safety, privacy, evidence, QA, and release gates.
- Cross-repository access must use reviewed, versioned public contracts. Never import private modules, read another repository's database or profile files, parse human-oriented CLI output, assume adjacent checkout paths, or share mutable storage.
- Generic chat must never impersonate or silently replace a specialist capability. Any future approved health path must fail closed.
- Architecture decisions in `docs/ecosystem-architecture.md` remain authoritative only where they have not been superseded by an accepted ADR. Keep the document aligned with the canonical five-repository roadmap before implementation relies on it.

See `docs/repository-context.md` and `docs/issue-dependency-graph.md` for the dated Phase 0 audit and execution dependencies.

## Supported runtime

- Python 3.11, 3.12, and 3.13.
- A clean checkout must install with `python -m pip install -e ".[dev]"`.
- Default tests must not require Discord, Ollama, other repository checkouts, network access, production secrets, or private user data.
- Set `OLLAMA_DISCORD_SKIP_DOTENV=1` for validation so a developer or production `.env` file is not loaded.

## Required verification

Run the checks relevant to every change. Before a PR is marked ready, run the complete baseline unless the PR documents an exact environmental blocker:

```bash
python -m pip install -e ".[dev]"
mkdir -p .pytest_tmp
export OLLAMA_DISCORD_SKIP_DOTENV=1
export MAX_MEMORY_MESSAGES=0
export MEMORY_FILE="${PWD}/.pytest_tmp/ci-memory.json"
python -m compileall -q bot.py tests
python -c "import bot; print('import ok')"
ruff check .
pytest --cov --cov-report=term-missing
python -m pip_audit --cache-dir .pip-audit-cache --progress-spinner off --strict .
actionlint
bash -n scripts/github/sync_ai_ecosystem_issues.sh
DRY_RUN=true bash scripts/github/sync_ai_ecosystem_issues.sh > .pytest_tmp/ai-ecosystem-backlog.json
test "$(jq -r '.totals.repositories' .pytest_tmp/ai-ecosystem-backlog.json)" = "5"
test "$(jq -r '.totals.epics' .pytest_tmp/ai-ecosystem-backlog.json)" = "5"
test "$(jq -r '.totals.child_issues' .pytest_tmp/ai-ecosystem-backlog.json)" = "70"
test "$(jq -r '.totals.creates' .pytest_tmp/ai-ecosystem-backlog.json)" = "75"
git diff --check
```

The synchronizer gate requires GNU Bash and `jq`. On Windows, run that portion in WSL, a Linux container, or GitHub Actions; native Git Bash combined with Windows `jq.exe` can introduce CRLF into command substitutions. Record that as an environmental blocker instead of claiming a local pass.

Do not weaken coverage, disable lint rules, skip or delete failing tests, make CI fail-open, or claim an unavailable tool passed. Add or update tests with implementation changes and record acceptance-criterion evidence in the PR.

## Branch, commit, and PR conventions

- Start from the latest `main`. Never commit directly to `main`.
- Use one issue per branch and PR by default: `feat/<issue>-<slug>`, `fix/<issue>-<slug>`, `docs/<issue>-<slug>`, or `refactor/<issue>-<slug>`.
- Do not combine issues unless they cannot be separated safely; explain the coupling in the PR body.
- Keep commits small and intentional. Use behavior-oriented messages such as `docs: define gateway trust boundary` or `fix: reject expired attachment references`.
- Do not force-push a shared branch or modify unrelated files.
- Open a draft PR first. Include problem, rationale, solution, scope/non-goals, changed modules, tests and results, acceptance evidence, security/privacy review, compatibility/migration notes, risks, rollback, and an issue-closing reference only when the full issue is satisfied.
- Keep prompts, transcripts, chain-of-thought, agent metadata, secrets, runtime data, caches, and unnecessary generated artifacts out of commits and PR text.

## Security and privacy rules

- Never commit `.env`, tokens, credentials, private records, production data, local absolute paths, or raw user/model content.
- Validate identity and authorization before invoking capabilities; missing, malformed, expired, or unauthorized caller context fails closed.
- Exclude secrets, raw prompts/responses, health content, learner/player content, stack traces, and personal paths from normal logs and public errors.
- Treat attachment references as opaque, bounded, expiring, and gateway-owned. Reject arbitrary paths and commands; clean temporary data after success, rejection, timeout, cancellation, and recovery.
- Authentication/authorization, secret handling, privacy/retention, public protocols or schemas, breaking APIs, migrations, deployment configuration, supply-chain changes, destructive operations, cross-repository architecture boundaries, and final release gates require human approval before merge.

## Review guidelines

- Review against both the issue acceptance criteria and repository standards.
- Verify assumptions in source, tests, contracts, and current GitHub state; do not infer completion from code presence alone.
- Request an independent review after the PR is ready. Read review submissions, inline comments, unresolved threads, CI results, and failure logs.
- Validate each finding, fix the root cause, add a regression test when applicable, rerun relevant verification, and reply with evidence. Resolve a thread only after the fix is present on the branch.
- Do not merge with an unresolved valid P0/P1 finding, unexplained scope expansion, missing acceptance evidence, failing required check, or unexpected HEAD change.

## Definition of done

An issue is done only when:

- every acceptance criterion has direct evidence;
- dependencies and cross-repository contracts are complete or explicitly outside the issue's approved scope;
- relevant local verification and required GitHub checks pass on the reviewed HEAD;
- no unresolved review thread or valid P0/P1 blocker remains;
- security, privacy, compatibility, migration, documentation, and rollback consequences are addressed;
- the PR is merged without bypassing repository rules;
- the merge commit is present on `main`, post-merge CI is green, and the issue has a closing summary with PR, commit, and verification evidence.
