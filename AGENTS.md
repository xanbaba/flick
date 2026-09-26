# AGENTS.md

Operating instructions for any AI agent working in this repository.

`ARCHITECTURE.md` is the specification — **what** to build. This file is the protocol — **how** to work. Where they conflict, `ARCHITECTURE.md` wins on design and this file wins on process.

Read both fully before your first edit.

---

## 1. Context

A 36-hour hackathon build. Four humans and their agents work the same repository in parallel. Two constraints follow from that and they shape everything below:

1. **Merge conflicts are the enemy.** Stay inside your assigned paths (§3). If you need something outside them, ask rather than edit.
2. **The repository is the only backup.** Laptops get closed, processes get killed, people fall asleep mid-refactor. Uncommitted work is work that does not exist.

---

## 2. Non-negotiables

Violating any of these is a defect regardless of whether tests pass.

1. **Never commit secrets.** No API keys, tokens, `.env` files, recorded sessions or personal data. If you generate a credential, write it to `.env` and add the *name* to `.env.example` with an empty value.
2. **Never fabricate data.** No mock API responses presented as real, no hardcoded classification results, no placeholder numbers that look like measurements. If something cannot be computed, raise or return `None` — do not invent a plausible value.
3. **Never disable or skip a failing test to get green.** Fix the code or fix the test with a commit message explaining why the test was wrong.
4. **Never weaken the demo-integrity rules** in `ARCHITECTURE.md` §2.5. No hidden manual triggering of classifications. Every non-production input adapter shows its badge.
5. **Never put blocking work in the sensor loop.** No network calls, no model loading, no disk I/O beyond the ring buffer.
6. **Never let telemetry block the pipeline.** `emit()` is fire-and-forget with a bounded queue that drops on overflow.
7. **Never hardcode a stimulus frequency, window length or sub-band edge** outside `config.yaml`. They come from the active profile at runtime.
8. **Never invent an API.** If you are unsure whether a library method exists or what it returns, check the installed package or the docs. A confidently wrong call signature costs more than asking.
9. **Never `git push --force` to a shared branch.** See §6.5.
10. **Never change `shared/schemas.py` unilaterally.** It is the contract every process depends on. See §4.

---

## 3. Ownership and boundaries

| Owner | Paths |
|---|---|
| Dev A | `shared/`, `inputs/`, `backend/app/`, `backend/providers/`, `config.yaml`, `run.sh` |
| Dev B | `sensor/`, `stimulus/`, `scripts/check_stimulus.py`, `scripts/run_calibration.py` |
| Dev C | `frontend/` |
| Dev D | `backend/app/services/{graph,retrieval,generation,extraction,partner,onboarding,speller}.py`, `backend/prompts/`, `backend/data/` |
| Shared, coordinate first | `shared/schemas.py`, `config.yaml`, `pyproject.toml`, `migrations/` |

**If a task requires editing outside your paths:** stop, state exactly which file and why, and wait. Do not "just make it work" in someone else's module. A five-minute wait beats a two-hour merge conflict at hour 30.

---

## 4. The contract-first rule

`shared/schemas.py` and `config.yaml` are frozen interfaces. Every process, the frontend and the tests all depend on them.

To change either:

1. State the change and why, in the chat, before editing
2. Wait for explicit confirmation
3. Make the change in **its own commit**, touching nothing else
4. Update `frontend/src/lib/types.ts` in the same commit — the hand-mirrored TypeScript types must never drift from the pydantic models
5. Update `ARCHITECTURE.md` §5 or §6 in the same commit

Adding an optional field with a default is low-risk and still follows this process. Renaming or removing a field breaks other people's running code.

---

## 5. Definition of done

A task is done when **all** of these hold. Not four of five.

- [ ] The code does what the task asked, and nothing else
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `pytest` passes — the whole suite, not just your new test
- [ ] New behaviour has a test; fixed bugs have a regression test
- [ ] It runs: you actually executed the thing, you did not just reason that it should work
- [ ] No secrets, no `print()` debugging left behind, no commented-out code
- [ ] Committed with a message that follows §6.2
- [ ] If a contract changed, §4 was followed

**"It should work" is not done.** Run it.

---

## 6. Git

Git is the team's coordination mechanism and its only backup. Treat it with the same rigour as the code.

### 6.1 Branching

Trunk-based with short-lived branches. `main` always runs.

```
main                     always working; every commit runs
  feat/input-keyboard    one feature, merged within a few hours
  fix/psd-scaling
  chore/uv-lock
```

Branch names: `<type>/<short-kebab-description>`. Types match the commit types in §6.2.

Create a branch for anything that will take more than one commit. Commit directly to `main` only for a single, self-contained, tested change during the early scaffolding hours.

**Branches live hours, not days.** A branch that cannot merge within half a day is a task that was scoped too large.

### 6.2 Commit messages

[Conventional Commits](https://www.conventionalcommits.org). Non-negotiable format:

```
<type>(<scope>): <subject>

<body — WHY, not what>

<footer — refs, breaking changes>
```

**Types:** `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `build`, `revert`

**Scopes:** `sensor`, `stimulus`, `inputs`, `backend`, `frontend`, `graph`, `llm`, `voice`, `telemetry`, `schemas`, `config`, `ci`

**Subject:** imperative mood, lower case, no trailing period, under 72 characters. "add", not "added" or "adds".

**Body:** explain *why*. The diff already shows what. Wrap at 72 columns. Include the reasoning a reviewer would otherwise have to reconstruct.

Good:

```
fix(sensor): reject windows arriving before stim.profile

The classifier was scoring against default frequencies for the first
few hundred ms after startup, producing spurious selections that the
orchestrator then acted on. P1 now refuses to classify until it has
received a profile, and reports configured=false in SensorStatus.

Refs ARCHITECTURE.md DSP-6
```

Bad:

```
fixed bug
update sensor.py
WIP
various changes
```

If your subject line needs "and", you are making two commits.

### 6.3 Atomic commits

One logical change per commit. A commit should be revertible without taking unrelated work with it.

- **Never `git add .` or `git add -A`.** Stage deliberately: `git add <path>`, or `git add -p` to stage hunks. Blind staging is how `.env` files and 400 MB of session recordings enter history.
- Run `git diff --staged` before every commit. Read it. If something in there surprises you, unstage it.
- Separate refactors from behaviour changes. A commit that both moves code and changes it is unreviewable.
- Formatting-only changes go in their own `chore(format):` commit.

### 6.4 Commit cadence

**Commit every 20–30 minutes, and always before:**

- switching tasks
- starting anything risky
- stepping away from the machine
- attempting a fix you are unsure about

A hackathon repository should show a dense, steady commit history. Sparse commits with huge diffs mean lost work when something goes wrong at hour 28.

If the work is not yet coherent but you need a save point, use a branch and squash before merging — do not leave `WIP` on `main`.

### 6.5 Pushing and merging

```bash
git fetch origin
git rebase origin/main        # keep history linear
# resolve conflicts, re-run tests
git push origin <branch>
```

- **Rebase your feature branch onto `main`** before merging. Do not merge `main` into your branch repeatedly; it produces unreadable history.
- **Never rebase or force-push a branch someone else has checked out.** If you must rewrite a shared branch, announce it first and use `--force-with-lease`, never bare `--force`.
- Merge to `main` with `--no-ff` so the feature boundary stays visible in history.
- **Run the full test suite after rebasing, before pushing.** A rebase that compiles is not a rebase that works.

### 6.6 Conflict protocol

1. **Do not guess** at someone else's intent. If the conflict is in their file, ask them.
2. Resolve semantically, not textually. Understand both sides before choosing.
3. After resolving, run the full suite. A conflict resolution that merely compiles has a good chance of being wrong.
4. If a conflict is large and unclear, `git rebase --abort` and coordinate. Aborting is free; a bad merge is not.

### 6.7 Recovery

Nothing is lost if it was ever committed.

| Situation | Command |
|---|---|
| Need to switch tasks with dirty tree | `git stash push -m "why"` then `git stash pop` |
| Committed too early | `git commit --amend` (**only if not pushed**) |
| Wrong commit on `main`, not pushed | `git reset --soft HEAD~1` (keeps changes staged) |
| Need to undo a pushed commit | `git revert <sha>` — never rewrite pushed history |
| "I destroyed everything" | `git reflog`, find the good SHA, `git reset --hard <sha>` |
| Want one commit from another branch | `git cherry-pick <sha>` |

**Before any `git reset --hard`, run `git stash push -u` first.** It costs two seconds and it is the difference between a scare and a loss.

### 6.8 Tags

Mark states you may need to return to under pressure:

```bash
git tag -a checkpoint-1 -m "synthetic end-to-end working"
git tag -a checkpoint-2 -m "real EEG + LLM + voice, full turn"
git tag -a demo-freeze  -m "state demoed to judges"
git push --tags
```

`demo-freeze` is the most important tag in the repository. After it exists, `main` is frozen: bug fixes only, each one individually verified. **Never refactor after the freeze.**

### 6.9 `.gitignore`

Must be committed in the first commit, before anything else exists:

```
.env
.env.*
!.env.example
__pycache__/
*.pyc
.venv/
node_modules/
dist/
data/sessions/
data/kuzu/
data/audio_cache/
data/calibration/
models/
*.npz
*.wav
*.mp3
.DS_Store
.pytest_cache/
.ruff_cache/
```

If a secret is ever committed, **assume it is compromised**: rotate the key immediately, then clean history. Rotating is fast; history surgery is not, and the key is public the moment it is pushed.

---

## 7. Working method

### 7.1 Before writing code

1. Read the relevant `ARCHITECTURE.md` section. Do not infer the design from surrounding code.
2. Check whether it already exists. This repository has a lot of small modules.
3. If the task is ambiguous, **state your interpretation and proceed** — do not stall waiting for clarification on a minor point. Flag the assumption in the commit body.
4. If the task conflicts with `ARCHITECTURE.md`, stop and say so. Do not silently implement something else.

### 7.2 While writing

- Follow the existing style of the file you are in.
- Type-annotate every function signature. Python 3.11 syntax: `list[str]`, `str | None`.
- Errors are raised or returned, never swallowed. `except Exception: pass` is a defect.
- Log with `structlog`, never `print()`.
- Read constants from config. If you need a new one, add it to `config.yaml` **and** to `ARCHITECTURE.md` §5.
- Prefer boring code. This is a 36-hour build; clever code you cannot debug at hour 30 is a liability.

### 7.3 After writing

Run it. Then run the tests. Then read your own diff before committing.

If you cannot run it because hardware is missing, use the substitutes that exist for exactly this reason — `input.adapter: keyboard`, `mode.source: synthetic`, empty `.env` for offline providers. **"Cannot test without hardware" is almost never true in this repository.**

### 7.4 When blocked

State plainly: what you tried, what happened, what you think is wrong, what you need. Do not produce a plausible-looking non-solution to appear productive.

**Do not spend more than 20 minutes stuck on one thing without saying so.** In a 36-hour build, 20 minutes is 1% of the total.

---

## 8. Testing

- `pytest`, plain functions, no class hierarchies
- Test the contract, not the implementation
- Every bug fix gets a regression test in the same commit
- No network calls in tests. Providers are stubbed.
- Fast: the full suite should run in under 30 seconds. A suite nobody runs is worthless.

Priority order when time is short:

1. `tests/test_schemas.py` — the contract everything depends on
2. `tests/test_fbcca.py`, `tests/test_profiles.py` — the classifier must actually classify
3. `tests/test_telemetry.py` — proves telemetry cannot stall the pipeline
4. `tests/test_decision.py` — proves the idle state is real
5. Everything else

---

## 9. Dependencies

- Python: `uv add <pkg>`, commit `pyproject.toml` and `uv.lock` together in one `build(deps):` commit
- Frontend: `npm install <pkg>`, commit `package.json` and `package-lock.json` together
- **Never add a dependency that requires CUDA** (`ARCHITECTURE.md` SW-9). The stack is CPU-only and portable between machines, and that property is load-bearing.
- Before adding anything, ask whether the standard library or an existing dependency covers it. Each new package is another thing that can fail to install on the demo machine at hour 30.

---

## 10. Anti-patterns

Seen often in agentic work on this kind of project. All are defects here.

| Anti-pattern | Why it is wrong |
|---|---|
| Implementing something adjacent to what was asked | Wastes time and creates merge surface |
| Adding features nobody requested | Same, plus it inflates the diff |
| "Improving" code outside the task scope | Turns a reviewable diff into an unreviewable one |
| Stubbing a function and reporting it complete | Someone builds on a lie |
| Catching exceptions to make an error disappear | Moves the failure somewhere harder to find |
| Writing a test that asserts what the code does | Tests the bug as well as the feature |
| Committing everything with `git add .` | How secrets and 400 MB artifacts get committed |
| `git commit -m "fixes"` | Useless at hour 30 when you are bisecting |
| Refactoring after `demo-freeze` | The highest-risk, lowest-reward act available |
| Claiming something works without running it | The most expensive lie in the repository |

---

## 11. Quick reference

```bash
# setup
uv sync
cp .env.example .env
cd frontend && npm install && cd ..

# run everything
./run.sh

# run individually
uv run python -m sensor.main
uv run python -m stimulus.main
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev

# develop with no hardware at all
#   config.yaml: input.adapter: keyboard, mode.source: synthetic

# checks
ruff check . && ruff format --check . && pytest

# commit
git add -p
git diff --staged
git commit
```

---

## 12. The one rule

**If you are about to write something you have not run, stop and run it.**

Almost every expensive failure in a build like this traces back to code that was reasoned about but never executed.
