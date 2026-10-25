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

## 4. Check the parsed classes against the Swift source, not a fixed count

- **Decision:** `parse_priors` fails unless it understood every `Entry(label:` in
  `ObjectCatalog.swift`.
- **Why:** A teammate swapped `traffic light` for `backpack`; the count stayed 23,
  so the old `len(PRIORS) != 23` check passed while the class list changed.
- **Alternatives:** Update the fixed count (breaks again on the next swap); pin a
  hash of the Swift file (catches every edit, including harmless comment changes).
- **Revisit if:** The catalog moves to a format the regular expression cannot read,
  such as a JSON resource; then read that format directly.

## 5. Apply the app's per-class confidence thresholds in the baseline

- **Decision:** `baseline()` returns no estimate (`below_shipped_confidence`) for a
  detection under the app's threshold: 0.65 people, 0.6 vehicles, 0.3 traffic
  lights, 0.5 otherwise. The numbers are read from `ObjectCatalog.swift`; a test
  checks that the class groups match its `switch`.
- **Why:** The baseline must behave like the shipped app. Without this, it would
  score detections the app never reports, making the "before" numbers wrong.
- **Alternatives:** Filter detections earlier, during replay (fewer rows, but every
  method would lose those boxes, hiding detector coverage); hard-code the numbers
  (simpler, but drifts silently when the app changes).
- **Revisit if:** The app's thresholds become per-device or are loaded at run time.
