import re
import unittest

from depth_eval import core

# A tiny stand-in for ObjectCatalog.swift, in the same format.
SWAPPED_CATALOG = '''
        "person": Entry(label: "Person", category: .person, typicalHeight: 1.7),
        "backpack": Entry(label: "Bag", category: .obstacle, typicalHeight: 0.5),
'''


class ParsePriorsTests(unittest.TestCase):
    def test_reads_every_entry_with_its_height(self):
        priors = core.parse_priors(SWAPPED_CATALOG)
        self.assertEqual(priors, {'person': 1.7, 'backpack': 0.5})

    def test_rejects_an_entry_it_cannot_read(self):
        broken_catalog = '''
        "person": Entry(label: "Person", category: .person, typicalHeight: 1.7),
        "car": Entry(label: "Car", category: .vehicle,
            typicalHeight: 1.5),
'''
        with self.assertRaises(RuntimeError):
            core.parse_priors(broken_catalog)


class ConfidenceTests(unittest.TestCase):
    def test_threshold_per_class_group(self):
        self.assertEqual(core.minimum_confidence('person'), 0.65)
        self.assertEqual(core.minimum_confidence('truck'), 0.6)
        self.assertEqual(core.minimum_confidence('traffic light'), 0.3)
        self.assertEqual(core.minimum_confidence('chair'), 0.5)

    def test_groups_match_the_swift_switch(self):
        # Every `case "a", "b": someConfidence` line in minimumConfidence(for:).
        cases = re.findall(r'case ([^:\n]+): (\w+Confidence)', core._SOURCE)
        swift = {name: group for names, group in cases for name in re.findall(r'"([^"]+)"', names)}
        self.assertEqual(swift, core.CONFIDENCE_GROUPS)

    def test_baseline_drops_detections_the_app_would_drop(self):
        box = (0.4, 0.3, 0.2, 0.4)  # x, y, width, height, normalized
        self.assertEqual(core.baseline('person', box, 1280, 1000, confidence=0.6),
                         (None, 'below_shipped_confidence'))
        estimate, status = core.baseline('person', box, 1280, 1000, confidence=0.7)
        self.assertEqual(status, 'ok')
        self.assertAlmostEqual(estimate, 1.7 * 1000 / (0.4 * 1280))  # height * focal / box pixels

    def test_manual_boxes_without_a_score_are_not_filtered(self):
        _, status = core.baseline('person', (0.4, 0.3, 0.2, 0.4), 1280, 1000)
        self.assertEqual(status, 'ok')


if __name__ == '__main__':
    unittest.main()
