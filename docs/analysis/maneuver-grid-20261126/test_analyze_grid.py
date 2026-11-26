"""Synthetic checks for the full-capture analysis math and counter attribution."""
import math
import unittest

from analyze_grid import PerfSnapshot, compare, perf_delta, polar_error


class AnalysisTests(unittest.TestCase):
    def test_angle_convention_and_wrapping(self):
        self.assertAlmostEqual(polar_error(10, 0, 0, 10), 0)
        self.assertAlmostEqual(polar_error(10, math.pi / 2, 10, 0), 0)
        self.assertAlmostEqual(polar_error(10, -math.pi, 0, -10), 0)

    def test_shared_valid_sensor_times(self):
        measured = {1900: 99, 2000: 3, 2100: 4, 2200: 99, 2300: 99}
        errors = {'a': {1900: 99, 2000: 1, 2100: 2, 2200: 99},
                  'b': {1900: 99, 2000: 2, 2100: 4, 2300: 99}}
        common, series = compare(measured, errors, 2000)
        self.assertEqual(common, [2000, 2100])
        self.assertEqual(series['measured'], [3, 4])
        self.assertEqual(series['a'], [1, 2])

    def test_counter_diff_rounding_and_contamination(self):
        start = PerfSnapshot(1, 10, {'predict': (4, 100, 150), 'correct': (3, 100, 110)})
        end = PerfSnapshot(2, 13, {'predict': (6, 150, 225), 'correct': (4, 110, 140)})
        values = perf_delta(start, end, 3, 2, 1)
        self.assertEqual(values['predict']['samples'], 2)
        self.assertAlmostEqual(values['predict']['mean_us_approx'], .25)
        self.assertIsNone(perf_delta(start, end, 4, 2, 1))
        self.assertIsNone(perf_delta(end, start, 3, 2, 1))


if __name__ == '__main__':
    unittest.main()
