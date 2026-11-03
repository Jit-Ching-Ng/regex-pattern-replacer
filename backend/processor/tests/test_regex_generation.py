import unittest

from processor.exceptions import PatternError
from processor.services.regex_generation import SYSTEM_PROMPT, ColumnContext, RegexGenerator
from processor.tests.fakes import FakeLLM

EMAIL = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
COLUMNS = [
    ColumnContext("ID", "numeric", ["1", "2"]),
    ColumnContext("Name", "text", ["John Doe", "Jane Smith"]),
    ColumnContext("Email", "text", ["john.doe@example.com", "jane_smith@domain.com"]),
]


def answer(**overrides):
    reply = {"pattern": EMAIL, "flags": [], "columns": ["Email"], "replacement": "REDACTED", "explanation": "Emails"}
    reply.update(overrides)
    return reply


class RegexGeneratorTests(unittest.TestCase):
    def test_parses_a_valid_answer(self):
        llm = FakeLLM(answer())
        suggestion = RegexGenerator(llm).generate("Find emails in Email and replace with REDACTED", COLUMNS)
        self.assertEqual(suggestion.pattern, EMAIL)
        self.assertEqual(suggestion.columns, ["Email"])
        self.assertEqual(suggestion.replacement, "REDACTED")
        self.assertEqual(suggestion.attempts, 1)
        prompt = llm.calls[0]["messages"][0]["content"]
        self.assertIn("john.doe@example.com", prompt)  # sample values give the model context

    def test_accepts_fenced_json_and_matches_columns_case_insensitively(self):
        reply = "```json\n" + '{"pattern": "example\\\\.com", "flags": ["ignorecase"], "columns": ["email"], "replacement": null}' + "\n```"
        llm = FakeLLM(reply)
        suggestion = RegexGenerator(llm).generate("numbers", COLUMNS)
        self.assertEqual(suggestion.columns, ["Email"])
        self.assertEqual(suggestion.flags, ["IGNORECASE"])

    def test_self_corrects_an_invalid_regex(self):
        llm = FakeLLM(answer(pattern="([a-z"), answer())
        suggestion = RegexGenerator(llm).generate("emails", COLUMNS)
        self.assertEqual(suggestion.attempts, 2)
        feedback = llm.calls[1]["messages"][-1]["content"]
        self.assertIn("rejected", feedback)

    def test_self_corrects_unknown_columns(self):
        llm = FakeLLM(answer(columns=["E-mail address"]), answer())
        self.assertEqual(RegexGenerator(llm).generate("emails", COLUMNS).columns, ["Email"])

    def test_grounding_check_asks_once_when_nothing_matches(self):
        llm = FakeLLM(answer(pattern=r"\d{3}-\d{4}"), answer())
        suggestion = RegexGenerator(llm).generate("emails", COLUMNS)
        self.assertEqual(suggestion.pattern, EMAIL)
        self.assertIn("matches none", llm.calls[1]["messages"][-1]["content"])

    def test_user_selected_columns_take_precedence(self):
        llm = FakeLLM(answer(pattern=r"\b[A-Z][a-z]+\b"))
        suggestion = RegexGenerator(llm).generate("capitalised words", COLUMNS, target_columns=["Name"])
        self.assertEqual(suggestion.columns, ["Name"])

    def test_gives_up_after_max_attempts(self):
        llm = FakeLLM("not json", "still not json", "nope")
        with self.assertRaises(PatternError):
            RegexGenerator(llm, max_attempts=3).generate("emails", COLUMNS)

    def test_prompt_examples_are_valid_json_with_valid_patterns(self):
        import json

        from processor.services.regex_engine import compile_pattern

        examples = [line for line in SYSTEM_PROMPT.splitlines() if line.startswith('{"pattern"')]
        self.assertTrue(examples)
        # examples span several physical lines in the source but one logical line in the prompt
        for line in examples:
            data = json.loads(line)
            compile_pattern(data["pattern"], data["flags"])
