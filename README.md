# Resonate

> **Kyla Hazel's portfolio fork** of [chimkenIJ/resonate](https://github.com/chimkenIJ/resonate),
> built by a three-person team at the Hacklanta hackathon (October 2026).
> The team's original README follows [below](#about-resonate).

## My role

During the hackathon I worked on:

- **Obstacle detection:** running the YOLO11s neural network on-device with Core ML and
  Apple Vision, and lowering the analysis frame rate as the phone heats up
  ([ObjectDetector.swift](Resonate/Services/Live/Vision/ObjectDetector.swift)).
- **LiDAR depth processing:** measuring obstacle distance and the terrain ahead from ARKit
  depth, filtering noisy readings so alerts only trigger for nearby objects in the
  user's path ([DepthReader.swift](Resonate/Services/Live/Vision/DepthReader.swift),
  [TerrainAnalyzer.swift](Resonate/Models/TerrainAnalyzer.swift)).
- **Depth evaluation pipeline:** a Python tool that measures distance-estimate accuracy
  with robust statistics and scene-level bootstrap intervals ([Evaluation/](Evaluation/)).
- **Map services:** Valhalla routing and Nominatim search in Docker containers
  ([server/](server/)).

I only had a Windows laptop at the event, so I wrote the iOS and server code on teammates'
Macs, and those commits appear under a teammate's account. The follow-up work below is in
my own commits.

## My follow-up work

I'm hardening the parts I worked on with tests and reproducible measurements, on Windows
and Linux.

| Area | Status | Evidence |
| --- | --- | --- |
| Reproducible depth evaluation | Done | [Commits](https://github.com/kylahazelwork-ux/Resonate/commits/feature/depth-eval-reproducible) · [README](Evaluation/README.md) · [decisions](docs/decisions.md) |
| Bootstrap and data-leakage tests | In progress | |
| YOLO thermal-throttling tests and timing | Planned | |
| LiDAR filtering regression tests | Planned | |
| Docker map-service smoke check | Planned | |

What's done in the depth evaluation so far:

- **[Fixed a silent drift bug](https://github.com/kylahazelwork-ux/Resonate/commit/5987df8):**
  the evaluation checked for exactly 23 object classes. A teammate swapped one class for
  another, so the check passed while the class list was wrong. It now checks against the
  Swift source.
- **[Matched the shipped app](https://github.com/kylahazelwork-ux/Resonate/commit/32b07ef):**
  the baseline now drops low-confidence detections the same way the app does (65% for
  people, 60% for vehicles).
- **[Added a correctness fixture](https://github.com/kylahazelwork-ux/Resonate/commit/c799868):**
  synthetic data with planted errors, so tests can check that the math comes out exactly right.
- **[One command for the whole report](https://github.com/kylahazelwork-ux/Resonate/commit/ee753a0):**
  error metrics, coverage, and 95% intervals from resampling whole scene groups.

Results on the synthetic fixture. These check the pipeline's math; **they are not
real-world accuracy**:

| Planted error | Pipeline reported |
| --- | --- |
| Baseline 25% too far | 0.2500 median relative error |
| Model 10% too far | 0.1000 |
| Model 0.2 m too near | −0.2000 m median bias |
| 1 missing prediction out of 72 | coverage 71/72, counted as a failure |

Try it (Python 3, no installs):

```sh
cd Evaluation
python -m unittest discover -s tests -v
python -m depth_eval fixture --out artifacts/fixture-report
```

**Not yet measured:** on-iPhone speed and thermal behavior, and accuracy on real recordings.
Both need a Mac with Xcode to install the app on a phone.

---

## About Resonate

Resonate is an iOS accessibility prototype for blind and low-vision users who want richer situational awareness while navigating the world.

Everyday navigation is hard when you cannot reliably tell what is in front of you, where the safest route is, or how to understand indoor spaces. Resonate brings obstacle detection, spoken guidance, vibration cues, and accessibility-aware mapping into one app to help users explore surroundings and navigate with more confidence.

The app combines obstacle detection, spoken feedback, vibration cues, and walking routes with accessibility-aware mapping so users can better understand both indoor and outdoor spaces. It is designed to supplement a cane or guide dog, not replace it. Outdoor routing focuses on Atlanta and Georgia; indoor room scanning requires a supported LiDAR iPhone.

This is an early prototype. Detection, distance estimates, and map data may be incomplete or approximate. See [Limits](#limits) before relying on the app in real-world settings.

## Quick start

If you want to try the interface without live services:

1. Clone the repository.
2. Open `Resonate.xcodeproj` in Xcode.
3. Select the **Resonate** scheme and an iPhone simulator.
4. Press **⌘R** to build and run.
5. Choose **Continue without account** and complete onboarding.

If `ResonateConfig.plist` is missing or incomplete, the app automatically runs in mock/demo mode. No API keys or backend are required for the interface demo.

## Features

- **Explore surroundings:** detect supported objects and announce distance estimates with spoken, haptic, and audio feedback.
- **Find a destination:** search for places and follow walking routes informed by available accessibility tags.
- **Scan a room:** use RoomPlan on a supported LiDAR iPhone.
- **Describe a scene:** request a camera-based description through Gemini.
- **Recognize colors:** name colors sampled from the center of the camera view.
- **Save places:** organize destinations in folders and choose feedback preferences.

These features run against simulated services in demo mode. Live services require additional setup described below.

## App flow

Sign in or continue as a guest → onboarding and preferences → home.

From home, users can choose a destination for outdoor navigation or open a tool to inspect nearby surroundings. Saved places are organized into folders for later use.

With live services configured, signed-in users store saved places and preferences in the backend; guests keep them on the phone. Choosing guest access does not by itself enable demo mode—the app configuration determines whether services are live or simulated.

## Tech stack

| Part | Implementation |
| --- | --- |
| iOS app | Swift and SwiftUI in Xcode using MVVM |
| Object detection | Apple Vision and Core ML running YOLO11s on device |
| Distance estimation | ARKit LiDAR where available; object-size estimates on non-LiDAR phones |
| Indoor scanning | Apple RoomPlan with LiDAR |
| Color recognition | AVFoundation camera sampling and on-device color naming |
| Maps and outdoor routes | MapKit, OpenStreetMap data, Nominatim search, and Valhalla walking routes |
| Feedback | ElevenLabs voice, AVSpeechSynthesizer fallback, Core Haptics, and audio cues |
| Scene descriptions | Gemini through a backend function |
| Authentication | Auth0 |
| Backend | Supabase Postgres/PostGIS and Edge Functions |

## Geographic coverage

Outdoor search, routing, and accessibility metadata are scoped to Atlanta and Georgia using OpenStreetMap data. The map server imports the Georgia extract, including tags for crossings, curb ramps, tactile paving, steps, and other accessibility features. MapKit handles the map display.

The current region checks use a Georgia bounding box, which includes small parts of neighboring states. See the [backend setup guide](docs/BACKEND_SETUP.md#2e-exact-georgia-border-optional) for loading the exact state boundary.

## Requirements

| Goal | Requirements |
| --- | --- |
| Explore the demo interface | Mac, a compatible Xcode release, and an iPhone simulator or iPhone |
| Try live camera tools | Physical iPhone running iOS 17+, camera permission, and live app configuration |
| Scan indoor rooms | Supported LiDAR iPhone |
| Run local routing services | Mac with Docker Desktop, Node.js/npm, and Python 3 |

The deployment target is iOS 17.0. Use a recent Xcode release compatible with the project's Swift syntax; the minimum iOS version does not specify the required Xcode version.

## Run the demo

1. Clone this repository and open `Resonate.xcodeproj` in Xcode.
2. Let Xcode resolve the Swift packages. If needed, use **File → Packages → Resolve Package Versions**.
3. Select the **Resonate** scheme and an iPhone simulator.
4. Press **⌘R** to build and run.
5. Choose **Continue without account**, finish onboarding, and try the home, search, route, and saved-place screens.

Without a complete `ResonateConfig.plist`, the app automatically uses mock services. No API keys or backend are needed for the demo. Locations, routes, detection, and feedback are simulated so the interface can be explored without live infrastructure.

To confirm demo mode, check the Xcode console for: `ResonateConfig.plist missing or incomplete; running on mock services.` If you have already configured live services, use a separate checkout without your local configuration file to try the demo.

### Run on an iPhone

Select your device in Xcode and set your development team under **Signing & Capabilities**, then build and run. Grant camera and location access when using the corresponding tools.

Real camera detection and color recognition require a physical device and live services. Indoor room scanning also requires supported LiDAR hardware. On phones without LiDAR, obstacle distances use object-size estimates. The simulator cannot validate physical camera accuracy, LiDAR depth, or haptic behavior.

## Configure live services

### Accounts and saved places

Follow the [backend setup guide](docs/BACKEND_SETUP.md) to configure Auth0, connect Supabase, and apply the database migrations. Then run this command from the repository root on your Mac:

```sh
cp config/ResonateConfig.example.plist Resonate/Resources/ResonateConfig.plist
```

Fill in `SupabaseURL`, `SupabaseKey`, `Auth0Domain`, `Auth0ClientID`, and `Auth0Audience`. Use the Supabase publishable or legacy anon key in the app. Keep service-role keys and third-party API secrets on the backend.

The local plist is gitignored. Missing, empty, or `YOUR_` placeholder values in required fields cause the app to use mock services. Rebuild after changing the configuration.

### Search and routing

Follow [Map server setup](docs/MAP_SERVER.md) for the Georgia OSM import, Valhalla, Nominatim, accessibility processing, and the `geocode` and `route` Edge Functions.

For local testing on your Mac, install Docker Desktop, Node.js/npm, and Python 3. Complete [account configuration](#accounts-and-saved-places) first, then create `supabase/functions/.env.local` containing:

```dotenv
VALHALLA_URL=http://host.docker.internal:8002
NOMINATIM_URL=https://nominatim.openstreetmap.org
```

Then run from the repository root:

```sh
server/scripts/dev_up.sh
```

The script starts local routing and Supabase, loads accessibility points, and updates the app's `FunctionsURL` and `FunctionsKey`. The first run downloads Georgia map data and builds routing tiles, so allow time for it to finish. Accounts and saved places still use your configured hosted Supabase project.

Rebuild the app in Xcode. For a phone, keep the Mac awake, put both devices on the same Wi‑Fi, and allow Local Network access when prompted. For a simulator, set `FunctionsURL` to `http://127.0.0.1:54321/functions/v1` if the Mac's `.local` address is unreachable.

Stop the local services with:

```sh
server/scripts/dev_down.sh
```

Local search uses public Nominatim for light personal testing. Use the self-hosted Nominatim setup in the map server guide for a deployed app.

### Voice and scene descriptions

Configure `ELEVENLABS_API_KEY` and `GEMINI_API_KEY` as Supabase function secrets, then deploy the `speak` and `describe` functions. For local functions, add the keys to the gitignored `supabase/functions/.env.local` and restart the local services. Optional settings are `ELEVENLABS_VOICE_ID` and `GEMINI_MODEL`.

Obstacle detection and color naming run on the device. A scene-description request sends a camera snapshot to the `describe` backend function for Gemini processing; ElevenLabs speech uses the `speak` function. These remote features require network access. Device speech provides a fallback when remote speech is unavailable.

### Voice assistant

The floating microphone talks to Claude through the `assistant` Edge Function. Configure `ANTHROPIC_API_KEY` as a Supabase function secret and deploy `assistant`. Keys that aren't scoped to a workspace also need `ANTHROPIC_WORKSPACE_ID`. Optional settings are `ANTHROPIC_MODEL` (default `claude-opus-5-5`) and `ANTHROPIC_EFFORT` (default `low`, for quick spoken replies). Turn the assistant on under **Settings → Voice assistant**, or say "Talk to Resonate" to Siri. Without a backend, a scripted mock handles simple requests such as "find Kroger" or "open saved places".

The YOLO Core ML model is included in `Resonate/Resources/Models/`. See the [model notes](Resonate/Resources/Models/README.md) for export instructions and licensing.

## Project structure

The app follows MVVM: views render the interface, view models handle screen state and actions, and services handle accounts, maps, vision, and feedback.

```text
Resonate/
  Views/          SwiftUI screens
  ViewModels/     Screen state and actions
  Models/         App data and navigation logic
  Services/       Protocols, live implementations, and mocks
  Components/     Shared interface components
  Theme/          Colors, typography, and spacing
  Resources/      Fonts, Core ML model, and local configuration
ResonateTests/    Unit tests
config/          Example app configuration
auth0/           Auth0 login action
supabase/        Database migrations and Edge Functions
server/          Map server containers and development scripts
docs/            Backend and map setup guides
```

## Testing

Select the **Resonate** scheme and an iPhone simulator in Xcode, then press **⌘U**. The test suite covers navigation logic, preferences, alerts, speech dispatch, indoor descriptions, terrain analysis, and color naming.

For a manual demo check, continue as a guest, complete onboarding, search for a destination, and save a place in a folder. For live testing, verify sign-in and saved-place persistence after backend setup, then check camera tools and feedback on a physical iPhone.

Passing unit tests or trying simulated screens does not establish real-world detection accuracy or route accessibility.

## Storage and feature status

With live services configured, Supabase stores signed-in user profiles, saved places, folders, and preferences. Guest saved places and preferences stay on the phone. The `saved_routes` table stores saved destinations rather than complete route histories.

OSM accessibility points are stored in Supabase, while route calculation runs on the separate Valhalla server. In the local development setup, account data remains in hosted Supabase and routing functions use the local stack.

Color recognition has a live, on-device implementation that samples the center of the camera image. Its output depends on lighting and what is inside the aiming area. Demo mode uses mock color readings, as it does for the other services.

## Limits

- **Routing:** OSM accessibility coverage varies. A suggested route may include steps, missing curb information, or unverified crossings.
- **Detection:** camera detection can miss objects. Object-size distance estimates are approximate and depend on the detected object and its visible size.
- **Hardware:** indoor room scanning needs supported LiDAR hardware; simulator behavior does not validate physical sensors or feedback.
- **Connectivity:** remote search, routing, and scene descriptions depend on available services and network access.

Resonate is a prototype that supplements a cane or guide dog; it does not replace them. This README does not claim measured navigation or detection accuracy.

## Documentation

- [Backend setup](docs/BACKEND_SETUP.md): Auth0, Supabase, app configuration, and account troubleshooting.
- [Map server setup](docs/MAP_SERVER.md): map imports, routing, geocoding, and accessibility data.
- [Model notes](Resonate/Resources/Models/README.md): YOLO export instructions and licensing.

Map data: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
