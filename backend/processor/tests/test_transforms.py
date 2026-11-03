import unittest

import pandas as pd

from processor.exceptions import ColumnError, ProcessingError
from processor.services.transforms import DERIVE, STANDARDIZE, ColumnTransformer
from processor.tests.fakes import FakeLLM, echo_transform


class ColumnTransformerTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"Country": ["usa", "USA", "canada", "usa", ""], "n": ["1", "2", "3", "4", "5"]})

    def test_standardize_rewrites_distinct_values_in_place(self):
        llm = FakeLLM(echo_transform(lambda v: {"usa": "US", "USA": "US", "canada": "CA"}[v]))
        result = ColumnTransformer(llm).apply(
            self.frame(), kind=STANDARDIZE, column="Country", instruction="ISO country codes"
        )
        self.assertEqual(result.frame["Country"].tolist(), ["US", "US", "CA", "US", ""])
        self.assertEqual(result.distinct_values, 3)  # empty values are never sent
        self.assertEqual(result.cells_changed, 4)

    def test_derive_inserts_a_new_column_next_to_the_source(self):
        llm = FakeLLM(echo_transform(str.upper))
        result = ColumnTransformer(llm).apply(
            self.frame(), kind=DERIVE, column="Country", instruction="upper", new_column="Upper"
        )
        self.assertEqual(list(result.frame.columns), ["Country", "Upper", "n"])
        self.assertEqual(result.frame["Upper"].tolist(), ["USA", "USA", "CANADA", "USA", ""])

    def test_batches_and_retries_missing_ids(self):
        frame = pd.DataFrame({"v": [f"x{i}" for i in range(5)]})

        def skip_first(system, messages):
            reply = echo_transform(str.upper)(system, messages)
            reply["results"] = reply["results"][1:]
            return reply

        llm = FakeLLM(skip_first, echo_transform(str.upper), echo_transform(str.upper))
        result = ColumnTransformer(llm, batch_size=3).apply(frame, kind=STANDARDIZE, column="v", instruction="up")
        self.assertEqual(result.frame["v"].tolist(), ["X0", "X1", "X2", "X3", "X4"])
        self.assertEqual(result.unresolved, 0)
        self.assertEqual(len(llm.calls), 3)

    def test_validation(self):
        transformer = ColumnTransformer(FakeLLM(), max_unique_values=2)
        with self.assertRaises(ColumnError):
            transformer.apply(self.frame(), kind=STANDARDIZE, column="missing", instruction="x")
        with self.assertRaises(ColumnError):
            transformer.apply(self.frame(), kind=DERIVE, column="Country", instruction="x", new_column="n")
        with self.assertRaises(ProcessingError):
            transformer.apply(self.frame(), kind=STANDARDIZE, column="Country", instruction="x")
