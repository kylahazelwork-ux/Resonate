# Camera depth evaluation — proposed protocol

Status: Phase 1 inspected; Phase 2 proposed, awaiting owner confirmation. No accuracy experiment has run. Prepared 2026-10-10 against commit `234bc57c00cc5e1027ce412f130fcd549519a98c`. Working tree was clean at inspection. The earlier interrupted pull is not assumed successful.

## Scope and order

1. Review the current implementation and approve this protocol and decision criteria.
2. Build isolated capture, replay, and analysis tools under `Evaluation/`; leave production sources, alert behavior, LiDAR behavior, and the Xcode project unchanged.
3. Validate geometry, baseline parity, and a small real capture; freeze configurations using tuning data only.
4. Run the held-out experiment and write `docs/depth-eval-results.md`, beginning with Yes / No / Inconclusive.

No model output will enter alerts. Ask before large dependency installation, any model download exceeding approximately 500 MB, or build-setting changes. A separate capture app will require a Mac, Xcode, signing, and a LiDAR phone; approve its project setup separately before changing build settings. Do not create an apparent results report from synthetic smoke tests.

## Phase 1: repository findings

These are source-inspection findings, not device measurements. Executed checks: Git status/revision, file inventory, source reads, and embedded model string inspection. No iOS build, Swift tests, model inference, camera capture, or accuracy measurements ran on this Windows host. No applicable AGENTS.md was found in the repository or immediate parent.

### Platform and build

- `Resonate.xcodeproj/project.pbxproj`: iOS 17 minimum, app and `ResonateTests` targets, Swift language mode 5.0, approachable concurrency and MainActor default isolation. Recent Swift compiler features mean language mode is not the required compiler version. SwiftUI/MVVM app, Apple Vision/Core ML, ARKit, AVFoundation, RoomPlan.
- Swift Package Manager: Auth0 (minimum 3.1.0), Supabase (minimum 2.55.3); resolved dependencies in `Resonate.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved`. Backend code and scripts also use TypeScript/SQL/shell; they are outside this experiment.
- `Resonate/Services/AppServices.swift`, `live(config:)`: chooses LiDAR when supported, camera-only otherwise. `makeDefault()` uses mocks when configuration is missing/incomplete. Capture must not accidentally use this mock-service fallback.

### Frame flow and depth

`Resonate/Services/Live/Vision/ObstacleDetectionServices.swift`:

- `LiDARFrameProcessor.session(_:didUpdate:)` reads `ARFrame.capturedImage`, runs YOLO with `.right` orientation, uses `camera.intrinsics[0][0]` as upright vertical focal length and landscape image width as upright height. Prefers `smoothedSceneDepth`, falling back to `sceneDepth`. `LiDARObstacleDetectionService.frames()` requests `.smoothedSceneDepth` on an ARWorldTrackingConfiguration.
- `CameraObstacleDetectionService.configureIfNeeded()` selects the back wide camera, requests 1280x720 BGRA, and discards late frames. Focal length is fixed at configuration time: `640 / tan(activeFormat.videoFieldOfView * pi / 360)`. Processor default is 1400 pixels, normally overwritten. No per-frame camera intrinsics are read on this path.
- `CameraFrameProcessor.captureOutput` applies `.right`, uses actual pixel-buffer width as upright image height, and passes no depth to `FrameAnalysis.objects`.
- `FrameAnalysis.analysisInterval` in `ObjectDetector.swift` targets 15 Hz normally, 8 Hz when serious thermal state, 3 Hz when critical. This is throttling, not measured throughput.
- `FrameRelay.emit` feeds the AsyncStream. Snapshot JPEGs are upright, at most 1024 pixels, quality 0.7, on demand; they do not constitute synchronized depth recordings.

`Resonate/Services/Live/Vision/DepthReader.swift`, `read`, `depth`, `distance(in:)`, `terrainSamples`:

- Locks depth/confidence buffers with their row strides. Accepts medium/high confidence when a confidence map exists and depths in 0.2–5.5 m.
- Box distance is the 25th percentile of sampled depths in the central 50% of box width and height, minimum six samples. Portrait-to-sensor mapping is `(x,y) -> (y,1-x)`.
- Terrain samples are unprojected using intrinsics scaled to depth dimensions and the AR camera transform. `TerrainAnalyzer` detects steps, drop-offs, and generic obstacles. `FrameAnalysis.merge` suppresses a generic obstacle near a named central detection (distance difference <0.8 m).
- Frame-wide `depthSource` can be `.lidar` even when individual objects fall back to size estimates. It is not sufficient provenance for evaluation.

### YOLO and baseline

`Resonate/Resources/Models/README.md` documents YOLO11s, COCO 80 classes, Core ML export `nms=True imgsz=640 half=True`. Bundled artifact: `Resonate/Resources/Models/YOLO11s.mlpackage`. Embedded strings show confidence default 0.25 and IoU default 0.7; confirm actual Core ML feature descriptions/NMS configuration on macOS before replay rather than treating string inspection as execution proof. Export tooling is not fully pinned in the README.

`ObjectDetector.init` loads compiled YOLO11s with `.all` compute units. `detect(in:orientation:)` uses Vision `.scaleFill`, expects `VNRecognizedObjectObservation`, takes the top label with confidence >=0.4, converts normalized bottom-left boxes to normalized top-left upright boxes. Load/inference failure returns an empty detection list (load failure is logged). Replay must distinguish execution failure from a successful frame with no objects.

`Resonate/Models/ObjectCatalog.swift`, `entry(for:)`, retains these 23 COCO classes. All other COCO detections are ignored by `FrameAnalysis.objects`:

| Class | Assumed full height (m) | Class | Assumed full height (m) |
|---|---:|---|---:|
| person | 1.7 | bicycle | 1.0 |
| car | 1.5 | motorcycle | 1.1 |
| bus | 3.0 | truck | 3.0 |
| train | 3.5 | traffic light | 0.9 |
| stop sign | 0.75 | fire hydrant | 0.7 |
| parking meter | 1.4 | bench | 0.8 |
| potted plant | 0.8 | dog | 0.5 |
| cat | 0.3 | suitcase | 0.6 |
| skateboard | 0.15 | chair | 0.9 |
| couch | 0.85 | dining table | 0.75 |
| bed | 0.6 | toilet | 0.75 |
| refrigerator | 1.7 | | |

`ObjectCatalog.estimatedDistance`: `d = typicalHeight * focalLengthPixels / boxHeightPixels`. Returns nil if touchesEdge, pixel height <12, or prior height <0.3. `FrameAnalysis.objects` sets touchesEdge when box.minY <0.01 or box.maxY >0.99; horizontal clipping is not checked. Pixel height = normalized box height times upright image height. LiDAR is used first if available; the evaluation baseline must explicitly disable that fallback input.

No temporal distance smoothing, tracking, distance cap, or calibrated uncertainty exists in this estimator. Size variability, crouching, tilt, occlusion, orientation, and background-containing boxes can bias it; these are inferred limitations, not measured failures. A short visible box can dangerously overestimate distance. Skateboard estimates are always nil because its prior is below 0.3 m. Camera-only focal calibration assumes the requested 1280-pixel width; actual format/crop differences need recording. `Detection.swift` mentions a depth model in a comment, but no monocular depth model is integrated here.

### Alert consumers and reusable material

- `Resonate/ViewModels/WalkViewModel.swift`, `watchObstacles()` -> `Resonate/Models/Alerts.swift`, `ObstacleAlertComposer.compose(from:)`: ignores unknown distances and distances >6 m; excludes walls/doors. Priority combines range, direction and hazard category. Stop threshold is <=1.5 m (stairs/drop-offs <=2 m). Distance appears in speech fragments.
- `Resonate/Services/Feedback/FeedbackCenter.swift`, `deliver`: preferences control voice/haptics/tones; repeats suppressed for six seconds unless urgency increases. This is alert deduplication, not distance smoothing.
- Indoor path is separate: `RoomScanService` / RoomPlan -> `Resonate/Models/IndoorComposer.swift`, `compose`/`place`/`alert` -> `IndoorScanViewModel.run` -> feedback. Distances are from room geometry. Leave it unchanged.
- `ResonateTests/TerrainAnalyzerTests.swift` includes `ObjectCatalogTests.estimatesDistanceFromApparentSize`, mapping, merge and terrain tests. `AlertTests.swift`, `IndoorComposerTests.swift`, `SpeechPhrasesTests.swift`, `SpeechDispatchTests.swift` protect alert wording/behavior. Existing tests are not an accuracy dataset.
- `Resonate/Services/Log.swift`: OSLog vision category; no persistent per-frame depth evaluation logger found. `Mocks/SampleData.swift` and mock vision services contain simulated data. Design PNGs are UI screenshots, not camera truth. No reusable RGB/LiDAR/tape dataset found in the inventory.

## Ground truth and coordinate contract

Capture RGB, raw `sceneDepth`, confidence, intrinsics, camera transform, image/depth dimensions, ARFrame timestamp and tracking state from the SAME ARFrame. Save smoothed depth separately as a sensitivity analysis, not primary truth (temporal smoothing can lag walking scenes). Copy buffers before returning from callback; strip row padding with explicit dimensions/strides. Preserve original sensor pixels losslessly and store the RGB conversion/color-space settings. Record lens, device, OS, camera format/FOV, exposure, ISO, orientation, frame drops, and monotonic timestamps. Never pair separate callbacks by nearest wall-clock time silently.

Use upright portrait normalized top-left coordinates throughout the object CSV. Store exact image rotations, resize/crop transforms and K. Check RGB/depth alignment with static planar targets and object boundaries before collecting the main set. Candidate maps must be restored to original coordinates; use the identical cached YOLO boxes for every method. Intrinsics and format metadata are allowed; LiDAR, confidence maps, AR world position, and tape labels are unavailable to candidate predictors.

Primary target is camera-axis depth Z in meters, not radial Euclidean range or distance along the floor. Validate the ARKit and each model's convention before scoring. If a source reports ray range, convert using K: `Z = range / sqrt(1 + ((u-cx)/fx)^2 + ((v-cy)/fy)^2)`. Do not apply that conversion to an existing Z map. Ground truth is a regional surface-depth proxy, not guaranteed nearest collision clearance.

For each box, fixed truth ROI is central 50% width and height. Retain finite depth 0.2–5.0 m at HIGH confidence, require >=20 pixels and >=50% valid coverage; discard values beyond `max(3 * 1.4826 * MAD, 0.05 m)` from the ROI median and repeat coverage/count check. GT is median of survivors. Store pre/post counts, MAD, source, and exclusion reason. Annotators blinded to candidate outputs flag mixed foreground/background ROIs and exclude ambiguous ones from primary truth; publish exclusion counts by stratum. Do not change the truth ROI with the candidate aggregation. Every method receives exactly the same final GT value and eligibility mask.

LiDAR is not trusted automatically on transparent, reflective, thin, very close, or >5 m surfaces. Preserve such rows as missing/unreliable truth unless independently measured. They must remain in coverage tables. For glass, a valid depth of the background is not valid obstacle truth.

Tape validation: at least 150 stationary object observations, >=30 per distance band, >=5 physical scenes per band; include at least 30 reflective/glass or thin targets. With stationary phone and object, measure from the camera lens reference plane to the visible surface sampled by the ROI, record three readings, target point, camera pose/alignment and estimated measurement error. For off-axis targets measure ray direction and convert to Z; simpler primary setup uses a surface perpendicular to the optical axis. Do not use object height as truth. Record tape surface and LiDAR ROI separately if they are not the same surface. Proposed LiDAR validation gate: median absolute tape disagreement <=0.05 m and p90 <=0.15 m within 0.2–3 m; otherwise investigate alignment and collect again. Report disagreement in all other bands too.

For 5 m+ (collect 5–8 m), <0.2 m, glass and LiDAR-invalid cases, use independently tape-surveyed static surfaces/poses, with repeated measurement uncertainty <=max(0.05 m, 2% of depth), or mark unscorable. Walking frames there need independently surveyed camera poses; ARKit poses from a LiDAR session are not independent tape truth. This milestone may report missing walking/5 m+ coverage instead of inventing it. Never substitute a candidate or the size prior for GT.

## Methods and model shortlist

Baseline A is EXACT camera-only behavior: same class priors, rejection rules, Vision pipeline, actual box pixel heights, and `f=640/tan(FOV/2)`. Capture a configuration-matched AVFoundation FOV/format calibration for the wide lens. For the primary paired experiment use RGB mapped to that camera mode's verified 1280x720 field of view; update K consistently and run YOLO once on those images. If ARKit and AVFoundation crops/FOV cannot be matched and validated, exact camera-only replication is blocked: report it, and label ARKit-intrinsics replay as a proxy, not as shipped. Baseline B (diagnostic only) uses ARKit calibrated intrinsics on the same images. Do not replace A with B in the verdict. Hardware fidelity also requires later non-LiDAR-device replay/capture checks.

Three compact checkpoints of one architecture are proposed, not three independent architecture families:

| Candidate | Output | Published source weights | Input/preprocessing | License / deployment |
|---|---|---|---|---|
| Depth Anything V2 Small, Hypersim metric | meters; indoor-trained | 24.8M parameters, 99.2 MB | reference input size 518; aspect-preserving resize, dimensions multiples of 14; max_depth=20 | Apache-2.0 per model card; Core ML conversion to verify |
| Depth Anything V2 Small, VKITTI metric | meters; outdoor-trained | 24.8M parameters, 99.2 MB | same resize policy; max_depth=80 | Apache-2.0 per model card; Core ML conversion to verify |
| Depth Anything V2 Small, relative | relative inverse-depth-like output, NOT meters | 24.8M parameters, 99.2 MB | reference input size 518; freeze exact preprocessing for selected runtime | Apache-2.0; Apple publishes a Core ML version |

Sources accessed 2026-10-10: [architecture and relative model](https://github.com/DepthAnything/Depth-Anything-V2), [metric implementation](https://github.com/DepthAnything/Depth-Anything-V2/tree/main/metric_depth), [metric preprocessing](https://raw.githubusercontent.com/DepthAnything/Depth-Anything-V2/main/metric_depth/depth_anything_v2/dpt.py), [Hypersim weights/license](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Hypersim-Small/tree/main), [VKITTI weights/license](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-VKITTI-Small/tree/main), [relative weights/license](https://huggingface.co/depth-anything/Depth-Anything-V2-Small/tree/main), [Apple Core ML model](https://huggingface.co/apple/coreml-depth-anything-v2-small).

These sizes are published checkpoint sizes, not measured mobile memory. FP16 weight-only storage is roughly 49.6 MB by arithmetic; converted size, operator support, activation memory, latency and accuracy are unverified. Record actual fixed mobile input shape and bytes after export; do not claim a reference variable-aspect pipeline and a square mobile pipeline are identical. Conversion parity must be tested before relying on offline accuracy. No model downloaded yet.

Evaluate both metric checkpoints on BOTH environments; no test-tag switching to the better checkpoint. Choose one candidate/configuration on tuning data as the single confirmatory contender. Other test comparisons are descriptive unless multiplicity-adjusted; no post-test winner selection.

Relative scale recovery: primary realistic option is an offline fixed calibration `1/Z = a*r + b`, fitted with robust loss on tuning/calibration scenes only, equal scene weighting, a>0, fixed coefficients at runtime. No per-image normalization, fitting, GT-derived hints or test-set recalibration. Nonpositive/nonfinite inverse depth yields no estimate. This is deployable as stored constants but may fail under camera/domain shift; report that explicitly. Calibration scenes stay within the tuning split, separate from aggregation-selection scenes. No claim of zero-shot metric capability. A future ground-plane/known camera-height method is outside this first frozen comparison.

Relative oracle: separately fit positive affine inverse-depth scale/shift against each frame's valid dense GT pixels, then evaluate identical object boxes. Label every output `ORACLE_GT_FIT_NOT_DEPLOYABLE`; if insufficient valid pixels or depth variation, mark unavailable. It intentionally leaks truth to illustrate alignment potential; never include it in winner selection, paired deployment verdict, or latency claims. It is an optimistic diagnostic, not a mathematical bound on every object metric.

## Object aggregation, uncertainty, and splits

Test exactly three predicted-map aggregations: median central 50% box; 25th percentile central 50%; median central 50% width and y=50–80% of box height. Use finite positive predictions, >=20 pixels and >=50% ROI coverage. Record no-estimate reasons; do not silently clip extreme outputs to GT range. Select aggregation using tuning data only: enforce coverage/safety criteria, then minimize median relative error, ties by p90 absolute error. GT remains fixed central median for all variants.

Uncertainty signals: normalized within-ROI MAD and disagreement among the three aggregations; optional causal trailing-frame disagreement only when an RGB-only track is reliable, with motion effects reported. YOLO confidence is detection confidence, not distance confidence. Fit a mapping to probability of >50% error on calibration scenes; set abstention thresholds on selection scenes, freeze before test. Report reliability bins, Brier score, AUROC for >50% error, rank correlation with error, and risk-versus-coverage curves with scene-bootstrap intervals. Constant/uninformative signals or too few errors yield unavailable/inconclusive calibration. Always report raw and abstention-filtered estimates separately, with coverage.

Collection floor: 2,000 selected RGB frames, >=3,000 object observations, >=100 independent scene groups across >=10 locations and multiple days. Target >=2,000 supported-YOLO observations and >=1,000 manually annotated challenge observations (overlap labels allowed, rows uniquely identified). More frames may be needed to achieve usable truth and detection quotas. Do not count adjacent frames as independent trials.

Split by physical location/scene and object identity, not frames: 40% tuning, 60% held-out test, fixed seed 20261010. Keep related clips in one group. Split tuning groups equally between relative/confidence calibration and configuration selection. No imagery inspection for method tuning on test; blinded GT quality review is allowed. Freeze split manifest before inference; freeze chosen model, aggregation, calibration and thresholds before opening test results.

Minimum HELD-OUT counts (marginal strata, not a full Cartesian product):

- Each depth band [0,1), [1,2), [2,3), [3,5), [5,infinity): >=150 valid-GT observations from >=15 groups. Primary safety set is 0.2–3 m. Report 0–0.2 m separately if measurable.
- Each lighting tag bright, indoor/ordinary, low-light: >=150 observations / >=15 groups. Record environment separately; tag illuminance/exposure where available.
- Each motion tag stationary/walking and environment indoor/outdoor: >=300 observations / >=20 groups.
- Each requested type chair, person, door, pole, wall, parked car, low obstacle, glass/reflective: >=60 observations / >=10 groups; allow secondary material flags to overlap.
- Each remaining retained YOLO class: aim for >=30 / >=5 groups. Report every class, including zero count, and limit conclusions for unmet quotas. Other COCO classes: inventory all 80, report detections and ignored-class coverage; do not invent shipped priors.
- Critical intersections low-light+walking and reflective/glass+0–3 m: >=60 / >=10 groups each where independent GT is possible.

Tuning targets are at least two-thirds of the test marginal counts. Counts are planning floors, not a power calculation or sufficient evidence by themselves. Collect additional independent groups when intervals remain wide; do not repeatedly inspect the same test set until significant. Any follow-up requires a newly frozen held-out set.

Doors, poles, walls and glass have no corresponding retained YOLO class. Create a separate manual-box challenge track with human type/material/occlusion labels and independent truth. Baseline is unavailable where no shipped class exists; do not assign new priors. Its results diagnose depth quality and detector coverage, not paired superiority to baseline. For supported classes, annotate detector misses as well: distance accuracy conditional on detection cannot establish obstacle-detection recall. Match manual objects to YOLO with predeclared IoU >=0.5, one-to-one, preserving unmatched/false detections. Do not alter the common box set based on a candidate output.

## Metrics and preregistered decision criteria — approval requested

For GT g>0 and estimate p: signed error e=p-g (positive is dangerous overestimation), absolute error |e|, relative error |e|/g. Report MAE, mean absolute relative error, median/p90 absolute error, median/p90 relative error, mean/median signed bias, positive-error rate, >20% and >50% overestimation rates, and false-far crossings (g<=1.5 m but p>1.5 m). Report within +/-20% and within +/-0.5 m separately, not their union.

Failure = no estimate OR relative error >50%. Show components separately. Accuracy among available estimates must always show its denominator; within-tolerance rates and failure use all valid-GT eligible detections so abstaining cannot inflate success. Report safety overestimation on available estimates and all eligible observations, alongside coverage and missingness. Missing GT is a separate exclusion/coverage issue, not a successful estimate or an estimator failure.

Report overall, each distance band, each stratum above and critical intersections. Primary paired accuracy uses the common valid-estimate subset and must be accompanied by full-cohort failures/coverage. Use 10,000 paired scene-cluster bootstrap replicates, seed 20261010, resampling whole independent scene groups (same resample for baseline and candidate). Report 95% intervals on differences in medians, MAE, failure and safety rates; never bootstrap individual correlated frames as independent. Record effective group counts and undefined resamples. Use scene-weighted sensitivity results to expose domination by long clips.

Proposed YES, for the single tuning-selected non-oracle candidate on held-out supported detections at 0.2–3 m, only if ALL hold:

1. Paired median absolute relative error improves by >=20% relative AND >=0.03 absolute versus A; 95% bootstrap CI for (candidate median - baseline median) lies entirely below zero. Zero baseline median cannot satisfy relative improvement and is not treated as divide-by-zero success.
2. Upper 95% CI for difference in >20% overestimation rates is <=0 percentage points on common valid estimates; also <=0 on the complete eligible cohort. This intentionally strict criterion may make the pilot inconclusive.
3. Upper 95% CI for difference in catastrophic >50% overestimation and false-far crossing rates is <=0 points. No safety-band point estimate in 0–1, 1–2 or 2–3 m is worse by >2 percentage points; failed sample quotas preclude that band claim.
4. Upper 95% CI for candidate-minus-baseline full-cohort failure rate <=0; candidate estimate coverage >=baseline coverage. No abstention-based accuracy victory.
5. GT validation and primary sample/group floors pass; exact baseline replay and coordinate checks pass. Report p90 errors even when median criteria pass.

NO / baseline wins against the shortlist only when adequate valid data show that every deployable candidate either has significantly worse median error (95% CI for difference entirely >0) or significantly worse dangerous overestimation, with no countervailing candidate satisfying YES. A significant safety regression disqualifies that candidate even if its median improves. If the baseline is convincingly preferable only to one candidate, state that narrower finding.

INCONCLUSIVE for all other outcomes: wide intervals, modest improvements below the meaningful margin, missing strata/truth, failed baseline fidelity, no data, or unvalidated inference. Failing to prove improvement is not proof that baseline wins. Oracle performance cannot change the verdict.

Proposed uncertainty gate, separate from accuracy verdict: at >=80% coverage, the retained >50%-error rate must fall by >=50% relative to raw outputs with paired CI excluding no reduction; upper 95% bound on retained catastrophic overestimation <=2%. Reliability must remain useful across lighting/motion strata. Otherwise uncertainty is not established as trustworthy. Even passing this only supports a future experiment with number suppression; it does not authorize user-facing alerts or validate detector recall.

On-device feasibility is also separate: record cold start and warm median/p95 model latency, full RGB->YOLO+depth+aggregation latency, peak resident memory, model bytes, OS/device/compute units, dropped frames, battery/ambient conditions and thermal-state timeline. Run three 10-minute sessions after 50 warmups. Provisional practical targets: warm end-to-end p95 <=200 ms, peak memory <500 MB, no serious/critical thermal state in 10 minutes, and <=20% p95 slowdown between first/last minute. These are goals, not measurements. Measure on an identified mid-range non-LiDAR iPhone as well as capture phone; do not extrapolate LiDAR-phone timings as proof.

## Harness implementation contract after approval

- `Evaluation/Capture/`: standalone Swift capture source, tags UI/config and bounded asynchronous writer, no speech service. Export timestamped lossless RGB plus float32 depth, uint8 confidence, JSON metadata; explicit schema/version, buffer geometry and dropped-frame audit. Store both raw and smoothed maps, use raw for primary truth.
- `Evaluation/Replay/`: macOS Swift/Vision replay of the bundled YOLO artifact and original baseline logic; cache detections once with model/content hashes. Prefer executing shared unmodified source in an isolated runner; if a port is necessary validate parity at edge/tiny/prior thresholds and randomized cases. Record all 80 labels/model feature descriptions from the actual model.
- `Evaluation/depth/`: adapters with exact preprocessing, output units, explicit runtime/model errors, and hashes. A missing model is a run failure or explicitly unavailable method, never a silent perfect prediction.
- `Evaluation/analysis/`: per-object CSV plus frame/detection-coverage manifests, stratum tables, confidence calibration, paired cluster intervals and standalone error-vs-distance, bias and risk/coverage plots. Required CSV fields: scene/session/split/frame/object ids, timestamps, class/confidence, upright box, manual type/material/occlusion, GT/source/quality, baseline and each model estimate/uncertainty/status, aggregation, tags, run/model hashes. Preserve missing-value reasons.
- Pin interpreter, all package/transitive versions and upstream code commits after environment validation; save lockfiles. Save seeds, command lines, configuration, Git revision, dataset/split SHA-256, original and converted model SHA-256, conversion settings and hardware/runtime versions. Never use mutable `main` downloads in a scored run. No fabricated model hashes in this proposal.
- Smoke tests: synthetic geometry/orientation/stride/outlier/missing-data fixtures and baseline parity tests (clearly non-accuracy data), then 5–10 real synchronized frames through YOLO, every installed model, CSV and reports. Verify overlay alignment and units visually. A synthetic-only smoke cannot claim end-to-end real-model success. Require oracle isolation and test-split leakage checks.
- Suggested small commits: documentation protocol; capture/schema; replay/adapters; analysis/tests; measured report. Do not commit recordings/weights or unrelated user changes.

## Data collection checklist

1. Prepare LiDAR iPhone, Mac/Xcode, tripod, tape, scene-tag sheet, and an assistant for controlled walking captures. Disable production alerts in the separate capture app by having no alert wiring. Validate five stationary frames before a large session.
2. Use wide lens, portrait, no digital zoom. Record camera mode/FOV and intrinsics. For each scene assign a unique scene/session/location/object id; never reuse a physical object across split groups.
3. Stage distances near 0.5, 0.8, 1.2, 1.8, 2.3, 2.8, 3.5, 4.5, 5.5 and 7 m where the object can safely be placed. Include partial clipping, occlusion, small/large chairs, standing/seated people, short/tall instances, thin poles, low obstacles and reflective surfaces. Do not discard bad detections.
4. Across at least 100 scene groups and 10 locations, record stationary and controlled walking clips in indoor/outdoor bright, ordinary indoor and low-light settings. Aim for 20 selected frames per scene (>=2,000 total), sampling at 1 Hz for scoring; retain short higher-rate bursts for temporal uncertainty. Obtain >=3,000 annotated object observations and meet the split/stratum quotas above; capture more groups if needed.
5. Tag every clip with `lighting`, `motion`, `environment`, scene description; annotate each object with physical identity, type, material/reflectivity, occlusion, truncation and known class-size variation. Use `unknown` explicitly rather than guessing tags. Record lux if measured, exposure and ISO regardless.
6. Perform the 150 tape checks above with three readings each and a photo/diagram of the measured surface. For walking beyond LiDAR range, collect independent pose/surface measurements or mark truth unavailable. Preserve all failed LiDAR returns and annotate background-through-glass returns.
7. Export originals and manifests; verify matching ids/timestamps, dimensions, byte counts and hashes. Review RGB/depth overlays on static and moving examples. Reserve entire locations/objects for test before tuning. Do not select frames because a model looks good on them.
8. After the harness exists, run its real-frame smoke and inspect truth quality before the full run. On a Mac the existing production tests can be run by opening `Resonate.xcodeproj`, selecting Resonate and an iPhone simulator, then Product > Test. Capture/inference commands will be supplied with the implemented harness; they do not exist yet.

## Current blockers and next gate

No supplied recordings, no connected LiDAR/non-LiDAR test phone, and no local macOS/Xcode execution have been established. Windows inspection cannot verify Vision behavior or on-device performance. Baseline camera-mode fidelity is a required preflight check. These block a measured verdict, not protocol drafting. Confirm the criteria above before Phase 3 construction and before any Phase 4 scored run, as requested. No candidate is currently recommended as an accuracy winner.
