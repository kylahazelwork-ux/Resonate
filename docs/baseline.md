# Baseline before evaluation and verification work

Recorded 2026-10-25 on branch `feature/depth-eval-reproducible`, created from
`e92f50f` (the team's latest commit, also the tip of GitHub `main`).

## Existing features (team work, before these improvements)

Described from source code, not re-tested on a device for this baseline:
destination search and walking routes (Nominatim and Valhalla through Supabase
Edge Functions), outdoor obstacle detection (YOLO11s with LiDAR depth or
object-size distance estimates), indoor room scanning (RoomPlan), color
identification, saved places, Auth0 sign-in, ElevenLabs speech, Gemini scene
descriptions, and the Claude voice assistant.

The depth evaluation harness in `Evaluation/` and its protocol in
`docs/depth-eval-plan.md` existed before this branch and were committed unchanged
(`0b35869`). The harness had no tests, no command-line entry point, and no
sample dataset.

## Checks that ran on Windows

| Check | Result |
| --- | --- |
| `python -c "import depth_eval.core"` (Python 3.14.7) | Passes; reads 23 object classes from `ObjectCatalog.swift` |

No other checks ran. This machine has no Xcode, Swift, Docker, or Deno.

## Checks that need other hardware

| Needs | What | Plan |
| --- | --- | --- |
| macOS with Xcode | Building the app; the 19 Swift test files in `ResonateTests/` | GitHub Actions macOS runner |
| iPhone with LiDAR, installed from Xcode | Camera, LiDAR depth, YOLO speed and thermal throttling, GPS, vibration, VoiceOver | Not available; reported as not run |
| Linux with Docker | Valhalla, Nominatim, and Caddy map containers (`server/docker-compose.yml`) | Ubuntu on WSL2 |

## Differences found between the evaluation plan and the current app

- Object classes: `traffic light` was removed and `backpack` (0.5 m) added, so the
  count is still 23 and the harness's fixed-count check did not catch the change.
  `truck` changed from 3.0 m to 2.5 m.
- Detector confidence: the plan says 0.4 for every class. The app now uses 0.5 by
  default, 0.65 for people, 0.6 for vehicles, and 0.3 for traffic lights. The
  Python baseline does not apply these thresholds.
- Thermal throttling: the plan says 15/8/3 Hz. The app now uses 10/5/3 Hz
  (normal, serious, critical).
- The test table in `AGENTS.md` lists fewer test files than `ResonateTests/` contains.

## Not part of this branch

README personalization is intentionally left for the personal fork.
