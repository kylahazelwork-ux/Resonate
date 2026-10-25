"""Validated dataset -> per-object CSV. Predictors run separately, with RGB only."""
from __future__ import annotations

import csv
import json
import math
import platform
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from .core import (CATALOG, PRIORS, SEED, VARIANTS, affine_fit, aggregate, baseline,
                   check_box, digest, finite, iou, load, map_indices, read_map,
                   save, scale_relative, truth, valid)


def validate_dataset(dataset):
    if dataset.get('schema_version') != 1:
        raise ValueError('Unsupported dataset schema')
    frames = dataset['frames']
    ids = [f['frame_id'] for f in frames]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError('Frame ids must be nonempty and unique')
    assignments = defaultdict(set)
    for f in frames:
        for key in ('scene_id', 'session_id', 'group_id', 'location_id', 'timestamp', 'tags', 'split'):
            if key not in f:
                raise ValueError(f'{f["frame_id"]}: missing {key}')
        if f['split'] not in ('calibration', 'selection', 'test', 'unassigned'):
            raise ValueError('Invalid split')
        for key in ('lighting', 'motion', 'environment', 'description'):
            if not f['tags'].get(key):
                raise ValueError(f'Missing tag {key}')
        assignments['group:'+f['group_id']].add(f['split'])
        assignments['location:'+f['location_id']].add(f['split'])
        for obj in f.get('annotations', []):
            check_box(obj['box'])
            if obj.get('physical_id'):
                assignments['object:'+obj['physical_id']].add(f['split'])
    for group, splits in assignments.items():
        if len(splits) != 1:
            raise ValueError(f'Split leakage: {group} appears in {splits}')


def assign_splits(dataset):
    """Connected locations, scene groups and object identities stay together."""
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    def union(a, b):
        parent[find(a)] = find(b)
    for f in dataset['frames']:
        g = 'group:'+f['group_id']
        union(g, 'location:'+f['location_id'])
        for o in f.get('annotations', []):
            if o.get('physical_id'):
                union(g, 'object:'+o['physical_id'])
    components = sorted({find('group:'+f['group_id']) for f in dataset['frames']})
    if len(components) < 5:
        raise ValueError('Need at least five independent location/object components for three splits')
    random.Random(SEED).shuffle(components)
    n = len(components)
    cal, sel = max(1, round(.2*n)), max(1, round(.2*n))
    assignment = {g: 'calibration' if i < cal else 'selection' if i < cal+sel else 'test'
                  for i, g in enumerate(components)}
    for f in dataset['frames']:
        f['split'] = assignment[find('group:'+f['group_id'])]
        # Clustering unit includes related scenes/locations, not arbitrary clips.
        f['group_id'] = find('group:'+f['group_id'])
    dataset['split_seed'] = SEED
    validate_dataset(dataset)
    return dataset


def frame_maps(root, f):
    depth_desc = f.get('raw_depth')
    conf_desc = f.get('confidence')
    depth = read_map(root, depth_desc) if depth_desc else None
    conf = read_map(root, conf_desc) if conf_desc else None
    if depth_desc and conf_desc:
        if any(depth_desc[k] != conf_desc[k] for k in ('width', 'height', 'orientation')):
            raise ValueError('Depth and confidence geometry mismatch')
    return depth, conf, depth_desc


def check_replay(dataset_path, replay, synthetic=False):
    if replay['dataset_sha256'] != digest(dataset_path):
        raise ValueError('Replay belongs to a different dataset/split manifest')
    if replay.get('synthetic', False) and not synthetic:
        raise ValueError('Synthetic detections cannot be used in a real run')
    if replay.get('baseline_source_sha256') != digest(CATALOG):
        raise ValueError('Baseline source changed since replay')


def joined_objects(frame, replay_frame):
    """Same YOLO boxes for all methods; manual-only track kept separate."""
    detections = replay_frame['detections']
    anns = frame.get('annotations', [])
    used_d, used_a, matching = set(), set(), {}
    edges = []
    for di, det in enumerate(detections):
        check_box(det['box'])
        for ai, ann in enumerate(anns):
            if ann.get('class') == det['class']:
                overlap = iou(det['box'], ann['box'])
                if overlap >= .5:
                    edges.append((overlap, di, ai))
    for _, di, ai in sorted(edges, reverse=True):
        if di not in used_d and ai not in used_a:
            matching[di] = ai
            used_d.add(di)
            used_a.add(ai)
    rows = []
    for di, det in enumerate(detections):
        ann = anns[matching[di]] if di in matching else {}
        rows.append((det, ann, 'yolo', 'matched' if di in matching else 'unmatched_detection'))
    # Include manual objects even if matched so the challenge set is detector-independent.
    for ai, ann in enumerate(anns):
        det = {'object_id': 'manual_'+ann['object_id'], 'class': ann.get('class', ann['type']),
               'box': ann['box'], 'confidence': None}
        rows.append((det, ann, 'manual', 'matched' if ai in used_a else 'missed_or_unsupported'))
    return rows


def fit_relative(dataset_path, replay_path, predictions_path, model_id, output):
    dataset, replay, predictions = load(dataset_path), load(replay_path), load(predictions_path)
    validate_dataset(dataset)
    check_replay(dataset_path, replay, dataset.get('synthetic', False))
    if predictions['replay_sha256'] != digest(replay_path):
        raise ValueError('Prediction/replay mismatch')
    root, pred_root = Path(dataset_path).parent, Path(predictions_path).parent
    replay_frames = {f['frame_id']: f for f in replay['frames']}
    samples, used = [], []
    for f in dataset['frames']:
        if f['split'] != 'calibration':
            continue
        r = replay_frames[f['frame_id']]
        depth, conf, dd = frame_maps(root, f)
        desc = predictions['frames'][f['frame_id']][model_id]
        values = read_map(pred_root, desc)
        if desc['orientation'] != 'upright' or desc['units'] != 'relative_inverse':
            raise ValueError('Relative maps must be raw upright inverse-depth-like output')
        for det, ann, track, _ in joined_objects(f, r):
            if track != 'yolo' or det['class'] not in PRIORS:
                continue
            g, _ = truth(depth, conf, dd, det['box'], r['sensor_crop'], ann)
            # Fit inverse-depth regional median only on calibration scenes.
            indices = list(map_indices(det['box'], desc))
            raw = [values[i] for i in indices if finite(values[i])]
            if g and len(raw) >= 20 and len(raw) >= .5*len(indices):
                from statistics import median
                samples.append((median(raw), g, f['group_id']))
                used.append(f['frame_id'])
    fit = affine_fit(samples)
    save(output, dict(fit, model_id=model_id, dataset_sha256=digest(dataset_path),
                     predictions_model=predictions['models'][model_id],
                     replay_sha256=digest(replay_path), calibration_frames=sorted(set(used)),
                     source_split='calibration', seed=SEED))


def dense_oracle(values, desc, depth, conf, dd, crop):
    """GT-leaking diagnostic only. Never callable by the RGB model adapter."""
    if depth is None or conf is None:
        return None
    dw, dh = dd['width'], dd['height']
    w, h = desc['width'], desc['height']
    cx, cy, cw, ch = crop
    samples = []
    # Fixed grid, independent of values; at most ~4k samples.
    step = max(1, math.ceil(math.sqrt(w*h/4096)))
    for y in range(0, h, step):
        for x in range(0, w, step):
            sx, sy = cx+(y+.5)/h*cw, cy+(1-(x+.5)/w)*ch
            dx, dy = min(dw-1, int(sx*dw)), min(dh-1, int(sy*dh))
            z, c = depth[dy*dw+dx], conf[dy*dw+dx]
            if c == 2 and finite(z) and .2 <= z <= 5:
                samples.append((values[y*w+x], z, 'oracle_frame'))
    try:
        return affine_fit(samples)
    except ValueError:
        return None


def evaluate(dataset_path, replay_path, predictions_path, config_path, output_dir,
             split, calibration_path=None, allow_synthetic=False):
    dataset, replay, predictions, config = map(load, (dataset_path, replay_path, predictions_path, config_path))
    validate_dataset(dataset)
    check_replay(dataset_path, replay, allow_synthetic)
    if dataset.get('synthetic', False) and not allow_synthetic:
        raise ValueError('Synthetic dataset requires --allow-synthetic')
    if predictions.get('synthetic', False) and not allow_synthetic:
        raise ValueError('Synthetic predictions require --allow-synthetic')
    if predictions['replay_sha256'] != digest(replay_path):
        raise ValueError('Prediction/replay mismatch')
    if config['seed'] != SEED:
        raise ValueError('Unexpected seed: approved plan uses 20261010')
    calibration = load(calibration_path) if calibration_path else None
    if calibration:
        if calibration['dataset_sha256'] != digest(dataset_path) or calibration['source_split'] != 'calibration':
            raise ValueError('Invalid calibration provenance')
        if calibration['replay_sha256'] != digest(replay_path):
            raise ValueError('Calibration replay mismatch')
        if calibration['predictions_model'] != predictions['models'][calibration['model_id']]:
            raise ValueError('Calibration model changed')
    root, pred_root = Path(dataset_path).parent, Path(predictions_path).parent
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new output directory; scored runs are immutable')
    out.mkdir(parents=True, exist_ok=True)
    rframes = {f['frame_id']: f for f in replay['frames']}
    rows, frame_audit = [], []
    for f in dataset['frames']:
        if f['split'] != split:
            continue
        r = rframes[f['frame_id']]
        if r.get('status') != 'ok':
            raise ValueError('YOLO inference failed: '+f['frame_id'])
        depth, confidence, dd = frame_maps(root, f)
        model_maps = {}
        for model in config['models']:
            mid = model['id']
            desc = predictions['frames'][f['frame_id']][mid]
            if desc.get('status', 'ok') != 'ok':
                raise ValueError(f'Model inference failed: {f["frame_id"]}/{mid}')
            if desc['orientation'] != 'upright':
                raise ValueError('Predicted maps must be restored to upright RGB coordinates')
            values = read_map(pred_root, desc)
            if model['kind'] == 'relative':
                if desc['units'] != 'relative_inverse':
                    raise ValueError('Relative model units mismatch')
                if not calibration or calibration['model_id'] != mid:
                    raise ValueError('Relative model requires a frozen calibration file')
                model_maps[mid] = (scale_relative(values, calibration), desc)
                oracle = dense_oracle(values, desc, depth, confidence, dd, r['sensor_crop'])
                model_maps[mid+'_ORACLE_GT_FIT_NOT_DEPLOYABLE'] = (
                    scale_relative(values, oracle) if oracle else [float('nan')]*len(values), desc)
            elif desc['units'] == 'z_m':
                model_maps[mid] = (values, desc)
            else:
                raise ValueError('Metric model must output camera-axis meters')
        objects = joined_objects(f, r)
        frame_audit.append({'frame_id': f['frame_id'], 'yolo_count': len(r['detections']),
                            'manual_count': len(f.get('annotations', [])), 'split': split,
                            'group_id': f['group_id'], 'baseline_mode': r['baseline_mode']})
        for det, ann, track, matching in objects:
            box = det['box']
            g, quality = truth(depth, confidence, dd, box, r['sensor_crop'], ann)
            # Store LiDAR/tape pair independently for validation, even when tape is chosen GT.
            lidar_ann = dict(ann)
            lidar_ann.pop('tape_z_m', None)
            lidar_g, _ = truth(depth, confidence, dd, box, r['sensor_crop'], lidar_ann)
            base, base_status = baseline(det['class'], box, r['image_height'], r.get('fov_focal_pixels'), det['confidence'])
            proxy, proxy_status = baseline(det['class'], box, r['image_height'], r['intrinsics_focal_pixels'], det['confidence'])
            if r['baseline_mode'] != 'exact_camera_mode':
                base, base_status = None, 'camera_mode_not_validated'
            if track == 'manual':
                base, base_status = None, 'manual_challenge_not_shipped'
            row = {'frame_id': f['frame_id'], 'scene_id': f['scene_id'], 'group_id': f['group_id'],
                   'session_id': f['session_id'], 'location_id': f['location_id'], 'timestamp': f['timestamp'],
                   'split': split, 'object_id': det['object_id'], 'class': det['class'],
                   'track': track, 'match_status': matching, 'confidence': det['confidence'],
                   'box': json.dumps(box), 'type': ann.get('type', 'unknown'),
                   'physical_id': ann.get('physical_id', ''), 'material': ann.get('material', 'unknown'),
                   'occlusion': ann.get('occlusion', 'unknown'), 'truncation': ann.get('truncation', 'unknown'),
                   'gt_m': g, 'gt_source': quality['source'], 'gt_status': quality['status'],
                   'gt_quality': json.dumps(quality), 'tape_z_m': ann.get('tape_z_m'),
                   'lidar_validation_m': lidar_g, 'baseline_m': base, 'baseline_status': base_status,
                   'baseline_intrinsics_proxy_m': proxy, 'proxy_status': proxy_status,
                   'baseline_mode': r['baseline_mode'], **f['tags']}
            for mid, (values, desc) in model_maps.items():
                estimates = []
                for variant in VARIANTS:
                    p, uncertainty, status = aggregate(values, desc, box, variant)
                    name = mid+'__'+variant
                    row[name+'_m'], row[name+'_uncertainty'], row[name+'_status'] = p, uncertainty, status
                    if valid(p):
                        estimates.append(p)
                from statistics import median
                disagreement = ((max(estimates)-min(estimates))/median(estimates)
                                if len(estimates) == len(VARIANTS) else None)
                for variant in VARIANTS:
                    name = mid+'__'+variant
                    row[name+'_disagreement'] = disagreement
            rows.append(row)
    if not rows:
        raise ValueError(f'No objects in {split}; check detector coverage')
    metadata = {'schema_version': 1, 'synthetic': dataset.get('synthetic', False), 'split': split,
                'dataset_sha256': digest(dataset_path), 'replay_sha256': digest(replay_path),
                'predictions_sha256': digest(predictions_path), 'config': config,
                'config_sha256': digest(config_path), 'baseline_source_sha256': digest(CATALOG),
                'calibration_sha256': digest(calibration_path) if calibration_path else None,
                'python': sys.version, 'platform': platform.platform(), 'command': sys.argv,
                'models': predictions['models'], 'row_count': len(rows)}
    try:
        metadata['git_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        metadata['git_revision'] = 'unavailable'
    save(out/'run.json', metadata)
    run_hash = digest(out/'run.json')
    for row in rows:
        row['run_sha256'] = run_hash
    with (out/'objects.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save(out/'frames.json', frame_audit)
    return rows
