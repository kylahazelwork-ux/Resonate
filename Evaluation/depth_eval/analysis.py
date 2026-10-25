"""Paired scene-cluster statistics. All uncertainty intervals use whole groups."""
from __future__ import annotations

import csv
import html
import math
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

from .core import PRIORS, SEED, digest, finite, load, quantile, save, valid

METRICS = ('mae_m', 'mean_abs_rel', 'median_abs_m', 'p90_abs_m', 'median_abs_rel',
           'p90_abs_rel', 'mean_bias_m', 'median_bias_m', 'positive_error_rate',
           'over20_rate', 'over50_rate', 'false_far_rate', 'within20_rate',
           'within05m_rate', 'failure_rate', 'missing_rate', 'coverage')


def number(value):
    try:
        v = float(value)
        return v if finite(v) else None
    except (ValueError, TypeError):
        return None


def read_rows(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        return [{k: number(v) if k.endswith(('_m', '_uncertainty', '_disagreement')) else v
                 for k, v in row.items()} for row in csv.DictReader(stream)]


def metrics(rows, key):
    rows = [r for r in rows if valid(r['gt_m'])]
    n = len(rows)
    errors = [r[key]-r['gt_m'] for r in rows if valid(r.get(key))]
    relative = [abs(r[key]-r['gt_m'])/r['gt_m'] for r in rows if valid(r.get(key))]
    absolute = [abs(e) for e in errors]
    k = len(errors)
    near = [r for r in rows if r['gt_m'] <= 1.5]
    result = dict.fromkeys(METRICS)
    result.update(n=n, estimates=k, groups=len({r['group_id'] for r in rows}))
    if not n:
        return result
    result.update(coverage=k/n, missing_rate=(n-k)/n,
                  failure_rate=(n-k+sum(e > .5 for e in relative))/n,
                  within20_rate=sum(e <= .2 for e in relative)/n,
                  within05m_rate=sum(e <= .5 for e in absolute)/n,
                  over20_rate=sum(valid(r.get(key)) and r[key] > 1.2*r['gt_m'] for r in rows)/n,
                  over50_rate=sum(valid(r.get(key)) and r[key] > 1.5*r['gt_m'] for r in rows)/n,
                  false_far_rate=(sum(valid(r.get(key)) and r[key] > 1.5 for r in near)/len(near)) if near else None,
                  positive_error_rate=sum(e > 0 for e in errors)/n)
    if k:
        result.update(mae_m=st.mean(absolute), mean_abs_rel=st.mean(relative),
                      median_abs_m=st.median(absolute), p90_abs_m=quantile(absolute, .9),
                      median_abs_rel=st.median(relative), p90_abs_rel=quantile(relative, .9),
                      mean_bias_m=st.mean(errors), median_bias_m=st.median(errors))
    return result


def primary(rows):
    return [r for r in rows if r['track'] == 'yolo' and r['class'] in PRIORS
            and valid(r['gt_m']) and .2 <= r['gt_m'] < 3]


def differences(rows, candidate):
    common = [r for r in rows if valid(r.get(candidate)) and valid(r.get('baseline_m'))]
    b, c = metrics(common, 'baseline_m'), metrics(common, candidate)
    bf, cf = metrics(rows, 'baseline_m'), metrics(rows, candidate)
    result = {}
    for metric in ('median_abs_rel', 'mae_m', 'over20_rate', 'over50_rate', 'false_far_rate'):
        result['paired_'+metric] = c[metric]-b[metric] if c[metric] is not None and b[metric] is not None else None
    for metric in ('failure_rate', 'over20_rate', 'over50_rate', 'false_far_rate', 'coverage'):
        result['full_'+metric] = cf[metric]-bf[metric] if cf[metric] is not None and bf[metric] is not None else None
    return result


def paired_bootstrap(rows, candidate, replicates=10000):
    clusters = defaultdict(list)
    for r in rows:
        clusters[r['group_id']].append(r)
    keys = sorted(clusters)
    point = differences(rows, candidate)
    samples = {k: [] for k in point}
    rng = random.Random(SEED)
    if len(keys) >= 2:
        for _ in range(replicates):
            resample = [r for g in rng.choices(keys, k=len(keys)) for r in clusters[g]]
            for k, value in differences(resample, candidate).items():
                if value is not None:
                    samples[k].append(value)
    return {k: {'difference': value, 'lo': quantile(samples[k], .025),
                'hi': quantile(samples[k], .975), 'valid_replicates': len(samples[k]),
                'undefined_replicates': replicates-len(samples[k]), 'groups': len(keys)}
            for k, value in point.items()}


def band(g):
    if not valid(g):
        return 'unknown'
    return '0-1' if g < 1 else '1-2' if g < 2 else '2-3' if g < 3 else '3-5' if g < 5 else '5+'


def strata(rows):
    # Explicit empty levels preserve missing strata rather than hiding them.
    yield 'overall', 'all', rows
    for level in ('0-1', '1-2', '2-3', '3-5', '5+', 'unknown'):
        yield 'distance_band', level, [r for r in rows if band(r['gt_m']) == level]
    levels = {'lighting': ('bright', 'indoor/ordinary', 'low-light'),
              'motion': ('stationary', 'walking'), 'environment': ('indoor', 'outdoor'),
              'type': ('chair', 'person', 'door', 'pole', 'wall', 'parked car', 'low obstacle', 'glass/reflective'),
              'class': sorted(PRIORS), 'material': ('glass', 'reflective', 'thin', 'opaque', 'unknown')}
    for field, values in levels.items():
        for level in sorted(set(values) | {r[field] for r in rows}):
            yield field, level, [r for r in rows if r[field] == level]
    yield 'intersection', 'low-light+walking', [r for r in rows if r['lighting'] == 'low-light' and r['motion'] == 'walking']
    yield 'intersection', 'reflective/glass+0-3', [r for r in rows if r['material'] in ('glass', 'reflective') and valid(r['gt_m']) and r['gt_m'] < 3]


def signal(row, method):
    name = method.removesuffix('_m')
    v = [row.get(name+'_uncertainty'), row.get(name+'_disagreement')]
    return max(v) if all(finite(x) for x in v) else None


def fit_uncertainty(rows, method):
    data = [(signal(r, method), abs(r[method]-r['gt_m'])/r['gt_m'] > .5, r['group_id'])
            for r in rows if valid(r.get(method)) and valid(r['gt_m']) and signal(r, method) is not None]
    if len(data) < 50 or len({g for _, _, g in data}) < 5 or len({e for _, e, _ in data}) < 2:
        return {'status': 'insufficient_calibration'}
    data.sort()
    bins = []
    for i in range(5):
        chunk = data[len(data)*i//5:len(data)*(i+1)//5]
        if chunk:
            bins.append({'max_signal': chunk[-1][0], 'probability': sum(e for _, e, _ in chunk)/len(chunk), 'n': len(chunk)})
    return {'status': 'ok', 'bins': bins, 'source_split': 'calibration'}


def probability(value, fit):
    if value is None or fit.get('status') != 'ok':
        return None
    return next((b['probability'] for b in fit['bins'] if value <= b['max_signal']), fit['bins'][-1]['probability'])


def ranks(values):
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result = [0.]*len(values)
    i = 0
    while i < len(values):
        j = i+1
        while j < len(values) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        for k in ordered[i:j]:
            result[k] = (i+j-1)/2+1
        i = j
    return result


def uncertainty_report(rows, method, fit, threshold):
    data = [(signal(r, method), abs(r[method]-r['gt_m'])/r['gt_m'], r)
            for r in rows if valid(r.get(method)) and valid(r['gt_m']) and signal(r, method) is not None]
    if not data:
        return {'status': 'unavailable'}
    scores, errors = [x[0] for x in data], [x[1] for x in data]
    labels = [e > .5 for e in errors]
    pos, neg = sum(labels), len(labels)-sum(labels)
    ranking = ranks(scores)
    auc = (sum(r for r, e in zip(ranking, labels) if e)-pos*(pos+1)/2)/(pos*neg) if pos and neg else None
    try:
        rho = st.correlation(ranks(scores), ranks(errors))
    except st.StatisticsError:
        rho = None
    probs = [probability(s, fit) for s in scores]
    reliability = []
    for lo in (0., .2, .4, .6, .8):
        ix = [i for i, p in enumerate(probs) if p is not None and lo <= p <= 1 and (p < lo+.2 or lo == .8)]
        reliability.append({'lower': lo, 'n': len(ix),
                            'predicted': st.mean(probs[i] for i in ix) if ix else None,
                            'observed': st.mean(labels[i] for i in ix) if ix else None})
    risk = []
    for coverage in (.2, .4, .6, .8, 1.):
        selected = sorted(data, key=lambda x: x[0])[:max(1, math.ceil(coverage*len(data)))]
        risk.append({'coverage_among_signal_available': len(selected)/len(data),
                     'error50_rate': st.mean(e > .5 for _, e, _ in selected)})
    retained = [r for s, _, r in data if threshold is not None and s <= threshold]
    return {'status': 'descriptive_not_deployment_approval', 'n': len(data), 'auroc_error50': auc,
            'spearman': rho, 'brier': st.mean((p-e)**2 for p, e in zip(probs, labels)) if all(p is not None for p in probs) else None,
            'reliability': reliability, 'risk_coverage': risk, 'retained': metrics(retained, method),
            'retained_coverage_all_eligible': len(retained)/len(rows) if rows else 0,
            'threshold': threshold}


def select(calibration_csv, selection_csv, output):
    cal, sel = read_rows(calibration_csv), read_rows(selection_csv)
    if {r['split'] for r in cal} != {'calibration'} or {r['split'] for r in sel} != {'selection'}:
        raise ValueError('Selection may not consume held-out test rows')
    if {r['group_id'] for r in cal} & {r['group_id'] for r in sel}:
        raise ValueError('Calibration/selection scene leakage')
    cal_run, sel_run = load(Path(calibration_csv).parent/'run.json'), load(Path(selection_csv).parent/'run.json')
    for field in ('dataset_sha256', 'replay_sha256', 'config_sha256', 'calibration_sha256', 'models'):
        if cal_run[field] != sel_run[field]:
            raise ValueError('Selection provenance mismatch: '+field)
    eligible = primary(sel)
    methods = [k for k in sel[0] if '__' in k and k.endswith('_m') and 'ORACLE' not in k]
    choices = []
    for method in methods:
        m, b = metrics(eligible, method), metrics(eligible, 'baseline_m')
        common = [r for r in eligible if valid(r.get(method)) and valid(r.get('baseline_m'))]
        cm, bm = metrics(common, method), metrics(common, 'baseline_m')
        passes = bool(common) and m['coverage'] >= b['coverage'] and m['failure_rate'] <= b['failure_rate']
        for key in ('over20_rate', 'over50_rate', 'false_far_rate'):
            passes = passes and m[key] is not None and b[key] is not None and m[key] <= b[key]
            passes = passes and cm[key] is not None and bm[key] is not None and cm[key] <= bm[key]
        choices.append({'method': method, 'eligible_on_tuning': passes, 'metrics': m})
    safe = [c for c in choices if c['eligible_on_tuning']]
    chosen = min(safe, key=lambda c: (c['metrics']['median_abs_rel'], c['metrics']['p90_abs_m'])) if safe else None
    method = chosen['method'] if chosen else None
    fit = fit_uncertainty(primary(cal), method) if method else {'status': 'no_eligible_candidate'}
    signals = [signal(r, method) for r in eligible if method and valid(r.get(method)) and signal(r, method) is not None]
    threshold = quantile(signals, .8) if signals else None
    result = {'schema_version': 1, 'method': method, 'choices': choices, 'uncertainty_fit': fit,
              'uncertainty_threshold': threshold, 'source_split': 'selection',
              'selection_csv_sha256': digest(selection_csv), 'calibration_csv_sha256': digest(calibration_csv),
              'provenance': {f: sel_run[f] for f in ('dataset_sha256', 'replay_sha256', 'config_sha256', 'calibration_sha256', 'models')},
              'synthetic': sel_run['synthetic'], 'seed': SEED}
    if Path(output).exists():
        raise ValueError('Refusing to overwrite frozen selection')
    save(output, result)
    return result


def svg_scatter(rows, method, destination):
    points = [(r['gt_m'], r[method]-r['gt_m']) for r in rows if valid(r['gt_m']) and valid(r.get(method))]
    if not points:
        return
    xmax = max(1, max(x for x, _ in points))
    ymax = max(.1, max(abs(y) for _, y in points))
    shapes = ['<rect width="800" height="450" fill="white"/>',
              '<path d="M60 35V390H770 M60 212H770" fill="none" stroke="#777"/>']
    for x, y in points:
        px, py = 60+710*x/xmax, 212-175*y/ymax
        shapes.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="2" fill="#286ca8" opacity=".45"/>')
    title = html.escape(method+' signed error vs. GT (positive = too far)')
    shapes += [f'<text x="60" y="22">{title}</text>',
               f'<text x="60" y="425">GT depth: 0–{xmax:.2f} m; vertical error: -{ymax:.2f} to +{ymax:.2f} m</text>']
    Path(destination).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450">'+''.join(shapes)+'</svg>', encoding='utf-8')


def analyze(csv_path, output_dir, frozen_path=None, replicates=10000):
    rows = read_rows(csv_path)
    run = load(Path(csv_path).parent/'run.json')
    if digest(Path(csv_path).parent/'run.json') != rows[0]['run_sha256']:
        raise ValueError('Run manifest hash mismatch')
    frozen = load(frozen_path) if frozen_path else None
    if run['split'] == 'test':
        if not frozen:
            raise ValueError('Test analysis requires a tuning-frozen selection')
        for key, value in frozen['provenance'].items():
            if run[key] != value:
                raise ValueError('Test configuration changed after selection: '+key)
    if not run['synthetic'] and replicates != 10000:
        raise ValueError('Real runs require the approved 10,000 bootstrap replicates')
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new analysis output directory')
    out.mkdir(parents=True, exist_ok=True)
    methods = ['baseline_m', 'baseline_intrinsics_proxy_m'] + [k for k in rows[0] if '__' in k and k.endswith('_m')]
    table = []
    for track in ('yolo', 'manual'):
        for field, level, subset in strata([r for r in rows if r['track'] == track]):
            for method in methods:
                table.append({'track': track, 'stratum': field, 'level': level, 'method': method,
                              'observations': len(subset), 'missing_gt': sum(not valid(r['gt_m']) for r in subset),
                              **metrics(subset, method)})
    with (out/'strata.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    comparisons = {m: paired_bootstrap(primary(rows), m, replicates) for m in methods
                   if m not in ('baseline_m', 'baseline_intrinsics_proxy_m') and 'ORACLE' not in m}
    save(out/'paired.json', comparisons)
    sensitivity = {}
    for method in methods:
        groups = defaultdict(list)
        for r in primary(rows):
            groups[r['group_id']].append(r)
        gm = [metrics(v, method) for v in groups.values()]
        sensitivity[method] = {k: st.mean(m[k] for m in gm if m[k] is not None)
                               if any(m[k] is not None for m in gm) else None for k in METRICS}
    save(out/'equal_group_sensitivity.json', sensitivity)
    selected = frozen.get('method') if frozen else None
    uncertainty = uncertainty_report(primary(rows), selected, frozen['uncertainty_fit'], frozen['uncertainty_threshold']) if selected else {'status': 'no_frozen_candidate'}
    save(out/'uncertainty.json', uncertainty)
    coverage = {'observations': len(rows), 'valid_gt': sum(valid(r['gt_m']) for r in rows),
                'groups': len({r['group_id'] for r in rows}),
                'locations': len({r['location_id'] for r in rows}),
                'frames': len(load(Path(csv_path).parent/'frames.json')),
                'detections_unmatched': sum(r['track'] == 'yolo' and r['match_status'] != 'matched' for r in rows),
                'manual_objects_missed': sum(r['track'] == 'manual' and r['match_status'] == 'missed_or_unsupported' for r in rows)}
    save(out/'coverage.json', coverage)
    failures = sorted([{'frame_id': r['frame_id'], 'object_id': r['object_id'], 'method': m,
                        'class': r['class'], 'material': r['material'], 'lighting': r['lighting'], 'motion': r['motion'],
                        'gt_m': r['gt_m'], 'estimate_m': r[m], 'signed_error_m': r[m]-r['gt_m']}
                       for r in rows for m in methods if valid(r['gt_m']) and valid(r.get(m))],
                      key=lambda r: abs(r['signed_error_m']), reverse=True)[:100]
    save(out/'failure_examples.json', failures)
    for method in methods:
        svg_scatter([r for r in rows if r['track'] == 'yolo'], method, out/(method+'.svg'))
    # Statistical gates are reported separately from unverified device/GT gates.
    gates = {'verdict': 'Inconclusive', 'synthetic': run['synthetic'],
             'reason': 'Synthetic smoke only' if run['synthetic'] else 'Review GT, sample floors, baseline parity and device evidence before any verdict',
             'selected_candidate': selected, 'statistical_gates': {}}
    if selected:
        p = primary(rows)
        common = [r for r in p if valid(r.get(selected)) and valid(r.get('baseline_m'))]
        b, c = metrics(common, 'baseline_m'), metrics(common, selected)
        comp = comparisons[selected]
        gates['statistical_gates']['meaningful_improvement'] = bool(b['median_abs_rel'] and c['median_abs_rel'] is not None and
            c['median_abs_rel'] <= .8*b['median_abs_rel'] and b['median_abs_rel']-c['median_abs_rel'] >= .03)
        for key, ci in comp.items():
            gates['statistical_gates'][key] = (ci['lo'] is not None and ci['lo'] >= 0 if key.endswith('coverage') else
                ci['hi'] is not None and (ci['hi'] < 0 if key == 'paired_median_abs_rel' else ci['hi'] <= 0))
    save(out/'decision_review.json', gates)
    title = 'SYNTHETIC SMOKE — NOT ACCURACY EVIDENCE' if run['synthetic'] else 'Offline evaluation — evidence review required'
    def fmt(v):
        return 'N/A' if v is None else f'{v:.4f}'
    lines = [f'# {title}', '', 'Verdict: **Inconclusive**. '+gates['reason']+'.', '',
             f'Primary set: supported YOLO detections, ground truth 0.2-3 m. Test split: {coverage["groups"]} scene groups, '
             f'{coverage["observations"]} observations. Chosen on tuning data: `{selected}`.', '',
             '| Method | Valid GT | Estimates | Coverage | Median AbsRel | p90 error (m) | Failure |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for method in methods:
        m = metrics(primary(rows), method)
        lines.append(f'| {method} | {m["n"]} | {m["estimates"]} | {fmt(m["coverage"])} | {fmt(m["median_abs_rel"])} '
                     f'| {fmt(m["p90_abs_m"])} | {fmt(m["failure_rate"])} |')
    lines += ['', f'## Candidate minus baseline, 95% scene-bootstrap intervals ({replicates} resamples of whole scene groups)', '',
              'Negative is better for errors and failures; positive is better for coverage. '
              'Paired = objects where both have an estimate; full = every eligible object.', '',
              '| Method | Paired median AbsRel | Full failure rate | Full >20% overestimation | Full coverage |',
              '|---|---|---|---|---|']
    def interval(ci):
        return 'N/A' if ci['difference'] is None else f'{ci["difference"]:+.4f} [{fmt(ci["lo"])}, {fmt(ci["hi"])}]'
    for method, comp in comparisons.items():
        lines.append(f'| {method} | {interval(comp["paired_median_abs_rel"])} | {interval(comp["full_failure_rate"])} '
                     f'| {interval(comp["full_over20_rate"])} | {interval(comp["full_coverage"])} |')
    lines += ['', 'See strata.csv, paired.json, coverage.json, failure_examples.json, uncertainty.json and SVG plots.',
              'Oracle methods leak GT and cannot win. Intrinsics proxy is not the shipped camera baseline.',
              'On-device latency, memory, thermals, conversion parity and real-world uncertainty trust are not inferred from this report.']
    (out/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return gates
