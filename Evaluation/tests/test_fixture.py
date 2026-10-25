"""End-to-end checks on the synthetic correctness fixture: planted errors must come back out."""
import tempfile
import unittest
from pathlib import Path

from depth_eval import analysis, fixture, pipeline


class FixtureKnownAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Runs once: build the fixture, fit the relative model, score the test split.
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cls.paths = fixture.build(out/'inputs')
        pipeline.fit_relative(cls.paths['dataset'], cls.paths['replay'], cls.paths['predictions'],
                              'relative', out/'calibration.json')
        pipeline.evaluate(cls.paths['dataset'], cls.paths['replay'], cls.paths['predictions'],
                          cls.paths['config'], out/'test', 'test', out/'calibration.json', allow_synthetic=True)
        # primary = YOLO detections of app classes with ground truth from 0.2 to 3 m.
        cls.rows = analysis.primary(analysis.read_rows(out/'test'/'objects.csv'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_plus10_model_is_ten_percent_too_far(self):
        result = analysis.metrics(self.rows, 'plus10__center_median_m')
        self.assertAlmostEqual(result['median_abs_rel'], fixture.PLUS10_FACTOR - 1, places=5)
        self.assertEqual(result['coverage'], 1.0)

    def test_missing_prediction_counts_as_a_failure(self):
        result = analysis.metrics(self.rows, 'minus20cm__center_median_m')
        self.assertEqual(result['n'], result['estimates'] + 1)
        self.assertAlmostEqual(result['failure_rate'], 1 / result['n'])


if __name__ == '__main__':
    unittest.main()
