"""Shared redaction for any monitor-owned persistent or returned text."""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/=]{8,}"),
    re.compile(r"\b(?:sk-ant-|sk-|xai-|ghp_)[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*([=:])\s*(['\"]?)[^\s,'\"}\]]+"),
    re.compile(r'(?i)(["\'](?:api[_-]?key|token|secret|password|authorization)["\']\s*:\s*["\'])[^"\']+'),
)
_WRAPPED_ASSIGNMENT = re.compile(r"(?i)\b(api\s*[_-]?\s*k\s*e\s*y|token|secret|password|authorization)\s*([=:])\s*([^\s,'\"}\\\]]+(?:\n[^\s,'\"}\\\]]+)*)")


def _redact_wrapped_assignments(value: str) -> str:
    return _WRAPPED_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)


def redact_text(value: str, prompt: str | None = None) -> str:
    result = value.replace(prompt, "[REDACTED_TASK]") if prompt else value
    result = _SECRET_PATTERNS[0].sub(r"\1 [REDACTED]", result)
    result = _SECRET_PATTERNS[1].sub(r"\1 [REDACTED]", result)
    result = _SECRET_PATTERNS[2].sub("[REDACTED]", result)
    result = _redact_wrapped_assignments(result)
    result = _SECRET_PATTERNS[3].sub(r"\1\2\3[REDACTED]", result)
    return _SECRET_PATTERNS[4].sub(r"\1[REDACTED]", result)


def redact_value(value: Any, prompt: str | None = None) -> Any:
    if isinstance(value, str): return redact_text(value, prompt)
    if isinstance(value, list): return [redact_value(item, prompt) for item in value]
    if isinstance(value, dict): return {str(key): redact_value(item, prompt) for key, item in value.items()}
    return value


def safe_task_summary(task: str) -> str:
    compact = " ".join(redact_text(task).split())
    return f"Task submitted ({len(compact)} characters; secrets_redacted={'yes' if '[REDACTED]' in compact else 'no'})"[:240]
