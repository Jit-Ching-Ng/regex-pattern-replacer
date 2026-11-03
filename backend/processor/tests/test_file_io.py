import tempfile
import unittest
from pathlib import Path

import pandas as pd

from processor.exceptions import FileValidationError
from processor.services import file_io


class FileIOTests(unittest.TestCase):
    def write(self, name: str, content: bytes) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / name
        path.write_bytes(content)
        return path

    def test_reads_csv_as_strings_and_keeps_leading_zeros(self):
        path = self.write("a.csv", b"ID,Zip,Email\n1,00123,a@b.com\n2,,c@d.org\n")
        frame = file_io.read_table(path, "csv", max_rows=10)
        self.assertEqual(frame["Zip"].tolist(), ["00123", ""])
        self.assertEqual([c.as_dict() for c in file_io.profile_columns(frame)], [
            {"name": "ID", "kind": "numeric"},
            {"name": "Zip", "kind": "numeric"},
            {"name": "Email", "kind": "text"},
        ])

    def test_sniffs_semicolons_and_cleans_headers(self):
        path = self.write("b.csv", "Name; ;Name\nJosé;x;y\n".encode("cp1252"))
        frame = file_io.read_table(path, "csv", max_rows=10)
        self.assertEqual(list(frame.columns), ["Name", "Column 2", "Name.1"])
        self.assertEqual(frame["Name"].iat[0], "José")

    def test_reads_xlsx(self):
        path = Path(tempfile.mkdtemp()) / "c.xlsx"
        pd.DataFrame({"A": [1, 2], "B": ["x", None]}).to_excel(path, index=False)
        frame = file_io.read_table(path, "xlsx", max_rows=10)
        self.assertEqual(frame["B"].tolist(), ["x", ""])

    def test_rejects_bad_input(self):
        with self.assertRaises(FileValidationError):
            file_io.detect_file_type("report.pdf")
        with self.assertRaises(FileValidationError):
            file_io.read_table(self.write("e.csv", b""), "csv", max_rows=10)
        with self.assertRaises(FileValidationError):
            file_io.read_table(self.write("f.csv", b"a\n1\n2\n3\n"), "csv", max_rows=2)

    def test_export_round_trip(self):
        frame = pd.DataFrame({"A": ["1", "x"]})
        payload, content_type = file_io.export_bytes(frame, "csv")
        self.assertTrue(content_type.startswith("text/csv"))
        self.assertIn(b"A\r\n1\r\nx" if b"\r\n" in payload else b"A\n1\nx", payload)
        payload, _ = file_io.export_bytes(frame, "xlsx")
        self.assertTrue(payload.startswith(b"PK"))
