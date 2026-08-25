from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable

from app.config import ModelSettings
from app.models import BatchResult, ProcessedStatement, ValidationReport
from app.routing import process_pdf


ProgressCallback = Callable[[int, int, str], None]


def scan_pdf_files(folder: Path) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        return []
    paths = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.casefold() == ".pdf"
        and "提取结果" not in path.relative_to(root).parts
    ]
    return sorted(paths, key=lambda path: str(path.relative_to(root)).casefold())


def _unexpected_failure(path: Path, error: Exception) -> ProcessedStatement:
    return ProcessedStatement(
        source_path=path,
        extraction=None,
        validation=ValidationReport(
            status="核对失败",
            actual_count=0,
            actual_debit=Decimal("0.00"),
            actual_credit=Decimal("0.00"),
            errors=[f"{path.name}：处理时发生意外错误：{error}"],
        ),
    )


def _statement_sort_key(statement: ProcessedStatement):
    extraction = statement.extraction
    period_start = extraction.period_start if extraction and extraction.period_start else date.max
    period_end = extraction.period_end if extraction and extraction.period_end else date.max
    return period_start, period_end, statement.source_path.name.casefold()


def process_batch(
    paths: list[Path],
    settings: ModelSettings | None,
    force_ai: bool,
    progress: ProgressCallback | None = None,
) -> BatchResult:
    statements: list[ProcessedStatement] = []
    total = len(paths)
    for index, raw_path in enumerate(paths, start=1):
        path = Path(raw_path)
        if progress:
            progress(index - 1, total, f"正在处理：{path.name}")
        try:
            statement = process_pdf(path, settings, force_ai=force_ai)
        except Exception as exc:
            statement = _unexpected_failure(path, exc)
        statements.append(statement)
        if progress:
            progress(index, total, f"{path.name}：{statement.validation.status}")

    statements.sort(key=_statement_sort_key)
    return BatchResult(statements=statements)
