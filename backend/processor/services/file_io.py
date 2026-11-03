"""
Reading uploaded CSV/Excel files into DataFrames and writing them back out.

Every cell is loaded as a string. The app is about text pattern matching, and
keeping the original textual representation avoids surprises such as
``00123`` becoming ``123`` or ``1.50`` becoming ``1.5`` after a round trip.
Columns are still *profiled* (text / numeric / empty) so the UI and the LLM
know which columns are worth targeting.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from processor.exceptions import FileValidationError

SUPPORTED_EXTENSIONS = {".csv": "csv", ".tsv": "csv", ".txt": "csv", ".xlsx": "xlsx", ".xls": "xls"}
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
EXCEL_MAX_ROWS = 1_048_575  # Excel's sheet limit minus the header row


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    kind: str  # "text" | "numeric" | "empty"

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.kind}


def detect_file_type(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    try:
        return SUPPORTED_EXTENSIONS[extension]
    except KeyError as exc:
        raise FileValidationError(
            f"Unsupported file type '{extension or 'none'}'. Upload a .csv, .xlsx or .xls file."
        ) from exc


def read_table(path: Path, file_type: str, *, max_rows: int) -> pd.DataFrame:
    """Load a CSV/Excel file as an all-string DataFrame with clean headers."""
    try:
        if file_type == "csv":
            frame = _read_csv(path, max_rows=max_rows)
        else:
            engine = "openpyxl" if file_type == "xlsx" else "xlrd"
            frame = pd.read_excel(
                path, sheet_name=0, dtype=str, engine=engine, nrows=max_rows + 1, keep_default_na=False
            )
    except FileValidationError:
        raise
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError, OSError) as exc:
        raise FileValidationError(f"The file could not be parsed: {exc}") from exc
    except Exception as exc:  # openpyxl / xlrd raise a variety of library-specific errors
        raise FileValidationError("The file could not be read. Is it a valid spreadsheet?") from exc

    if len(frame) > max_rows:
        raise FileValidationError(f"The file has more than {max_rows:,} rows, which is the current limit.")
    if frame.shape[1] == 0:
        raise FileValidationError("The file does not contain any columns.")

    frame = frame.fillna("").astype(str)
    frame.columns = _clean_headers(frame.columns)
    return frame.reset_index(drop=True)


def _read_csv(path: Path, *, max_rows: int) -> pd.DataFrame:
    sample = path.read_bytes()[:64 * 1024]
    if not sample.strip():
        raise FileValidationError("The file is empty.")

    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            delimiter = _sniff_delimiter(sample.decode(encoding))
            return pd.read_csv(
                path,
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
                nrows=max_rows + 1,
                on_bad_lines="error",
            )
        except UnicodeDecodeError as exc:
            last_error = exc
    raise FileValidationError("The file encoding is not supported. Save it as UTF-8 and retry.") from last_error


def _sniff_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _clean_headers(columns: pd.Index) -> list[str]:
    """Strip whitespace, name blank/unnamed headers and de-duplicate."""
    cleaned: list[str] = []
    used: set[str] = set()
    for position, raw in enumerate(columns, start=1):
        name = str(raw).strip()
        if not name or name.startswith("Unnamed:"):
            name = f"Column {position}"
        candidate, counter = name, 1
        while candidate in used:
            counter += 1
            candidate = f"{name} ({counter})"
        used.add(candidate)
        cleaned.append(candidate)
    return cleaned


def profile_columns(frame: pd.DataFrame) -> list[ColumnProfile]:
    return [ColumnProfile(name=column, kind=_infer_kind(frame[column])) for column in frame.columns]


def _infer_kind(series: pd.Series, sample_size: int = 2000) -> str:
    non_empty = series[series.str.strip() != ""]
    if non_empty.empty:
        return "empty"
    sample = non_empty.head(sample_size)
    numeric = pd.to_numeric(sample.str.replace(",", "", regex=False), errors="coerce")
    return "numeric" if numeric.notna().all() else "text"


def sample_values(frame: pd.DataFrame, column: str, limit: int = 5, max_length: int = 80) -> list[str]:
    """Distinct, non-empty example values used to give the LLM context."""
    values = frame[column]
    distinct = values[values.str.strip() != ""].drop_duplicates().head(limit)
    return [value if len(value) <= max_length else value[:max_length] + "…" for value in distinct]


def export_bytes(frame: pd.DataFrame, file_format: str) -> tuple[bytes, str]:
    """Serialise a frame for download. Returns ``(payload, content_type)``."""
    if file_format == "csv":
        return frame.to_csv(index=False).encode("utf-8-sig"), "text/csv; charset=utf-8"
    if file_format == "xlsx":
        if len(frame) > EXCEL_MAX_ROWS:
            raise FileValidationError("This dataset is too large for Excel. Download it as CSV instead.")
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False, engine="openpyxl")
        return (
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    raise FileValidationError(f"Unknown export format '{file_format}'. Use csv or xlsx.")
