# Repository Context — Phase 0 Audit

Snapshot date: 2026-07-15

## Executive summary

The canonical repository is `Dyu20705/chat-assistant` (GitHub repository ID `1296002020`) on default branch `main`. GitHub resolves the historical names `Dyu20705/ollama-discord` and `Dyu20705/ollama-assistant` to that same repository ID, so they are rename aliases, not separate systems. The local remote was updated from the redirecting `ollama-discord` URL to `https://github.com/Dyu20705/chat-assistant.git` after verifying that identity.

The current default branch at `4fbf12f376dfb6b1e4294b1316bdafc2641599c1` is a tested legacy Discord/Ollama application plus architecture documentation, CI, tests, and a five-repository backlog synchronizer. It is not yet the target Quân Sư gateway: production code remains a single `bot.py` that loads Discord configuration, opens a Discord client, registers Discord commands, owns memory/cooldowns/attachment handling, and calls Ollama directly.

There are 26 open issues and no open pull requests. The managed Quân Sư epic covers 23 child issues, while issues #17 and #24 remain open outside that epic. The authoritative architecture document still describes four repositories and the `ollama-discord` name, while the managed roadmap assumes five repositories and canonical `chat-assistant` ownership. Resolve that architecture drift before feature implementation.

## Repository baseline

| Item | Evidence | Current state |
| --- | --- | --- |
| Canonical repository | GitHub repository ID `1296002020` | `Dyu20705/chat-assistant` |
| Default branch | GitHub repository metadata | `main` |
| Local branch at discovery | `git status --short --branch` | `main`, initially 9 commits behind; fast-forwarded to `origin/main` |
| Local remote at discovery | `.git/config`, `git remote -v` | Legacy `Dyu20705/ollama-discord`; corrected to canonical URL |
| Current baseline SHA | `git rev-parse origin/main` | `4fbf12f376dfb6b1e4294b1316bdafc2641599c1` |
| Worktree after refresh | `git status --short --branch` | Current with `origin/main`; pre-existing untracked documentation was preserved and excluded |
| Open GitHub work | GitHub issue/PR queries | 26 open issues; 0 open PRs |
| Current-main CI | GitHub Actions run `29395618785` | Passed on Python 3.11, 3.12, and 3.13 matrix |

Pre-existing untracked documentation was preserved and excluded from the governance branch. Because it is neither committed nor publicly linked, this audit does not use its contents as architecture, dependency, or blocking evidence.

## Current package and module boundaries

- `bot.py`: approximately 1,200 lines and the only production module. It owns environment loading, configuration helpers, prompts, persistent memory, cooldowns, an `OllamaDiscordBot` Discord client, direct Ollama HTTP calls, context collection, Discord command handlers, and process startup.
- `tests/`: 54 offline helper/command tests for the legacy module. Tests use monkeypatching and fakes; they do not require live Discord or Ollama.
- `pyproject.toml`: package name remains `ollama-discord`; supports Python `>=3.11,<3.14`; runtime dependencies are `aiohttp`, `discord.py`, and `python-dotenv`.
- `.github/workflows/ci.yml`: compile/import, Ruff, pytest coverage, workflow validation, backlog dry-run, and project dependency audit across Python 3.11-3.13.
- `docs/ecosystem-architecture.md`: authoritative four-repository ownership record from closed issue #1, now incomplete for the health capability and canonical rename.
- `scripts/github/`: reviewable manifest and synchronizer for 75 managed issues across five repositories. The persistent workflow can mutate issues only with explicit `apply`, exact confirmation text, and `AI_ECOSYSTEM_PAT`.

This is a single-package repository, not a monorepo. There is no `src/` package layout, gateway server, public protocol model, capability registry, specialist adapter, or deployment artifact on `main`.

## Architecture and ownership baseline

The accepted four-repository dependency direction remains:

```text
Discord user
  -> my-discord-bot
  -> chat-assistant
  -> lang-assistant | game-assistant
  -> local Ollama where approved
```

- `my-discord-bot` is the only Discord runtime and token owner.
- `chat-assistant` owns transport-neutral gateway orchestration; issue #2 still owns the concrete transport, and generic advisor behavior requires separate approval.
- `lang-assistant` and `game-assistant` own domain policy, prompts, model use, private data, persistence, and public contracts.
- Cross-repository database access, private imports, human-output parsing, fixed checkout paths, arbitrary command execution, and generic fallback for specialist failures are forbidden.
- The managed roadmap proposes extending this direction to `health-assistant` through issue #24 and selecting local HTTP/JSON through issue #2. Neither proposal is accepted by this audit. If health is approved later, it must remain disabled until its stricter safety, privacy, evidence, QA, and release gates pass.

Issue #24 must update the four-repository architecture record before issue #2 finalizes topology for the five-repository system. Issues #2, #3, and #4 are human-approval gates because they change cross-repository architecture, public contracts, identity, privacy, and retention.

## GitHub governance and recent history

The effective repository ruleset prevents branch deletion and non-fast-forward updates and requires pull requests. It requests CODEOWNER review but requires zero approving reviews, does not require the last pusher's approval, does not require review-thread resolution, and does not require status checks. The project workflow must therefore enforce the stronger merge gate documented in `AGENTS.md`; the platform currently does not enforce it fully.

Recent architecture-affecting pull requests:

- PR #22 merged `docs/ecosystem-architecture.md` and closed issue #1. It required a repair loop after the branch and repository-state claims became stale.
- PR #25 added the five-repository managed backlog and canonical `chat-assistant` roadmap.
- PR #27 added the manually dispatched sync workflow.
- PR #28 applied the backlog once and created/updated the GitHub issues.
- PR #34 removed the temporary one-shot workflow while preserving the guarded reusable sync workflow.

PR CI passed on the reviewed heads, and current-main CI is green. However, automated review comments on recent PRs report reviewer quota exhaustion; PRs #25, #27, #28, and #34 have no substantive independent review evidence. Future issue work must not treat those comments as an approval.

## Baseline verification

The required local baseline was run on Python 3.11.9 after refreshing `main`. Validation mirrored CI with `OLLAMA_DISCORD_SKIP_DOTENV=1`, `MAX_MEMORY_MESSAGES=0`, and `MEMORY_FILE` redirected under `.pytest_tmp` so it could not load developer configuration or persistent memory:

| Check | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed after allowing build-dependency resolution |
| `OLLAMA_DISCORD_SKIP_DOTENV=1 python -m compileall -q bot.py tests` | Passed |
| `OLLAMA_DISCORD_SKIP_DOTENV=1 python -c "import bot; print('import ok')"` | Passed; emitted only optional Discord voice dependency warnings |
| `ruff check .` | Passed |
| `pytest --cov --cov-report=term-missing` | 54 passed; 76.64% branch-aware coverage; 65% threshold |
| `python -m pip_audit --cache-dir .pip-audit-cache --progress-spinner off --strict .` | Passed |
| `actionlint` | Passed for all workflow files |
| Synchronizer syntax | Passed locally with GNU Bash |
| Mutation-free synchronizer dry-run/count assertions | Linux CI is authoritative; native Windows `jq.exe` adds CRLF to Bash command substitutions, so the local dry-run is recorded as environmentally blocked rather than passed |
| `git diff --check` | Passed |

Local validation covers Python 3.11; GitHub Actions supplies Python 3.12 and 3.13 evidence.

## Stale, duplicate, partial, and superseded findings

| Finding | Classification | Required action |
| --- | --- | --- |
| README heading, package name, architecture prose, and many issue links use `ollama-discord` | Stale rename reference; links redirect safely | Migrate names when the affected issue owns compatibility and packaging; do not rename blindly in unrelated PRs |
| `my-discord-bot` issue #56 also refers to `ollama-assistant` | Stale intermediate rename | Refine the cross-repository issue after canonical topology is accepted |
| `docs/ecosystem-architecture.md` defines four repositories and omits Health Assistant | Superseded scope, not a duplicate | Complete issue #24 before issue #2 is accepted |
| Issue #5 asks for project/test foundations already partly present | Partially implemented, target behavior absent | Refine acceptance evidence around package migration and removal of Discord ownership; do not close |
| Issue #9 has a direct Ollama client in legacy `bot.py` | Partially implemented in the wrong boundary | Replace with a Discord-independent provider adapter; legacy code is not acceptance evidence |
| Issue #10 has CI, tests, coverage, lint, audit, and actionlint | Partially implemented | Retain for package entry points, typing/format/secret policy as approved, protocol schemas, and success/error fixtures |
| Issue #17 repeats structured logging/dependency-health/operations concerns from #6, #9, and #20 but retains unique metrics, tracing, bounded-cardinality, and audit-event scope | Partially duplicate and orphaned; no exact duplicate issue was found | Trim duplicated scope, preserve the unique observability acceptance criteria, and add the refined issue to the managed roadmap |
| Issue #24 is not a child of managed epic #33 and remains on an older milestone | Orphaned active architecture work | Add it to the managed roadmap or explicitly supersede/close it with evidence |
| Issues #2, #5, #6, #9, and #10 carry combinations of `ready-for-agent` with design/blocked labels | Contradictory workflow state | Normalize labels after dependency refinement |
| Issues #18-#21 and #31-#32 omit material dependencies in their managed blocks | Incomplete dependency metadata | Update issue dependencies before implementation/release work |
| Epic #33 is self-linked in its related-epic list | Harmless synchronizer artifact | Exclude or render the current epic separately in a future synchronizer maintenance change |

No open PR overlaps implementation scope. No feature issue is authorized to start until this context and the dependency graph are merged, issue #24 reconciles the five-repository architecture, and the selected issue has verifiable acceptance criteria.
