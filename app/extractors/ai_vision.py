import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import requests
from PIL import Image

from app.config import ModelSettings, build_models_url
from app.extractors.generic_table import parse_generic_table
from app.models import StatementExtraction, Transaction


STANDARD_HEADER = [
    "交易时间",
    "摘要",
    "凭证类型",
    "凭证号码",
    "借方发生额",
    "贷方发生额",
    "账户余额",
    "流水号",
    "对方户名/账号",
    "对方行名",
]
EXTRACTION_PROMPT = """请读取这张银行对账单图片，只抄录图片中真实可见的内容，不要猜测。
主体流水必须输出为 Markdown 表格，列名和顺序固定为：
交易时间、摘要、凭证类型、凭证号码、借方发生额、贷方发生额、账户余额、流水号、对方户名/账号、对方行名。
金额只写数字；编号保持原样；没有内容的单元格留空。
如果图片中能看到以下账单级信息，请在表格前分别用一行输出；看不到就不要输出：
银行名称：
账号：
账单开始日期：YYYY-MM-DD
账单结束日期：YYYY-MM-DD
账单交易笔数：
账单借方合计：
账单贷方合计：
不要把本页小计冒充账单合计。"""


@dataclass(slots=True)
class CapabilityReport:
    endpoint_reachable: bool = False
    model_callable: bool = False
    vision_capable: bool = False
    models_endpoint_available: bool = False
    messages: list[str] = field(default_factory=list)


def safe_request_error(error: Exception, settings: ModelSettings) -> str:
    message = str(error)
    if settings.api_key:
        message = message.replace(settings.api_key, "***")
    message = re.sub(r"Bearer\s+[^\s,;]+", "Bearer ***", message, flags=re.IGNORECASE)
    return message


def _headers(settings: ModelSettings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return headers


def _message_content(payload: dict) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("模型返回内容缺少 choices.message.content") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        )
    raise ValueError("模型返回的正文格式无法识别")


def _post_chat(
    settings: ModelSettings,
    messages: list[dict],
    timeout: int,
    max_retries: int,
) -> str:
    if not settings.api_url.strip():
        raise ValueError("未填写模型接口地址")
    if not settings.model_name.strip():
        raise ValueError("未填写模型名称")

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url=settings.api_url,
                headers=_headers(settings),
                json={
                    "model": settings.model_name,
                    "messages": messages,
                    "max_tokens": 8192,
                    "temperature": 0,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            return _message_content(response.json())
        except (OSError, ValueError, requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < max_retries:
                time.sleep(1)
    assert last_error is not None
    raise RuntimeError(safe_request_error(last_error, settings)) from last_error


def request_page(
    image_bytes: bytes,
    settings: ModelSettings,
    prompt: str = EXTRACTION_PROMPT,
    timeout: int = 180,
    max_retries: int = 3,
) -> str:
    image_data = base64.b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                },
            ],
        }
    ]
    return _post_chat(settings, messages, timeout=timeout, max_retries=max_retries)


def check_model_capabilities(settings: ModelSettings) -> CapabilityReport:
    report = CapabilityReport()
    if not settings.api_url.strip() or not settings.model_name.strip():
        report.messages.append("请先填写接口地址和模型名称")
        return report

    models_url = build_models_url(settings.api_url)
    try:
        response = requests.get(url=models_url, headers=_headers(settings), timeout=15)
        report.models_endpoint_available = response.status_code < 400
        if report.models_endpoint_available:
            report.endpoint_reachable = True
        else:
            report.messages.append("模型列表接口不可用，将继续测试实际调用")
    except requests.RequestException as exc:
        report.messages.append(f"模型列表接口未响应：{safe_request_error(exc, settings)}")

    try:
        text = _post_chat(
            settings,
            [{"role": "user", "content": "只回答：成功"}],
            timeout=30,
            max_retries=1,
        )
        report.endpoint_reachable = True
        report.model_callable = bool(text.strip())
    except (RuntimeError, ValueError) as exc:
        report.messages.append(f"模型文字调用失败：{safe_request_error(exc, settings)}")
        return report

    tiny_jpeg = base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=="
    )
    try:
        text = request_page(
            tiny_jpeg,
            settings,
            prompt="这是一张测试图。只回答：成功",
            timeout=45,
            max_retries=1,
        )
        report.vision_capable = bool(text.strip())
    except (RuntimeError, ValueError) as exc:
        report.messages.append(f"图片调用失败：{safe_request_error(exc, settings)}")
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_progress(
    progress_path: Path,
    source_path: Path,
    current_page: int,
    header: list[str] | None,
    rows: list[dict],
    metadata: dict | None = None,
    completed: bool = False,
) -> Path:
    payload = {
        "source_path": str(source_path.resolve()),
        "source_sha256": _sha256(source_path),
        "current_page": current_page,
        "header": header,
        "rows": rows,
        "metadata": metadata or {},
        "completed": completed,
    }
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return progress_path


def load_progress(progress_path: Path, source_path: Path) -> dict | None:
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
        if payload.get("source_path") != str(source_path.resolve()):
            return None
        if payload.get("source_sha256") != _sha256(source_path):
            return None
        if not isinstance(payload.get("rows"), list):
            return None
        return payload
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return None


def parse_markdown_tables(content: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line[1:-1].split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                continue
            current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _render_page(pdf_path: Path, page_index: int) -> bytes:
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        image = page.render(scale=2.0).to_pil().convert("L")
        if image.width > 1800:
            ratio = 1800 / image.width
            image = image.resize((1800, int(image.height * ratio)), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
        return buffer.getvalue()
    finally:
        document.close()


def _metadata_from_content(content: str) -> dict[str, object]:
    patterns = {
        "bank_name": r"银行名称[：:]\s*([^\n|]+)",
        "account_number": r"账号[：:]\s*([^\n|]+)",
        "period_start": r"账单开始日期[：:]\s*(\d{4}[-/]\d{2}[-/]\d{2})",
        "period_end": r"账单结束日期[：:]\s*(\d{4}[-/]\d{2}[-/]\d{2})",
        "declared_count": r"账单交易笔数[：:]\s*(\d+)",
        "declared_debit": r"账单借方合计[：:]\s*([0-9,.]+)",
        "declared_credit": r"账单贷方合计[：:]\s*([0-9,.]+)",
    }
    values: dict[str, object] = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, content)
        if match:
            values[name] = match.group(1).strip()
    return values


def _merge_metadata(current: dict, incoming: dict) -> dict:
    merged = dict(current)
    for key, value in incoming.items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def _rows_from_content(content: str, header: list[str] | None) -> tuple[list[str] | None, list[list[str]]]:
    for table in parse_markdown_tables(content):
        if not table:
            continue
        candidate_header = table[0]
        locked_header = header or candidate_header
        if len(locked_header) != len(STANDARD_HEADER):
            continue
        rows = []
        for row in table[1:]:
            if row == candidate_header or row == locked_header:
                continue
            if len(row) == len(locked_header):
                rows.append(row)
        return locked_header, rows
    return header, []


def _date(value: object):
    if not value:
        return None
    normalized = str(value).replace("/", "-")
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return None


def _decimal_or_none(value: object):
    if value in (None, ""):
        return None
    try:
        from decimal import Decimal

        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def extract_ai(
    pdf_path: Path,
    settings: ModelSettings,
    resume: bool = True,
) -> StatementExtraction | None:
    source_path = Path(pdf_path)
    progress_path = Path(str(source_path) + ".ai-progress.json")
    saved = load_progress(progress_path, source_path) if resume else None
    header = saved.get("header") if saved else None
    stored_rows = list(saved.get("rows", [])) if saved else []
    metadata = dict(saved.get("metadata", {})) if saved else {}
    start_page = int(saved.get("current_page", 0)) if saved else 0
    errors: list[str] = []

    document = pdfium.PdfDocument(str(source_path))
    try:
        page_count = len(document)
    finally:
        document.close()

    for page_index in range(start_page, page_count):
        try:
            content = request_page(_render_page(source_path, page_index), settings)
            metadata = _merge_metadata(metadata, _metadata_from_content(content))
            header, rows = _rows_from_content(content, header)
            stored_rows.extend({"page": page_index + 1, "cells": row} for row in rows)
            save_progress(
                progress_path,
                source_path,
                current_page=page_index + 1,
                header=header,
                rows=stored_rows,
                metadata=metadata,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{source_path.name}：第{page_index + 1}页模型读取失败：{safe_request_error(exc, settings)}")
            save_progress(
                progress_path,
                source_path,
                current_page=page_index,
                header=header,
                rows=stored_rows,
                metadata=metadata,
            )
            break

    transactions: list[Transaction] = []
    if header:
        for item in stored_rows:
            try:
                transactions.extend(
                    parse_generic_table(
                        [header, item["cells"]],
                        source_path,
                        page_number=int(item["page"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{source_path.name}：模型结果转为流水失败：{exc}")

    period_start = _date(metadata.get("period_start"))
    period_end = _date(metadata.get("period_end"))
    if transactions:
        period_start = period_start or min(item.occurred_at.date() for item in transactions)
        period_end = period_end or max(item.occurred_at.date() for item in transactions)
    bank_name = str(metadata.get("bank_name", "")).strip()
    account_number = str(metadata.get("account_number", "")).strip()
    for transaction in transactions:
        transaction.bank_name = bank_name
        transaction.account_number = account_number
        transaction.period_start = period_start
        transaction.period_end = period_end
        transaction.extraction_method = "通用视觉模型"

    declared_count_value = metadata.get("declared_count")
    declared_count = int(declared_count_value) if str(declared_count_value or "").isdigit() else None
    declared_debit = _decimal_or_none(metadata.get("declared_debit"))
    declared_credit = _decimal_or_none(metadata.get("declared_credit"))
    if not transactions and declared_count is None:
        return None

    if not errors:
        save_progress(
            progress_path,
            source_path,
            current_page=page_count,
            header=header,
            rows=stored_rows,
            metadata=metadata,
            completed=True,
        )
    return StatementExtraction(
        source_path=source_path,
        bank_name=bank_name,
        account_number=account_number,
        period_start=period_start,
        period_end=period_end,
        page_count=page_count,
        extraction_method="通用视觉模型",
        transactions=transactions,
        declared_count=declared_count,
        declared_debit=declared_debit,
        declared_credit=declared_credit,
        errors=errors,
    )
