import csv
import hashlib
import io
import json
from typing import Any, Dict, List, Optional, Set, Tuple


class DatasetValidationError(Exception):
    """Raised when file validation fails before parsing."""
    pass


class ParsedDatasetResult:
    def __init__(
        self,
        is_valid: bool,
        checksum_sha256: str,
        records: List[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        total_rows_processed: int
    ):
        self.is_valid = is_valid
        self.checksum_sha256 = checksum_sha256
        self.records = records
        self.errors = errors
        self.total_rows_processed = total_rows_processed


MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


def validate_file_size(content: bytes) -> None:
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise DatasetValidationError(
            f"File size exceeds maximum permitted limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB."
        )


def compute_sha256(content: bytes) -> str:
    hasher = hashlib.sha256()
    hasher.update(content)
    return hasher.hexdigest()


def parse_and_validate_dataset(content: bytes, filename: str) -> ParsedDatasetResult:
    """
    Parses and validates a CSV or JSONL dataset file.
    Enforces required fields, checks for duplicate case_ids, and reports row errors.
    """
    validate_file_size(content)
    checksum = compute_sha256(content)

    filename_lower = filename.lower()
    if filename_lower.endswith(".jsonl"):
        return _parse_jsonl(content, checksum)
    elif filename_lower.endswith(".csv"):
        return _parse_csv(content, checksum)
    else:
        raise DatasetValidationError(
            "Unsupported file format. Please upload a .jsonl or .csv file."
        )


def _validate_record(
    record: Dict[str, Any],
    row_num: int,
    seen_ids: Set[str]
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Validates a single record row."""
    case_id = str(record.get("case_id", "")).strip()
    prompt = str(record.get("prompt", "")).strip()
    expected_behavior = str(record.get("expected_behavior", "")).strip()

    missing = []
    if not case_id:
        missing.append("case_id")
    if not prompt:
        missing.append("prompt")
    if not expected_behavior:
        missing.append("expected_behavior")

    if missing:
        return False, None, {
            "row": row_num,
            "error": f"Missing required field(s): {', '.join(missing)}",
            "raw": str(record)[:120]
        }

    if case_id in seen_ids:
        return False, None, {
            "row": row_num,
            "error": f"Duplicate case_id '{case_id}' detected.",
            "raw": case_id
        }

    seen_ids.add(case_id)

    # Normalize optional metadata
    raw_metadata = record.get("metadata", {})
    if isinstance(raw_metadata, str):
        try:
            metadata_dict = json.loads(raw_metadata) if raw_metadata.strip() else {}
        except Exception:
            metadata_dict = {"raw_metadata": raw_metadata}
    elif isinstance(raw_metadata, dict):
        metadata_dict = raw_metadata
    else:
        metadata_dict = {}

    cleaned_record = {
        "case_id": case_id,
        "prompt": prompt,
        "expected_behavior": expected_behavior,
        "reference_answer": record.get("reference_answer"),
        "candidate_response": record.get("candidate_response"),
        "category": str(record.get("category", "General")).strip() or "General",
        "difficulty": str(record.get("difficulty", "Medium")).strip() or "Medium",
        "metadata_json": metadata_dict
    }

    return True, cleaned_record, None


def _parse_jsonl(content: bytes, checksum: str) -> ParsedDatasetResult:
    records: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    text_stream = io.StringIO(content.decode("utf-8", errors="replace"))
    row_num = 0

    for line in text_stream:
        row_num += 1
        line_str = line.strip()
        if not line_str:
            continue

        try:
            raw_obj = json.loads(line_str)
            if not isinstance(raw_obj, dict):
                errors.append({
                    "row": row_num,
                    "error": "JSONL line must be a JSON object ({...})",
                    "raw": line_str[:120]
                })
                continue
        except Exception as e:
            errors.append({
                "row": row_num,
                "error": f"Malformed JSON syntax: {str(e)}",
                "raw": line_str[:120]
            })
            continue

        is_valid, record, err = _validate_record(raw_obj, row_num, seen_ids)
        if is_valid and record:
            records.append(record)
        elif err:
            errors.append(err)

    is_overall_valid = len(errors) == 0 and len(records) > 0
    return ParsedDatasetResult(
        is_valid=is_overall_valid,
        checksum_sha256=checksum,
        records=records,
        errors=errors,
        total_rows_processed=row_num
    )


def _parse_csv(content: bytes, checksum: str) -> ParsedDatasetResult:
    records: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    text_stream = io.StringIO(content.decode("utf-8", errors="replace"))
    reader = csv.DictReader(text_stream)

    if not reader.fieldnames:
        return ParsedDatasetResult(
            is_valid=False,
            checksum_sha256=checksum,
            records=[],
            errors=[{"row": 1, "error": "CSV file contains no headers or is empty"}],
            total_rows_processed=0
        )

    row_num = 1  # Header is row 1
    for row in reader:
        row_num += 1
        is_valid, record, err = _validate_record(row, row_num, seen_ids)
        if is_valid and record:
            records.append(record)
        elif err:
            errors.append(err)

    is_overall_valid = len(errors) == 0 and len(records) > 0
    return ParsedDatasetResult(
        is_valid=is_overall_valid,
        checksum_sha256=checksum,
        records=records,
        errors=errors,
        total_rows_processed=row_num - 1
    )
