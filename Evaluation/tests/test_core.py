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


if __name__ == '__main__':
    unittest.main()
