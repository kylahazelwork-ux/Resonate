"""One command for the whole evaluation: python -m depth_eval --help"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import analysis, fixture, pipeline
from .core import load


def run_all(paths, out, replicates=None, allow_synthetic=False):
    """Calibrate on calibration scenes, choose on selection scenes, then report on test scenes.

    The order matters: nothing chosen or fitted ever sees the test split.
    """
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError(f'{out} is not empty; use a new output folder')
    config = load(paths['config'])
    relative = [m['id'] for m in config['models'] if m['kind'] == 'relative']
    if len(relative) > 1:
        raise ValueError('Only one relative model per run is supported')
    calibration = None
    if relative:
        calibration = out/'calibration.json'
        pipeline.fit_relative(paths['dataset'], paths['replay'], paths['predictions'], relative[0], calibration)
    for split in ('calibration', 'selection', 'test'):
        pipeline.evaluate(paths['dataset'], paths['replay'], paths['predictions'], paths['config'],
                          out/split, split, calibration, allow_synthetic)
    analysis.select(out/'calibration'/'objects.csv', out/'selection'/'objects.csv', out/'selection.json')
    analysis.analyze(out/'test'/'objects.csv', out/'report', out/'selection.json',
                     replicates or config['bootstrap_replicates'])
    return out/'report'/'report.md'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m depth_eval', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('fixture', help='build the synthetic correctness fixture and report on it')
    demo.add_argument('--out', required=True, type=Path, help='new, empty output folder')
    demo.add_argument('--replicates', type=int, default=2000,
                      help='bootstrap resamples (synthetic only; real runs always use the config value)')
    real = commands.add_parser('run', help='evaluate a real dataset')
    for name in ('dataset', 'replay', 'predictions', 'config'):
        real.add_argument('--'+name, required=True, type=Path)
    real.add_argument('--out', required=True, type=Path, help='new, empty output folder')
    args = parser.parse_args(argv)

    if args.command == 'fixture':
        paths = fixture.build(args.out/'inputs')
        report = run_all(paths, args.out/'results', args.replicates, allow_synthetic=True)
    else:
        paths = {name: getattr(args, name) for name in ('dataset', 'replay', 'predictions', 'config')}
        report = run_all(paths, args.out)
    print(f'Report: {report}')


if __name__ == '__main__':
    main()
