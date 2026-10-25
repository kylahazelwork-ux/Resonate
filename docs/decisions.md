# Decisions

Each entry: the decision, why, alternatives considered, and when to revisit it.

## 1. Start from the team's latest commit, not the local `main`

- **Decision:** Branch `feature/depth-eval-reproducible` from `e92f50f`.
- **Why:** The laptop's `main` was 44 commits behind. Those commits include the
  object-height changes the depth evaluation reads, so an older base would
  evaluate an outdated app.
- **Alternatives:** Local `main` (outdated); a separate branch per area from the start
  (cleaner PRs, but more branch management at this stage).
- **Revisit if:** The team moves past `e92f50f` before these changes merge; rebase then.

## 2. Commit the existing evaluation work unchanged first

- **Decision:** Commit `Evaluation/` and `docs/depth-eval-plan.md` as they were
  (`0b35869`), before any fixes.
- **Why:** Every later improvement appears as its own reviewable diff, and the
  "before" state is preserved.
- **Alternatives:** Commit together with the fixes (smaller history, but reviewers
  cannot see what changed).
- **Revisit if:** Never; history is kept as is.

## 3. Verify each area on the hardware actually available

- **Decision:** Python on Windows; Docker on Ubuntu (WSL2); Swift tests on a GitHub
  Actions macOS runner. The on-iPhone benchmark is reported as not run.
- **Why:** Only a Windows laptop and an iPhone are available. Installing on an
  iPhone requires Xcode on macOS.
- **Alternatives:** Borrowing a Mac (not available); renting a cloud Mac (cost,
  and attaching a phone is impractical).
- **Revisit if:** A Mac becomes available; then run the YOLO benchmark on the
  iPhone 15 Pro Max.
