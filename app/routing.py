from decimal import Decimal
from pathlib import Path
from typing import Callable

from app.config import ModelSettings
from app.extractors.ai_vision import extract_ai, safe_request_error
from app.extractors.chengdu_rural import extract_chengdu_rural
from app.extractors.generic_table import extract_generic_table
from app.extractors.huaxia import extract_huaxia
from app.extractors.minsheng import extract_minsheng
from app.models import ProcessedStatement, StatementExtraction, ValidationReport
from app.validators import validate_statement


Extractor = Callable[[Path], StatementExtraction | None]
PASSED_STATUSES = {"通过", "零交易通过"}


def _model_is_ready(settings: ModelSettings | None) -> bool:
    return bool(settings and settings.api_url.strip() and settings.model_name.strip())


def _failed_report(path: Path, errors: list[str]) -> ValidationReport:
    return ValidationReport(
        status="核对失败",
        actual_count=0,
        actual_debit=Decimal("0.00"),
        actual_credit=Decimal("0.00"),
        errors=errors or [f"{path.name}：没有任何读取方式取得可核对的数据"],
    )


def process_pdf(
    pdf_path: Path,
    settings: ModelSettings | None,
    force_ai: bool = False,
) -> ProcessedStatement:
    source_path = Path(pdf_path)
    attempts: list[tuple[str, Extractor]] = []
    if not force_ai:
        attempts.extend(
            [
                ("普通表格", extract_generic_table),
                ("成都农商行", extract_chengdu_rural),
                ("民生银行", extract_minsheng),
                ("华夏银行", extract_huaxia),
            ]
        )

    if _model_is_ready(settings):
        assert settings is not None
        attempts.append(("通用视觉模型", lambda path: extract_ai(path, settings)))

    route_errors: list[str] = []
    last_extraction: StatementExtraction | None = None
    last_validation: ValidationReport | None = None

    for label, extractor in attempts:
        try:
            extraction = extractor(source_path)
        except Exception as exc:
            message = safe_request_error(exc, settings) if settings else str(exc)
            route_errors.append(f"{source_path.name}：{label}读取失败：{message}")
            continue
        if extraction is None:
            continue

        validation = validate_statement(extraction)
        if validation.status in PASSED_STATUSES:
            return ProcessedStatement(source_path, extraction, validation)
        last_extraction = extraction
        last_validation = validation

    if not _model_is_ready(settings):
        if force_ai:
            route_errors.append(f"{source_path.name}：强制模型模式已开启，但接口地址或模型名称未填写")
        else:
            route_errors.append(f"{source_path.name}：本地读取未通过，且未配置可用的视觉模型")

    if last_validation is not None:
        last_validation.errors.extend(route_errors)
        return ProcessedStatement(source_path, last_extraction, last_validation)
    return ProcessedStatement(source_path, None, _failed_report(source_path, route_errors))
