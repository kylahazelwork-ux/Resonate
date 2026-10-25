"""Dependency-free geometry, robust statistics and shipped-baseline port."""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics as st
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'Resonate/Models/ObjectCatalog.swift'


def parse_priors(source):
    """Class name -> typical height (m) from ObjectCatalog.swift source text.

    Fails if any entry was not understood, rather than trusting a fixed class count.
    """
    priors = {name: float(height) for name, height in re.findall(
        r'"([^"]+)": Entry\([^\n]+typicalHeight: ([0-9.]+)\)', source)}
    if not priors or len(priors) != source.count('Entry(label:'):
        raise RuntimeError('Could not parse every ObjectCatalog entry: review the baseline port')
    return priors


PRIORS = parse_priors(CATALOG.read_text(encoding='utf-8'))
VARIANTS = ('center_median', 'center_p25', 'lower_median')
SEED = 20261010


def digest(path):
    path = Path(path)
    h = hashlib.sha256()
    if path.is_dir():
        for p in sorted(x for x in path.rglob('*') if x.is_file()):
            h.update(p.relative_to(path).as_posix().encode())
            h.update(bytes.fromhex(digest(p)))
    else:
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def valid(x):
    return finite(x) and x > 0


def quantile(values, p):
    if not values:
        return None
    v = sorted(values)
    index = (len(v) - 1) * p
    lo = int(index)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (index - lo)


def mad(values):
    m = st.median(values)
    return st.median(abs(x - m) for x in values)


def baseline(label, box, image_height, focal):
    """Same guards/arithmetic as ObjectCatalog + FrameAnalysis (no improvements)."""
    height = PRIORS.get(label.lower())
    if height is None:
        return None, 'unsupported_class'
    _, y, _, h = box
    if y < .01 or y + h > .99:
        return None, 'vertical_edge'
    if h * image_height < 12:
        return None, 'tiny_box'
    if height < .3:
        return None, 'prior_below_minimum'
    if not valid(focal):
        return None, 'missing_focal'
    return height * focal / (h * image_height), 'ok'


def check_box(box):
    if len(box) != 4 or not all(finite(x) for x in box):
        raise ValueError('Box must contain four finite coordinates')
    x, y, w, h = box
    if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1.000001 or y+h > 1.000001:
        raise ValueError(f'Invalid normalized upright box {box}')


def roi(box, variant='center_median'):
    check_box(box)
    x, y, w, h = box
    return (x + .25*w, y + (.5 if variant == 'lower_median' else .25)*h,
            x + .75*w, y + (.8 if variant == 'lower_median' else .75)*h)


def read_map(root, descriptor):
    """Packed little-endian float32 or uint8, with explicit orientation."""
    w, h = descriptor['width'], descriptor['height']
    if not isinstance(w, int) or not isinstance(h, int) or min(w, h) <= 0:
        raise ValueError('Invalid map dimensions')
    kind = descriptor['dtype']
    if kind not in ('float32_le', 'uint8'):
        raise ValueError(f'Unsupported map dtype {kind}')
    path = Path(root) / descriptor['path']
    if descriptor.get('sha256') and digest(path) != descriptor['sha256']:
        raise ValueError(f'Map checksum mismatch: {path}')
    data = path.read_bytes()
    size = 4 if kind == 'float32_le' else 1
    if len(data) != w*h*size:
        raise ValueError(f'Packed buffer size mismatch: {path}')
    return list(struct.unpack('<' + str(w*h) + ('f' if size == 4 else 'B'), data))


def map_indices(box, desc, crop=(0, 0, 1, 1), variant='center_median'):
    """Use pixel centers, rotate right from original sensor coordinates.

    crop is normalized sensor [x,y,w,h] used to create replay RGB.
    Predicted maps are upright already; original LiDAR stays sensor-oriented.
    """
    left, top, right, bottom = roi(box, variant)
    w, h = desc['width'], desc['height']
    orientation = desc['orientation']
    if orientation == 'sensor':
        cx, cy, cw, ch = crop
        left, top, right, bottom = (cx + top*cw, cy + (1-right)*ch,
                                    cx + bottom*cw, cy + (1-left)*ch)
    elif orientation != 'upright':
        raise ValueError('Unknown map orientation')
    for y in range(max(0, math.ceil(top*h-.5)), min(h, math.ceil(bottom*h-.5))):
        for x in range(max(0, math.ceil(left*w-.5)), min(w, math.ceil(right*w-.5))):
            yield y*w+x


def truth(depth, confidence, desc, box, crop, annotation):
    """One fixed GT rule, independent of method and candidate aggregation."""
    if annotation.get('gt_review') != 'accepted':
        return None, {'status': 'unreviewed_or_ambiguous', 'source': 'none'}
    tape = annotation.get('tape_z_m')
    if tape is not None:
        readings = annotation.get('tape_readings_m', [])
        error = annotation.get('tape_uncertainty_m')
        if not valid(tape) or len(readings) != 3 or not all(valid(x) for x in readings):
            raise ValueError('Tape truth needs positive Z and three readings')
        if not finite(error) or error < 0 or error > max(.05, .02*tape):
            return None, {'status': 'tape_uncertainty', 'source': 'tape'}
        if not annotation.get('tape_geometry_verified', False):
            return None, {'status': 'tape_geometry_unverified', 'source': 'tape'}
        return tape, {'status': 'ok', 'source': 'tape', 'uncertainty_m': error}
    if annotation.get('material') in ('glass', 'reflective', 'thin'):
        return None, {'status': 'independent_truth_required', 'source': 'none'}
    if depth is None or confidence is None:
        return None, {'status': 'missing_raw_depth_or_confidence', 'source': 'lidar'}
    indices = list(map_indices(box, desc, crop))
    values = [depth[i] for i in indices if confidence[i] == 2 and finite(depth[i]) and .2 <= depth[i] <= 5]
    info = {'source': 'lidar', 'pixels': len(indices), 'before': len(values)}
    if len(values) < 20 or len(values) < .5*len(indices):
        return None, dict(info, status='insufficient_high_confidence')
    med, deviation = st.median(values), mad(values)
    limit = max(3*1.4826*deviation, .05)
    filtered = [v for v in values if abs(v-med) <= limit]
    info.update(after=len(filtered), mad=deviation)
    if len(filtered) < 20 or len(filtered) < .5*len(indices):
        return None, dict(info, status='insufficient_after_outlier_rejection')
    return st.median(filtered), dict(info, status='ok')


def aggregate(values, desc, box, variant):
    indices = list(map_indices(box, desc, variant=variant))
    kept = [values[i] for i in indices if valid(values[i])]
    if len(kept) < 20 or len(kept) < .5*len(indices):
        return None, None, 'insufficient_predictions'
    estimate = quantile(kept, .25 if variant == 'center_p25' else .5)
    return estimate, mad(kept)/st.median(kept), 'ok'


def affine_fit(samples):
    """Huber IRLS for inverse-depth calibration, equal total scene weights.

    samples = [(relative_value, metric_z, scene_group), ...]. No per-image
    normalization. Positive slope required; degenerate fits are rejected.
    """
    from collections import Counter
    samples = [(r, z, g) for r, z, g in samples if finite(r) and valid(z)]
    if len(samples) < 20:
        raise ValueError('At least 20 calibration samples required')
    counts = Counter(g for _, _, g in samples)
    base = [1/counts[g] for _, _, g in samples]
    weights = base[:]
    a = b = 0.
    for _ in range(30):
        total = sum(weights)
        mx = sum(w*r for w, (r, _, _) in zip(weights, samples))/total
        my = sum(w/z for w, (_, z, _) in zip(weights, samples))/total
        variance = sum(w*(r-mx)**2 for w, (r, _, _) in zip(weights, samples))
        if variance <= 1e-12:
            raise ValueError('Calibration has insufficient depth variation')
        a = sum(w*(r-mx)*(1/z-my) for w, (r, z, _) in zip(weights, samples))/variance
        b = my-a*mx
        residuals = [1/z-(a*r+b) for r, z, _ in samples]
        scale = max(1e-8, 1.4826*mad(residuals))
        weights = [w*min(1., 1.345*scale/max(abs(e), 1e-12)) for w, e in zip(base, residuals)]
    if not finite(a) or not finite(b) or a <= 0:
        raise ValueError('Calibration must have a finite positive inverse-depth slope')
    return {'a': a, 'b': b, 'samples': len(samples), 'groups': len(counts)}


def scale_relative(values, fit):
    a, b = fit['a'], fit['b']
    if not valid(a) or not finite(b):
        raise ValueError('Invalid relative calibration')
    return [1/(a*r+b) if finite(r) and a*r+b > 0 else float('nan') for r in values]


def iou(a, b):
    x = max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]))
    y = max(0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))
    inter = x*y
    return inter/(a[2]*a[3]+b[2]*b[3]-inter)
