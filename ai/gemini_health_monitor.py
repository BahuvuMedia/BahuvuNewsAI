"""
BahuvuNewsAI Gemini API Health Monitor.

Capabilities:
- Finds Gemini API keys from environment variables and .env.
- Never prints or writes complete API keys.
- Tests keys sequentially to avoid creating an artificial rate spike.
- Measures authentication, model access, latency, reliability, and response quality.
- Classifies invalid, quota-limited, unavailable, and healthy keys.
- Ranks keys and writes a JSON health report.
- Provides reusable functions for selecting the healthiest key.

Run:
    python -m ai.gemini_health_monitor

Optional:
    python -m ai.gemini_health_monitor --runs 3
    python -m ai.gemini_health_monitor --model gemini-flash-latest
    python -m ai.gemini_health_monitor --show-key-sources
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import requests


MODULE_VERSION = "1.0.0"

DEFAULT_MODEL = (
    os.getenv("BAHUVU_GEMINI_HEALTH_MODEL")
    or os.getenv("GEMINI_MODEL")
    or "gemini-flash-latest"
)

DEFAULT_RUNS = 3
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_DELAY_SECONDS = 1.5

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "outputs" / "diagnostics" / "gemini_health_report.json"

HEALTH_PROMPT = (
    "This is an automated API health check. "
    "Reply with exactly this text and nothing else: BAHUVU_HEALTH_OK"
)
EXPECTED_RESPONSE = "BAHUVU_HEALTH_OK"

API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/{model}:generateContent"
)

KEY_ENVIRONMENT_NAMES = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "BAHUVU_GEMINI_API_KEY",
)

KEY_PREFIXES = (
    "GEMINI_API_KEY_",
    "GOOGLE_API_KEY_",
    "BAHUVU_GEMINI_API_KEY_",
)

KEY_LIST_ENVIRONMENT_NAMES = (
    "BAHUVU_GEMINI_API_KEYS",
    "GEMINI_API_KEYS",
)


@dataclass(frozen=True)
class DiscoveredKey:
    value: str
    source: str
    variable_name: str

    @property
    def fingerprint(self) -> str:
        return mask_api_key(self.value)


@dataclass
class AttemptResult:
    attempt: int
    success: bool
    latency_seconds: float
    status_code: int | None
    category: str
    message: str
    response_text: str = ""


@dataclass
class KeyHealthResult:
    fingerprint: str
    source: str
    variable_name: str
    model: str
    status: str
    healthy: bool
    score: float
    attempts_requested: int
    attempts_completed: int
    successful_attempts: int
    success_rate: float
    average_latency_seconds: float | None
    median_latency_seconds: float | None
    minimum_latency_seconds: float | None
    maximum_latency_seconds: float | None
    categories: list[str] = field(default_factory=list)
    attempts: list[AttemptResult] = field(default_factory=list)


@dataclass
class HealthReport:
    module_version: str
    generated_at_utc: str
    model: str
    runs_per_key: int
    total_keys: int
    healthy_keys: int
    limited_keys: int
    invalid_keys: int
    unavailable_keys: int
    best_key_fingerprint: str | None
    results: list[KeyHealthResult]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_api_key(value: str) -> str:
    cleaned = value.strip()

    if not cleaned:
        return "<empty>"

    if len(cleaned) <= 8:
        return "*" * len(cleaned)

    return f"{cleaned[:4]}...{cleaned[-4:]}"


def normalize_key(value: str) -> str:
    return value.strip().strip('"').strip("'")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.exists() or not path.is_file():
        return values

    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        return values

    for raw_line in content.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        name, raw_value = line.split("=", 1)
        name = name.strip()
        value = normalize_key(raw_value)

        if name and value:
            values[name] = value

    return values


def split_key_list(value: str) -> list[str]:
    normalized = value.replace("\r", "\n").replace(";", ",")
    parts: list[str] = []

    for line in normalized.splitlines():
        parts.extend(line.split(","))

    return [
        normalize_key(part)
        for part in parts
        if normalize_key(part)
    ]


def looks_like_api_key(value: str) -> bool:
    cleaned = normalize_key(value)

    if len(cleaned) < 20:
        return False

    if any(character.isspace() for character in cleaned):
        return False

    placeholders = (
        "your-api-key",
        "your_api_key",
        "replace-me",
        "replace_me",
        "example",
        "xxxxx",
    )

    lowered = cleaned.casefold()
    return not any(token in lowered for token in placeholders)


def discover_keys(
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    environment: Mapping[str, str] | None = None,
) -> list[DiscoveredKey]:
    process_environment = dict(environment or os.environ)
    file_environment = read_env_file(env_path)

    discovered: list[DiscoveredKey] = []
    seen_values: set[str] = set()

    def add_key(value: str, source: str, variable_name: str) -> None:
        cleaned = normalize_key(value)

        if not looks_like_api_key(cleaned):
            return

        if cleaned in seen_values:
            return

        seen_values.add(cleaned)
        discovered.append(
            DiscoveredKey(
                value=cleaned,
                source=source,
                variable_name=variable_name,
            )
        )

    for source_name, values in (
        ("process-environment", process_environment),
        (".env", file_environment),
    ):
        for variable_name in KEY_ENVIRONMENT_NAMES:
            value = values.get(variable_name, "")
            if value:
                add_key(value, source_name, variable_name)

        for variable_name in KEY_LIST_ENVIRONMENT_NAMES:
            value = values.get(variable_name, "")
            for position, key_value in enumerate(split_key_list(value), start=1):
                add_key(
                    key_value,
                    source_name,
                    f"{variable_name}[{position}]",
                )

        for variable_name, value in sorted(values.items()):
            upper_name = variable_name.upper()

            if any(upper_name.startswith(prefix) for prefix in KEY_PREFIXES):
                add_key(value, source_name, variable_name)

    return discovered


def extract_response_text(payload: Mapping[str, object]) -> str:
    candidates = payload.get("candidates")

    if not isinstance(candidates, list) or not candidates:
        return ""

    first_candidate = candidates[0]

    if not isinstance(first_candidate, Mapping):
        return ""

    content = first_candidate.get("content")

    if not isinstance(content, Mapping):
        return ""

    parts = content.get("parts")

    if not isinstance(parts, list):
        return ""

    texts: list[str] = []

    for part in parts:
        if isinstance(part, Mapping):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())

    return "\n".join(texts).strip()


def safe_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else f"HTTP {response.status_code}"

    if isinstance(payload, Mapping):
        error = payload.get("error")

        if isinstance(error, Mapping):
            message = error.get("message")
            status = error.get("status")

            pieces = [
                str(piece).strip()
                for piece in (status, message)
                if str(piece).strip()
            ]

            if pieces:
                return ": ".join(pieces)[:500]

    return json.dumps(payload, ensure_ascii=False)[:500]


def classify_http_failure(status_code: int, message: str) -> str:
    lowered = message.casefold()

    if status_code in (401, 403):
        if "leak" in lowered or "reported" in lowered:
            return "leaked-or-blocked"
        return "invalid-or-forbidden"

    if status_code == 404:
        return "model-unavailable"

    if status_code == 429:
        return "quota-or-rate-limited"

    if status_code in (500, 502, 503, 504):
        return "temporary-service-error"

    if status_code == 400:
        return "bad-request"

    return "http-error"


def perform_health_attempt(
    *,
    key: DiscoveredKey,
    model: str,
    attempt_number: int,
    timeout_seconds: float,
) -> AttemptResult:
    url = API_URL_TEMPLATE.format(model=model)

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": key.value,
    }

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": HEALTH_PROMPT}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 128,
       },
    }

    started = time.perf_counter()

    try:
        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=timeout_seconds,
        )
    except requests.Timeout:
        latency = time.perf_counter() - started
        return AttemptResult(
            attempt=attempt_number,
            success=False,
            latency_seconds=round(latency, 3),
            status_code=None,
            category="timeout",
            message=f"Request exceeded {timeout_seconds:.1f} seconds.",
        )
    except requests.RequestException as exc:
        latency = time.perf_counter() - started
        return AttemptResult(
            attempt=attempt_number,
            success=False,
            latency_seconds=round(latency, 3),
            status_code=None,
            category="network-error",
            message=str(exc)[:500],
        )

    latency = time.perf_counter() - started

    if not response.ok:
        error_message = safe_error_message(response)
        return AttemptResult(
            attempt=attempt_number,
            success=False,
            latency_seconds=round(latency, 3),
            status_code=response.status_code,
            category=classify_http_failure(
                response.status_code,
                error_message,
            ),
            message=error_message,
        )

    try:
        payload = response.json()
    except ValueError:
        return AttemptResult(
            attempt=attempt_number,
            success=False,
            latency_seconds=round(latency, 3),
            status_code=response.status_code,
            category="invalid-json-response",
            message="Gemini returned a non-JSON response.",
        )

    response_text = extract_response_text(payload)
    normalized_response = response_text.strip().upper()

    if not response_text:
        candidates = payload.get("candidates", [])
        finish_reason = ""

        if isinstance(candidates, list) and candidates:
            first_candidate = candidates[0]

            if isinstance(first_candidate, Mapping):
                finish_reason = str(
                    first_candidate.get("finishReason") or ""
                ).strip()

        return AttemptResult(
            attempt=attempt_number,
            success=False,
            latency_seconds=round(latency, 3),
            status_code=response.status_code,
            category="empty-model-response",
            message=(
                "Authentication and model access succeeded, but Gemini "
                "returned no visible text. "
                f"finishReason={finish_reason or 'not provided'}"
            ),
        )

    if EXPECTED_RESPONSE not in normalized_response:
        return AttemptResult(
            attempt=attempt_number,
            success=True,
            latency_seconds=round(latency, 3),
            status_code=response.status_code,
            category="healthy-nonexact-response",
            message=(
                "Authentication, model access, and text generation "
                "succeeded, although the reply did not exactly match "
                "the requested health token."
            ),
            response_text=response_text[:200],
        )

    return AttemptResult(
        attempt=attempt_number,
        success=True,
        latency_seconds=round(latency, 3),
        status_code=response.status_code,
        category="healthy",
        message="Authentication, model access, and generation succeeded.",
        response_text=response_text[:200],
    )


def calculate_score(
    *,
    success_rate: float,
    average_latency: float | None,
    categories: Sequence[str],
) -> float:
    score = success_rate * 80.0

    if average_latency is not None:
        if average_latency <= 2.0:
            score += 20.0
        elif average_latency <= 4.0:
            score += 15.0
        elif average_latency <= 8.0:
            score += 10.0
        elif average_latency <= 15.0:
            score += 5.0

    category_set = set(categories)

    if "quota-or-rate-limited" in category_set:
        score -= 25.0

    if "temporary-service-error" in category_set:
        score -= 10.0

    if (
        "invalid-or-forbidden" in category_set
        or "leaked-or-blocked" in category_set
    ):
        score = 0.0

    return round(max(0.0, min(100.0, score)), 2)


def classify_key_status(
    *,
    success_count: int,
    runs: int,
    categories: Sequence[str],
) -> str:
    category_set = set(categories)

    if "leaked-or-blocked" in category_set:
        return "blocked"

    if "invalid-or-forbidden" in category_set:
        return "invalid"

    if "model-unavailable" in category_set:
        return "model-unavailable"

    if success_count == runs:
        return "healthy"

    if success_count > 0:
        return "degraded"

    if "quota-or-rate-limited" in category_set:
        return "limited"

    if (
        "temporary-service-error" in category_set
        or "timeout" in category_set
        or "network-error" in category_set
    ):
        return "unavailable"

    return "failed"


def evaluate_key(
    *,
    key: DiscoveredKey,
    model: str,
    runs: int,
    timeout_seconds: float,
    delay_seconds: float,
) -> KeyHealthResult:
    attempts: list[AttemptResult] = []

    for attempt_number in range(1, runs + 1):
        result = perform_health_attempt(
            key=key,
            model=model,
            attempt_number=attempt_number,
            timeout_seconds=timeout_seconds,
        )
        attempts.append(result)

        if result.category in (
            "invalid-or-forbidden",
            "leaked-or-blocked",
            "model-unavailable",
        ):
            break

        if attempt_number < runs and delay_seconds > 0:
            time.sleep(delay_seconds)

    successful_attempts = [
        attempt for attempt in attempts if attempt.success
    ]
    successful_latencies = [
        attempt.latency_seconds for attempt in successful_attempts
    ]

    success_count = len(successful_attempts)
    success_rate = success_count / runs if runs else 0.0
    categories = sorted({attempt.category for attempt in attempts})

    average_latency = (
        statistics.mean(successful_latencies)
        if successful_latencies
        else None
    )
    median_latency = (
        statistics.median(successful_latencies)
        if successful_latencies
        else None
    )
    minimum_latency = (
        min(successful_latencies)
        if successful_latencies
        else None
    )
    maximum_latency = (
        max(successful_latencies)
        if successful_latencies
        else None
    )

    status = classify_key_status(
        success_count=success_count,
        runs=runs,
        categories=categories,
    )

    score = calculate_score(
        success_rate=success_rate,
        average_latency=average_latency,
        categories=categories,
    )

    return KeyHealthResult(
        fingerprint=key.fingerprint,
        source=key.source,
        variable_name=key.variable_name,
        model=model,
        status=status,
        healthy=status == "healthy",
        score=score,
        attempts_requested=runs,
        attempts_completed=len(attempts),
        successful_attempts=success_count,
        success_rate=round(success_rate, 4),
        average_latency_seconds=(
            round(average_latency, 3)
            if average_latency is not None
            else None
        ),
        median_latency_seconds=(
            round(median_latency, 3)
            if median_latency is not None
            else None
        ),
        minimum_latency_seconds=(
            round(minimum_latency, 3)
            if minimum_latency is not None
            else None
        ),
        maximum_latency_seconds=(
            round(maximum_latency, 3)
            if maximum_latency is not None
            else None
        ),
        categories=categories,
        attempts=attempts,
    )


def rank_results(
    results: Iterable[KeyHealthResult],
) -> list[KeyHealthResult]:
    status_priority = {
        "healthy": 0,
        "degraded": 1,
        "limited": 2,
        "unavailable": 3,
        "model-unavailable": 4,
        "failed": 5,
        "blocked": 6,
        "invalid": 7,
    }

    return sorted(
        results,
        key=lambda result: (
            status_priority.get(result.status, 99),
            -result.score,
            (
                result.average_latency_seconds
                if result.average_latency_seconds is not None
                else float("inf")
            ),
            result.fingerprint,
        ),
    )


def build_report(
    *,
    model: str,
    runs: int,
    results: Sequence[KeyHealthResult],
) -> HealthReport:
    ranked_results = rank_results(results)

    healthy_results = [
        result
        for result in ranked_results
        if result.status in ("healthy", "degraded")
    ]

    return HealthReport(
        module_version=MODULE_VERSION,
        generated_at_utc=utc_now_text(),
        model=model,
        runs_per_key=runs,
        total_keys=len(ranked_results),
        healthy_keys=sum(
            result.status == "healthy"
            for result in ranked_results
        ),
        limited_keys=sum(
            result.status == "limited"
            for result in ranked_results
        ),
        invalid_keys=sum(
            result.status in ("invalid", "blocked")
            for result in ranked_results
        ),
        unavailable_keys=sum(
            result.status in (
                "unavailable",
                "model-unavailable",
                "failed",
            )
            for result in ranked_results
        ),
        best_key_fingerprint=(
            healthy_results[0].fingerprint
            if healthy_results
            else None
        ),
        results=ranked_results,
    )


def write_report(report: HealthReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            asdict(report),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def select_healthiest_key(
    discovered_keys: Sequence[DiscoveredKey],
    report: HealthReport,
) -> DiscoveredKey | None:
    usable_fingerprints = [
        result.fingerprint
        for result in report.results
        if result.status in ("healthy", "degraded")
    ]

    keys_by_fingerprint = {
        key.fingerprint: key
        for key in discovered_keys
    }

    for fingerprint in usable_fingerprints:
        selected = keys_by_fingerprint.get(fingerprint)
        if selected is not None:
            return selected

    return None


def format_latency(value: float | None) -> str:
    return f"{value:.3f}s" if value is not None else "-"


def print_report(
    report: HealthReport,
    *,
    show_key_sources: bool,
) -> None:
    print()
    print("=" * 78)
    print("BAHUVU NEWS - GEMINI API HEALTH REPORT")
    print("=" * 78)
    print(f"Monitor version : {report.module_version}")
    print(f"Model           : {report.model}")
    print(f"Keys tested     : {report.total_keys}")
    print(f"Runs per key    : {report.runs_per_key}")
    print(f"Healthy         : {report.healthy_keys}")
    print(f"Limited         : {report.limited_keys}")
    print(f"Invalid/blocked : {report.invalid_keys}")
    print(f"Unavailable     : {report.unavailable_keys}")
    print("-" * 78)

    if not report.results:
        print("No Gemini API keys were discovered.")
        print("=" * 78)
        return

    for position, result in enumerate(report.results, start=1):
        print(
            f"{position:>2}. {result.fingerprint:<16} "
            f"{result.status.upper():<18} "
            f"score={result.score:>6.2f} "
            f"success={result.successful_attempts}/"
            f"{result.attempts_requested} "
            f"avg={format_latency(result.average_latency_seconds)}"
        )

        if show_key_sources:
            print(
                f"    source={result.source}; "
                f"variable={result.variable_name}"
            )

        for attempt in result.attempts:
            marker = "PASS" if attempt.success else "FAIL"
            print(
                f"    [{marker}] attempt={attempt.attempt} "
                f"category={attempt.category} "
                f"http={attempt.status_code or '-'} "
                f"latency={attempt.latency_seconds:.3f}s"
            )

            if not attempt.success:
                print(f"           {attempt.message}")

    print("-" * 78)
    print(
        "Best key       : "
        f"{report.best_key_fingerprint or 'none available'}"
    )
    print("=" * 78)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test and rank Gemini API keys for BahuvuNewsAI."
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model to test. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"Requests per key. Default: {DEFAULT_RUNS}",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Timeout in seconds for each request. "
            f"Default: {DEFAULT_TIMEOUT_SECONDS}"
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=(
            "Delay between requests to the same key. "
            f"Default: {DEFAULT_DELAY_SECONDS}"
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help=f"Environment file. Default: {DEFAULT_ENV_PATH}",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"JSON report path. Default: {DEFAULT_REPORT_PATH}",
    )
    parser.add_argument(
        "--show-key-sources",
        action="store_true",
        help="Show variable names and key sources. Full keys remain hidden.",
    )

    arguments = parser.parse_args(argv)

    if arguments.runs < 1 or arguments.runs > 20:
        parser.error("--runs must be between 1 and 20.")

    if arguments.timeout <= 0:
        parser.error("--timeout must be greater than zero.")

    if arguments.delay < 0:
        parser.error("--delay cannot be negative.")

    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)

    keys = discover_keys(env_path=arguments.env_file)

    if not keys:
        empty_report = build_report(
            model=arguments.model,
            runs=arguments.runs,
            results=[],
        )
        write_report(empty_report, arguments.report)
        print_report(
            empty_report,
            show_key_sources=arguments.show_key_sources,
        )
        print()
        print(
            "Add GEMINI_API_KEY, GEMINI_API_KEY_2, etc. "
            "to .env and run again."
        )
        return 2

    results: list[KeyHealthResult] = []

    print(
        f"Testing {len(keys)} Gemini API key(s) sequentially "
        f"with model {arguments.model}..."
    )

    for position, key in enumerate(keys, start=1):
        print(
            f"[{position}/{len(keys)}] Testing {key.fingerprint}..."
        )

        result = evaluate_key(
            key=key,
            model=arguments.model,
            runs=arguments.runs,
            timeout_seconds=arguments.timeout,
            delay_seconds=arguments.delay,
        )
        results.append(result)

    report = build_report(
        model=arguments.model,
        runs=arguments.runs,
        results=results,
    )
    write_report(report, arguments.report)
    print_report(
        report,
        show_key_sources=arguments.show_key_sources,
    )

    print()
    print(f"JSON report: {arguments.report.resolve()}")

    selected = select_healthiest_key(keys, report)

    if selected is None:
        print("No usable Gemini key is currently available.")
        return 1

    print(
        "Selected key: "
        f"{selected.fingerprint} "
        f"from {selected.variable_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())