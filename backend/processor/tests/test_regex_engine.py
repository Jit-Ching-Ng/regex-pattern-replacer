import unittest

import pandas as pd

from processor.exceptions import OperationTimeout, PatternError
from processor.services.regex_engine import check_zero_width_matches, compile_pattern, replace_in_frame

EMAIL = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ID": ["1", "2", "3"],
            "Name": ["John Doe", "Jane Smith", "Alice Brown"],
            "Email": ["john.doe@example.com", "jane_smith@domain.com", "alice.brown@website.org"],
        }
    )


class CompilePatternTests(unittest.TestCase):
    def test_rejects_empty_and_invalid_patterns(self):
        for pattern in ["", "   ", "(unclosed", "[a-"]:
            with self.subTest(pattern=pattern), self.assertRaises(PatternError):
                compile_pattern(pattern)

    def test_rejects_patterns_matching_empty_text(self):
        for pattern in [r"\d*", "a?", "^", "(?:)"]:
            with self.subTest(pattern=pattern), self.assertRaises(PatternError):
                compile_pattern(pattern)

    def test_rejects_unknown_flags(self):
        with self.assertRaises(PatternError):
            compile_pattern("abc", ["VERBOSE_NONSENSE"])

    def test_flags_are_applied(self):
        self.assertIsNotNone(compile_pattern("hello", ["IGNORECASE"]).search("HeLLo"))

    def test_zero_width_matches_are_rejected(self):
        compiled = compile_pattern(r"\b")
        with self.assertRaises(PatternError):
            check_zero_width_matches(compiled, ["two words"], timeout=1)


class ReplaceInFrameTests(unittest.TestCase):
    def test_brief_example_redacts_emails(self):
        frame = sample_frame()
        result = replace_in_frame(frame, compile_pattern(EMAIL), "REDACTED", ["Email"])
        self.assertEqual(result.frame["Email"].tolist(), ["REDACTED"] * 3)
        self.assertEqual(result.cells_changed, 3)
        self.assertEqual(result.matches, 3)
        # the input frame is untouched and other columns are preserved
        self.assertEqual(frame["Email"].iat[0], "john.doe@example.com")
        self.assertEqual(result.frame["Name"].tolist(), frame["Name"].tolist())

    def test_counts_multiple_matches_and_repeated_values(self):
        frame = pd.DataFrame({"t": ["a1 b2", "a1 b2", "none", ""]})
        result = replace_in_frame(frame, compile_pattern(r"\d"), "#", ["t"])
        self.assertEqual(result.frame["t"].tolist(), ["a# b#", "a# b#", "none", ""])
        self.assertEqual(result.matches, 4)
        self.assertEqual(result.cells_changed, 2)
        self.assertEqual(result.per_column["t"], {"matches": 4, "cells_changed": 2})

    def test_replacement_is_literal_by_default(self):
        frame = pd.DataFrame({"path": ["old"]})
        result = replace_in_frame(frame, compile_pattern("(old)"), r"C:\new\1", ["path"])
        self.assertEqual(result.frame["path"].iat[0], r"C:\new\1")

    def test_group_references_when_enabled(self):
        frame = pd.DataFrame({"name": ["Doe, John"]})
        compiled = compile_pattern(r"(\w+), (\w+)")
        result = replace_in_frame(frame, compiled, r"\2 \1", ["name"], use_backrefs=True)
        self.assertEqual(result.frame["name"].iat[0], "John Doe")

    def test_invalid_group_reference_raises(self):
        frame = pd.DataFrame({"name": ["Doe"]})
        with self.assertRaises(PatternError):
            replace_in_frame(frame, compile_pattern(r"(\w+)"), r"\5", ["name"], use_backrefs=True)

    def test_samples_are_collected(self):
        result = replace_in_frame(sample_frame(), compile_pattern(EMAIL), "X", ["Email"], sample_limit=2)
        self.assertEqual(len(result.samples), 2)
        self.assertEqual(result.samples[0].before, "john.doe@example.com")
        self.assertEqual(result.samples[0].after, "X")

    def test_time_budget_is_enforced(self):
        frame = pd.DataFrame({"t": [f"value {i}" for i in range(50)]})
        with self.assertRaises(OperationTimeout):
            replace_in_frame(frame, compile_pattern(r"\d"), "#", ["t"], time_budget=-1)
