"""Synthetic CORRECTNESS FIXTURE with known answers. Not accuracy evidence.

Builds every input a real run needs (dataset, LiDAR maps, YOLO replay, model
predictions, config) so the pipeline can be checked end to end on Windows.
Errors are planted on purpose; tests compare the pipeline's output with them.
"""
from __future__ import annotations

import struct
from pathlib import Path

from .core import CATALOG, PRIORS, SEED, digest, save
from .pipeline import assign_splits

LABEL = 'SYNTHETIC CORRECTNESS FIXTURE - NOT ACCURACY DATA'
LOCATIONS = 10            # independent scene groups -> 2 calibration, 2 selection, 6 test
FRAMES_PER_LOCATION = 6
DEPTH_SIZE = (96, 72)     # LiDAR map, sensor (landscape) orientation: width, height
PREDICTION_SIZE = (72, 96)  # model maps, upright (portrait) orientation
IMAGE_HEIGHT = 1280       # upright RGB height in pixels
FOCAL = 1000.0            # focal length in pixels
BACKGROUND_M = 4.5

# Planted answers. Tests check that the pipeline reports exactly these.
CHAIR_DEPTHS_M = (0.8, 1.2, 1.6, 2.0, 2.4, 2.8)
PERSON_DEPTHS_M = (1.5, 1.8, 2.1, 2.4, 2.7, 2.9)
BASELINE_FACTOR = 1.25    # boxes are sized so the size-prior baseline reads 25% too far
PLUS10_FACTOR = 1.10      # model "plus10" reads 10% too far
MINUS20CM_OFFSET_M = -0.2  # model "minus20cm" reads 0.2 m too near
RELATIVE_A, RELATIVE_B = 0.5, 0.05  # model "relative" outputs r with 1/z = A*r + B
LOW_CONFIDENCE_PERSON = 0.6  # below the app's 0.65 person threshold: no baseline estimate
LIGHTING = ('bright', 'indoor/ordinary', 'low-light')

MODELS = (
    {'id': 'plus10', 'kind': 'metric', 'map_key': 'plus10'},
    {'id': 'minus20cm', 'kind': 'metric', 'map_key': 'minus20cm'},
    {'id': 'relative', 'kind': 'relative', 'map_key': 'relative'},
)


def box_for(label, depth):
    """Centered box whose height makes the baseline read BASELINE_FACTOR * depth."""
    x = .05 if label == 'chair' else .55
    h = PRIORS[label] * FOCAL / (IMAGE_HEIGHT * BASELINE_FACTOR * depth)
    return [x, round((1-h)/2, 6), .35, h]


def inside(box, x, y):
    bx, by, bw, bh = box
    return bx <= x < bx+bw and by <= y < by+bh


def write_floats(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<%df' % len(values), *values))


def depth_map(objects):
    """Sensor-oriented: sensor (sx, sy) shows upright point (1 - sy, sx)."""
    w, h = DEPTH_SIZE
    values = []
    for j in range(h):
        for i in range(w):
            x, y = 1-(j+.5)/h, (i+.5)/w
            values.append(next((z for box, z in objects if inside(box, x, y)), BACKGROUND_M))
    return values


def upright_map(objects, transform):
    w, h = PREDICTION_SIZE
    return [transform(next((z for box, z in objects if inside(box, (i+.5)/w, (j+.5)/h)), BACKGROUND_M))
            for j in range(h) for i in range(w)]


def build(out_dir):
    """Write the fixture into out_dir and return the paths of its inputs."""
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new, empty fixture directory')
    frames, objects_by_frame = [], {}
    for loc in range(LOCATIONS):
        for k in range(FRAMES_PER_LOCATION):
            fid = f'L{loc}-F{k}'
            chair_z, person_z = CHAIR_DEPTHS_M[(k+loc) % 6], PERSON_DEPTHS_M[(k+2*loc) % 6]
            objects = [('chair', box_for('chair', chair_z), chair_z),
                       ('person', box_for('person', person_z), person_z)]
            objects_by_frame[fid] = objects
            painted = [(box, z) for _, box, z in objects]
            write_floats(out/'maps'/f'{fid}_depth.bin', depth_map(painted))
            (out/'maps'/f'{fid}_confidence.bin').write_bytes(bytes([2]) * (DEPTH_SIZE[0]*DEPTH_SIZE[1]))
            geometry = {'width': DEPTH_SIZE[0], 'height': DEPTH_SIZE[1], 'orientation': 'sensor'}
            frames.append({
                'frame_id': fid, 'scene_id': f'scene-L{loc}', 'session_id': f'session-L{loc}',
                'group_id': f'group-L{loc}', 'location_id': f'location-L{loc}', 'timestamp': float(k),
                'split': 'unassigned',
                'tags': {'lighting': LIGHTING[loc % 3], 'motion': 'stationary', 'environment': 'indoor',
                         'description': LABEL},
                'raw_depth': dict(geometry, path=f'maps/{fid}_depth.bin', dtype='float32_le'),
                'confidence': dict(geometry, path=f'maps/{fid}_confidence.bin', dtype='uint8'),
                'annotations': [{'object_id': f'{fid}-{label}', 'physical_id': f'L{loc}-{label}',
                                 'class': label, 'type': label, 'box': box, 'material': 'opaque',
                                 'occlusion': 'none', 'truncation': 'none', 'gt_review': 'accepted'}
                                for label, box, _ in objects],
            })
    dataset = assign_splits({'schema_version': 1, 'synthetic': True, 'label': LABEL, 'frames': frames})
    save(out/'dataset.json', dataset)

    replay = {'synthetic': True, 'label': LABEL, 'dataset_sha256': digest(out/'dataset.json'),
              'baseline_source_sha256': digest(CATALOG), 'frames': []}
    for f in dataset['frames']:
        fid = f['frame_id']
        last = fid.endswith(f'F{FRAMES_PER_LOCATION-1}')
        replay['frames'].append({
            'frame_id': fid, 'status': 'ok', 'image_height': IMAGE_HEIGHT,
            'fov_focal_pixels': FOCAL, 'intrinsics_focal_pixels': FOCAL,
            'sensor_crop': [0, 0, 1, 1], 'baseline_mode': 'exact_camera_mode',
            'detections': [{'object_id': f'{fid}-{label}', 'class': label, 'box': box,
                            'confidence': LOW_CONFIDENCE_PERSON if label == 'person' and last else .9}
                           for label, box, _ in objects_by_frame[fid]]})
    save(out/'replay.json', replay)

    # One test frame has no usable "minus20cm" prediction for its chair (NaN pixels).
    missing_frame = next(f['frame_id'] for f in dataset['frames'] if f['split'] == 'test')
    transforms = {'plus10': lambda z: z*PLUS10_FACTOR,
                  'minus20cm': lambda z: z+MINUS20CM_OFFSET_M,
                  'relative': lambda z: (1/z-RELATIVE_B)/RELATIVE_A}
    predictions = {'synthetic': True, 'label': LABEL, 'replay_sha256': digest(out/'replay.json'),
                   'missing_chair_prediction': {'frame_id': missing_frame, 'model_id': 'minus20cm'},
                   'models': {m['id']: {'source': 'synthetic transform of ground truth'} for m in MODELS},
                   'frames': {}}
    for fid, objects in objects_by_frame.items():
        predictions['frames'][fid] = {}
        for model in MODELS:
            mid = model['id']
            painted = [(box, float('nan') if (fid, mid, label) == (missing_frame, 'minus20cm', 'chair') else z)
                       for label, box, z in objects]
            write_floats(out/'predictions'/f'{fid}_{mid}.bin', upright_map(painted, transforms[mid]))
            predictions['frames'][fid][mid] = {
                'path': f'{fid}_{mid}.bin', 'width': PREDICTION_SIZE[0], 'height': PREDICTION_SIZE[1],
                'dtype': 'float32_le', 'orientation': 'upright',
                'units': 'relative_inverse' if model['kind'] == 'relative' else 'z_m'}
    save(out/'predictions'/'predictions.json', predictions)
    save(out/'config.json', {'schema_version': 1, 'seed': SEED, 'bootstrap_replicates': 10000,
                             'label': LABEL, 'models': list(MODELS)})
    return {'dataset': out/'dataset.json', 'replay': out/'replay.json',
            'predictions': out/'predictions'/'predictions.json', 'config': out/'config.json',
            'missing_chair_prediction': missing_frame}
