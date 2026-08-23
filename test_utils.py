"""
Тесты для extract_skills() из модуля utils.

Запуск: py -m unittest test_utils -v
"""

import unittest

import pandas as pd

from utils import (
    calculate_relevance_score,
    extract_skills,
    build_salary_calibration,
    estimate_hidden_salary,
    clamp_score,
    parse_real_salary,
    detect_technologies,
)
from ollama_client import parse_model_json


class TestExtractSkills(unittest.TestCase):

    def test_json_with_non_string_numbers(self):
        # Раньше падало с AttributeError: int.strip()
        self.assertEqual(extract_skills("[1, 2]"), [])

    def test_json_with_null(self):
        # Раньше падало с AttributeError: NoneType.strip()
        self.assertEqual(extract_skills('["a", null]'), ["a"])

    def test_json_string_array(self):
        self.assertEqual(
            extract_skills('["Python", " SQL ", ""]'),
            ["Python", "SQL"]
        )

    def test_csv_string(self):
        self.assertEqual(
            extract_skills("Python, SQL , Docker"),
            ["Python", "SQL", "Docker"]
        )


class TestCalculateRelevanceScore(unittest.TestCase):

    def test_average_vacancy(self):
        row = {
            "salary_score": 5,
            "competition_score": 5,
            "requirements_density": 5,
            "ai_grade": "Middle"
        }
        self.assertAlmostEqual(calculate_relevance_score(row), 0.15833333333333333)

    def test_best_case(self):
        row = {
            "salary_score": 10,
            "competition_score": 1,
            "requirements_density": 10,
            "ai_grade": "Senior"
        }
        self.assertAlmostEqual(calculate_relevance_score(row), 0.5)

    def test_worst_case(self):
        row = {
            "salary_score": 1,
            "competition_score": 10,
            "requirements_density": 1,
            "ai_grade": "Junior"
        }
        self.assertAlmostEqual(calculate_relevance_score(row), -0.15)


class TestSalaryCalibration(unittest.TestCase):

    @staticmethod
    def _df(rows):
        return pd.DataFrame(rows, columns=["salary_score", "parsed_salary"])

    def test_medians_per_bucket(self):
        rows = [
            (5, 100000), (5, 200000), (5, 150000),
            (7, 300000), (7, 400000), (7, 500000),
        ]
        calibration, market_median = build_salary_calibration(self._df(rows))
        self.assertEqual(calibration[5], 150000)
        self.assertEqual(calibration[7], 400000)
        self.assertEqual(market_median, 250000)

    def test_filters_invalid_rows(self):
        rows = [
            (5, 100000), (5, 140000), (5, 160000),
            (6, float("nan")),
            (None, 250000),
            (11, 250000),
            (0, 250000),
        ]
        calibration, market_median = build_salary_calibration(self._df(rows))
        self.assertEqual(list(calibration.keys()), [5])
        self.assertEqual(calibration[5], 140000)
        self.assertEqual(market_median, 140000.0)

    def test_small_bucket_dropped(self):
        rows = [(5, 100000), (5, 120000), (6, 999999)]
        calibration, _ = build_salary_calibration(self._df(rows))
        self.assertNotIn(6, calibration)

    def test_empty_revealed_data(self):
        df = pd.DataFrame({"salary_score": pd.Series(dtype=float),
                           "parsed_salary": pd.Series(dtype=float)})
        calibration, market_median = build_salary_calibration(df)
        self.assertEqual(calibration, {})
        self.assertIsNone(market_median)


class TestEstimateHiddenSalary(unittest.TestCase):

    def test_interpolation(self):
        calibration = {5: 100000.0, 7: 200000.0}
        self.assertEqual(estimate_hidden_salary(6, calibration), 150000.0)
        self.assertAlmostEqual(estimate_hidden_salary(5.5, calibration), 125000.0)

    def test_exact_hit_and_clamp_to_edges(self):
        calibration = {5: 100000.0}
        self.assertEqual(estimate_hidden_salary(5, calibration), 100000.0)
        self.assertEqual(estimate_hidden_salary(3, calibration), 100000.0)
        self.assertEqual(estimate_hidden_salary(9, calibration), 100000.0)

    def test_fallback(self):
        self.assertIsNone(estimate_hidden_salary(4, {}))
        self.assertEqual(estimate_hidden_salary(4, {}, fallback=80000), 80000)


class TestClampScore(unittest.TestCase):

    def test_bounds_and_types(self):
        cases = [
            (0, 1),
            (99, 10),
            ("8", 8),
            (7.6, 8),
            (None, 5),
            ("abc", 5),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(clamp_score(value), expected)


class TestParseModelJson(unittest.TestCase):

    def test_plain_json(self):
        self.assertEqual(parse_model_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(parse_model_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_model_json("oops"))
        self.assertIsNone(parse_model_json(""))
        self.assertIsNone(parse_model_json(None))

    def test_non_dict_returns_none(self):
        self.assertIsNone(parse_model_json("[1, 2]"))


class TestParseRealSalary(unittest.TestCase):

    def test_rub_format(self):
        self.assertAlmostEqual(parse_real_salary("100 000 руб"), 100000)

    def test_usd_multiplier(self):
        self.assertAlmostEqual(parse_real_salary("$5000"), 450000)

    def test_thousands_suffix(self):
        self.assertAlmostEqual(parse_real_salary("50 тыс"), 50000)

    def test_range_average(self):
        self.assertAlmostEqual(parse_real_salary("от 20 до 40 тысяч"), 30000)

    def test_below_floor_returns_none(self):
        self.assertIsNone(parse_real_salary("10 000"))

    def test_above_ceiling_returns_none(self):
        self.assertIsNone(parse_real_salary("2 000 000 руб"))

    def test_non_string_returns_none(self):
        self.assertIsNone(parse_real_salary(None))


class TestDetectTechnologies(unittest.TestCase):

    def test_python(self):
        self.assertEqual(detect_technologies("Python-разработчик"), ["Python"])

    def test_java_not_javascript(self):
        self.assertEqual(detect_technologies("Java разработчик"), ["Java"])

    def test_frontend_js(self):
        self.assertEqual(detect_technologies("Frontend разработчик (JS)"), ["JavaScript"])

    def test_manager_category(self):
        self.assertEqual(detect_technologies("Менеджер продукта"), ["Marketing / PM"])

    def test_unknown_title_other(self):
        self.assertEqual(detect_technologies("Бухгалтер"), ["Other"])


if __name__ == "__main__":
    unittest.main()
