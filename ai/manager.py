"""
BahuvuNewsAI unified AI manager.

This module exposes the single public AI interface used by the rest of the
BahuvuNewsAI application.

The manager owns:

* Provider initialization.
* Provider registration.
* Provider routing.
* Synchronous and asynchronous generation.
* Translation, summarization, classification, script generation, and
  editorial-polishing convenience methods.
* Batch execution.
* Health reporting.
* Metrics.
* Startup and shutdown lifecycle.
* Safe automatic fallback from Gemini to the deterministic offline provider.

Application modules should depend on ``AIManager`` instead of importing Gemini
or offline providers directly.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from ai.providers.base import (
    BaseAIProvider,
    ProviderCapability,
    ProviderOperationalStatus,
    read_object_field,
    utc_now_iso,
)
from ai.router import (
    AIProviderRouter,
    AIRouterError,
    RouterConfiguration,
    RoutingMode,
    RoutingResult,
    create_default_router,
)


__all__ = [
    "AIManagerState",
    "AIManagerConfiguration",
    "AIManagerRequest",
    "AIManagerResult",
    "AIManagerError",
    "AIManagerNotStartedError",
    "AIManager",
    "create_ai_manager",
    "get_default_ai_manager",
    "shutdown_default_ai_manager",
]


MODULE_NAME = "BahuvuNewsAI unified AI manager"
MODULE_VERSION = "1.0.0"


class AIManagerState(str, Enum):
    """Lifecycle state of the AI manager."""

    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AIManagerConfiguration:
    """Unified AI manager configuration."""

    include_gemini: bool = True
    include_offline: bool = True
    auto_start: bool = True
    require_at_least_one_provider: bool = True
    perform_startup_health_checks: bool = False
    routing: RouterConfiguration = field(
        default_factory=RouterConfiguration
    )

    def __post_init__(self) -> None:
        if (
            self.require_at_least_one_provider
            and not self.include_gemini
            and not self.include_offline
        ):
            raise ValueError(
                "At least one AI provider must be enabled"
            )


@dataclass(frozen=True, slots=True)
class AIManagerRequest:
    """
    Generic request accepted by ``AIManager``.

    Canonical request objects from ``ai.models`` may also be supplied directly.
    """

    request_id: str
    task: str
    prompt: str
    provider: str | None = None
    model: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    routing_mode: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    structured_output: bool = False
    categories: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AIManagerResult:
    """Manager-level result containing output and routing diagnostics."""

    request_id: str
    status: str
    task: str
    text: str
    provider: str
    model: str | None
    created_at: str
    used_fallback: bool
    routing_attempts: int
    response: Any
    routing_result: RoutingResult
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Return whether the manager request succeeded."""

        return self.status == "success"

    @property
    def content(self) -> str:
        """Compatibility alias."""

        return self.text

    @property
    def output_text(self) -> str:
        """Compatibility alias."""

        return self.text


class AIManagerError(RuntimeError):
    """Base exception for manager failures."""


class AIManagerNotStartedError(AIManagerError):
    """Raised when generation is attempted before startup."""


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _response_text(response: Any) -> str:
    value = read_object_field(
        response,
        "text",
        "content",
        "output_text",
        "result",
        default="",
    )

    return str(value or "")


def _response_status(response: Any) -> str:
    value = read_object_field(
        response,
        "status",
        "response_status",
        default="success",
    )

    return str(_enum_value(value) or "success").lower()


def _response_model(response: Any) -> str | None:
    value = read_object_field(
        response,
        "model",
        "model_name",
        default=None,
    )

    if value is None:
        return None

    return str(_enum_value(value))


def _request_id(request: Any) -> str:
    value = read_object_field(
        request,
        "request_id",
        "id",
        default=None,
    )

    if value:
        return str(value)

    return f"ai_manager_{utc_now_iso().replace(':', '').replace('-', '')}"


def _request_task(request: Any) -> str:
    value = read_object_field(
        request,
        "task",
        "task_type",
        "operation",
        default="text_generation",
    )

    return str(_enum_value(value) or "text_generation").lower()


class AIManager:
    """
    Public AI service facade for BahuvuNewsAI.

    One manager instance may be shared safely across application modules.
    """

    def __init__(
        self,
        configuration: AIManagerConfiguration | None = None,
        *,
        router: AIProviderRouter | None = None,
    ) -> None:
        self.configuration = (
            configuration or AIManagerConfiguration()
        )

        self._router = router
        self._state = AIManagerState.CREATED
        self._lock = threading.RLock()
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._last_error: str | None = None
        self._generation_count = 0
        self._successful_count = 0
        self._failed_count = 0

        if self.configuration.auto_start:
            self.start()

    @property
    def state(self) -> AIManagerState:
        """Return the current manager lifecycle state."""

        with self._lock:
            return self._state

    @property
    def router(self) -> AIProviderRouter:
        """Return the active provider router."""

        if self._router is None:
            raise AIManagerNotStartedError(
                "AI manager router is not initialized"
            )

        return self._router

    @property
    def ready(self) -> bool:
        """Return whether generation may currently be performed."""

        return self.state in {
            AIManagerState.READY,
            AIManagerState.DEGRADED,
        }

    def start(self) -> None:
        """Initialize providers and make the manager ready."""

        with self._lock:
            if self._state in {
                AIManagerState.READY,
                AIManagerState.DEGRADED,
            }:
                return

            if self._state is AIManagerState.STARTING:
                return

            self._state = AIManagerState.STARTING

        try:
            if self._router is None:
                self._router = create_default_router(
                    include_gemini=(
                        self.configuration.include_gemini
                    ),
                    include_offline=(
                        self.configuration.include_offline
                    ),
                    configuration=self.configuration.routing,
                )

            provider_count = len(self._router.provider_names())

            if (
                self.configuration.require_at_least_one_provider
                and provider_count == 0
            ):
                raise AIManagerError(
                    "No AI providers were initialized"
                )

            state = AIManagerState.READY

            if self.configuration.perform_startup_health_checks:
                report = self._router.health_report()
                healthy_count = sum(
                    1
                    for provider in report.values()
                    if provider["healthy"]
                )

                if healthy_count == 0:
                    raise AIManagerError(
                        "No AI provider passed startup health checks"
                    )

                if healthy_count < provider_count:
                    state = AIManagerState.DEGRADED

            with self._lock:
                self._state = state
                self._started_at = utc_now_iso()
                self._stopped_at = None
                self._last_error = None

        except Exception as error:
            with self._lock:
                self._state = AIManagerState.FAILED
                self._last_error = str(error)

            raise

    def ensure_started(self) -> None:
        """Start automatically when permitted or raise a clear error."""

        if self.ready:
            return

        if self.state in {
            AIManagerState.CREATED,
            AIManagerState.STOPPED,
        }:
            self.start()

        if not self.ready:
            raise AIManagerNotStartedError(
                f"AI manager is not ready; state={self.state.value}"
            )

    def register_provider(
        self,
        provider: BaseAIProvider[Any, Any],
        *,
        replace: bool = False,
    ) -> None:
        """Register a provider with the manager router."""

        self.ensure_started()
        self.router.register(provider, replace=replace)

    def unregister_provider(
        self,
        provider_name: str,
    ) -> BaseAIProvider[Any, Any] | None:
        """Remove a provider from the router."""

        self.ensure_started()
        return self.router.unregister(provider_name)

    def providers(self) -> tuple[str, ...]:
        """Return active provider names."""

        self.ensure_started()
        return self.router.provider_names()

    def generate_with_details(
        self,
        request: Any,
    ) -> AIManagerResult:
        """Generate an AI response with routing diagnostics."""

        self.ensure_started()

        with self._lock:
            self._generation_count += 1

        try:
            routing_result = self.router.route_with_details(
                request
            )
            response = routing_result.response

            result = AIManagerResult(
                request_id=_request_id(request),
                status=_response_status(response),
                task=_request_task(request),
                text=_response_text(response),
                provider=routing_result.selected_provider,
                model=_response_model(response),
                created_at=utc_now_iso(),
                used_fallback=routing_result.used_fallback,
                routing_attempts=len(routing_result.attempts),
                response=response,
                routing_result=routing_result,
                metadata={
                    "manager_version": MODULE_VERSION,
                    "capability": (
                        routing_result.capability.value
                    ),
                    "routing_mode": (
                        routing_result.mode.value
                    ),
                },
            )

            with self._lock:
                self._successful_count += 1
                self._last_error = None

            return result

        except Exception as error:
            with self._lock:
                self._failed_count += 1
                self._last_error = str(error)

            raise

    def generate(self, request: Any) -> Any:
        """Generate and return only the provider response."""

        return self.generate_with_details(request).response

    async def generate_with_details_async(
        self,
        request: Any,
    ) -> AIManagerResult:
        """Asynchronously generate with routing diagnostics."""

        self.ensure_started()

        with self._lock:
            self._generation_count += 1

        try:
            routing_result = (
                await self.router.route_with_details_async(request)
            )
            response = routing_result.response

            result = AIManagerResult(
                request_id=_request_id(request),
                status=_response_status(response),
                task=_request_task(request),
                text=_response_text(response),
                provider=routing_result.selected_provider,
                model=_response_model(response),
                created_at=utc_now_iso(),
                used_fallback=routing_result.used_fallback,
                routing_attempts=len(routing_result.attempts),
                response=response,
                routing_result=routing_result,
                metadata={
                    "manager_version": MODULE_VERSION,
                    "capability": (
                        routing_result.capability.value
                    ),
                    "routing_mode": (
                        routing_result.mode.value
                    ),
                },
            )

            with self._lock:
                self._successful_count += 1
                self._last_error = None

            return result

        except Exception as error:
            with self._lock:
                self._failed_count += 1
                self._last_error = str(error)

            raise

    async def generate_async(self, request: Any) -> Any:
        """Asynchronously generate and return only the response."""

        result = await self.generate_with_details_async(request)
        return result.response

    def _build_request(
        self,
        *,
        task: str,
        prompt: str,
        request_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        routing_mode: RoutingMode | str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        structured_output: bool = False,
        categories: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIManagerRequest:
        """Build a generic manager request."""

        resolved_routing_mode: str | None

        if isinstance(routing_mode, RoutingMode):
            resolved_routing_mode = routing_mode.value
        elif routing_mode is None:
            resolved_routing_mode = None
        else:
            resolved_routing_mode = str(routing_mode)

        return AIManagerRequest(
            request_id=(
                request_id
                or f"ai_manager_request_{utc_now_iso()}"
            ),
            task=task,
            prompt=prompt,
            provider=provider,
            model=model,
            source_language=source_language,
            target_language=target_language,
            routing_mode=resolved_routing_mode,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            structured_output=structured_output,
            categories=tuple(categories or ()),
            metadata=dict(metadata or {}),
        )

    def translate(
        self,
        text: str,
        *,
        source_language: str = "en",
        target_language: str = "te",
        provider: str | None = None,
        model: str | None = None,
        routing_mode: RoutingMode | str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIManagerResult:
        """Translate text through the unified provider system."""

        request = self._build_request(
            task="translation",
            prompt=text,
            provider=provider,
            model=model,
            source_language=source_language,
            target_language=target_language,
            routing_mode=routing_mode,
            metadata=metadata,
        )

        return self.generate_with_details(request)

    def summarize(
        self,
        text: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        routing_mode: RoutingMode | str | None = None,
        structured_output: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIManagerResult:
        """Summarize news content."""

        request = self._build_request(
            task="summarization",
            prompt=text,
            provider=provider,
            model=model,
            routing_mode=routing_mode,
            structured_output=structured_output,
            metadata=metadata,
        )

        return self.generate_with_details(request)

    def classify(
        self,
        text: str,
        *,
        categories: Sequence[str] | None = None,
        provider: str | None = None,
        routing_mode: RoutingMode | str | None = None,
        structured_output: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIManagerResult:
        """Classify news content."""

        request = self._build_request(
            task="classification",
            prompt=text,
            provider=provider,
            routing_mode=routing_mode,
            structured_output=structured_output,
            categories=categories,
            metadata=metadata,
        )

        return self.generate_with_details(request)

    def polish(
        self,
        text: str,
        *,
        provider: str | None = None,
        routing_mode: RoutingMode | str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIManagerResult:
        """Polish a broadcast-news script."""

        request = self._build_request(
            task="editorial_polishing",
            prompt=text,
            provider=provider,
            routing_mode=routing_mode,
            metadata=metadata,
        )

        return self.generate_with_details(request)

    def generate_script(
        self,
        text: str,
        *,
        provider: str | None = None,
        routing_mode: RoutingMode | str | None = None,
        max_output_tokens: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIManagerResult:
        """Generate a broadcast-news script."""

        request = self._build_request(
            task="script_generation",
            prompt=text,
            provider=provider,
            routing_mode=routing_mode,
            max_output_tokens=max_output_tokens,
            metadata=metadata,
        )

        return self.generate_with_details(request)

    def generate_batch(
        self,
        requests: Sequence[Any],
        *,
        stop_on_error: bool = False,
    ) -> list[AIManagerResult | Exception]:
        """Generate a sequence of requests."""

        results: list[AIManagerResult | Exception] = []

        for request in requests:
            try:
                results.append(
                    self.generate_with_details(request)
                )
            except Exception as error:
                if stop_on_error:
                    raise
                results.append(error)

        return results

    async def generate_batch_async(
        self,
        requests: Sequence[Any],
        *,
        maximum_concurrency: int = 4,
        stop_on_error: bool = False,
    ) -> list[AIManagerResult | Exception]:
        """Generate requests concurrently."""

        if maximum_concurrency < 1:
            raise ValueError(
                "maximum_concurrency must be at least 1"
            )

        semaphore = asyncio.Semaphore(maximum_concurrency)

        async def run_one(
            request: Any,
        ) -> AIManagerResult | Exception:
            async with semaphore:
                try:
                    return await self.generate_with_details_async(
                        request
                    )
                except Exception as error:
                    if stop_on_error:
                        raise
                    return error

        return list(
            await asyncio.gather(
                *(run_one(request) for request in requests)
            )
        )

    def health_report(self) -> dict[str, Any]:
        """Return manager and provider health information."""

        self.ensure_started()
        provider_report = self.router.health_report()

        healthy_count = sum(
            1
            for value in provider_report.values()
            if value["healthy"]
        )

        provider_count = len(provider_report)

        if provider_count == 0:
            overall_status = ProviderOperationalStatus.UNAVAILABLE
        elif healthy_count == provider_count:
            overall_status = ProviderOperationalStatus.HEALTHY
        elif healthy_count > 0:
            overall_status = ProviderOperationalStatus.DEGRADED
        else:
            overall_status = ProviderOperationalStatus.UNAVAILABLE

        return {
            "manager_state": self.state.value,
            "overall_status": overall_status.value,
            "provider_count": provider_count,
            "healthy_provider_count": healthy_count,
            "checked_at": utc_now_iso(),
            "providers": provider_report,
        }

    def metrics(self) -> dict[str, Any]:
        """Return manager, router, and provider metrics."""

        self.ensure_started()

        with self._lock:
            manager_metrics = {
                "generation_count": self._generation_count,
                "successful_count": self._successful_count,
                "failed_count": self._failed_count,
                "success_rate": (
                    (
                        self._successful_count
                        / self._generation_count
                        * 100.0
                    )
                    if self._generation_count
                    else 0.0
                ),
                "started_at": self._started_at,
                "stopped_at": self._stopped_at,
                "last_error": self._last_error,
            }

        return {
            "manager": manager_metrics,
            **self.router.metrics(),
        }

    def describe(self) -> dict[str, Any]:
        """Return a serializable manager description."""

        return {
            "module_name": MODULE_NAME,
            "module_version": MODULE_VERSION,
            "state": self.state.value,
            "configuration": {
                **asdict(self.configuration),
                "routing": {
                    **asdict(self.configuration.routing),
                    "mode": (
                        self.configuration.routing.mode.value
                    ),
                },
            },
            "providers": list(self.providers()),
            "metrics": self.metrics(),
        }

    def stop(self) -> None:
        """Close provider resources and stop the manager."""

        with self._lock:
            if self._state is AIManagerState.STOPPED:
                return

            self._state = AIManagerState.STOPPING

        try:
            if self._router is not None:
                self._router.close()

            with self._lock:
                self._state = AIManagerState.STOPPED
                self._stopped_at = utc_now_iso()

        except Exception as error:
            with self._lock:
                self._state = AIManagerState.FAILED
                self._last_error = str(error)

            raise

    close = stop

    def __enter__(self) -> AIManager:
        self.ensure_started()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        del exception_type, exception, traceback
        self.stop()

    async def __aenter__(self) -> AIManager:
        self.ensure_started()
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        del exception_type, exception, traceback
        self.stop()


def create_ai_manager(
    *,
    include_gemini: bool = True,
    include_offline: bool = True,
    auto_start: bool = True,
    routing_mode: RoutingMode = RoutingMode.AUTOMATIC,
    default_provider: str | None = "gemini",
    fallback_provider: str | None = "offline",
    allow_fallback: bool = True,
    perform_startup_health_checks: bool = False,
) -> AIManager:
    """Create the standard BahuvuNewsAI AI manager."""

    configuration = AIManagerConfiguration(
        include_gemini=include_gemini,
        include_offline=include_offline,
        auto_start=auto_start,
        perform_startup_health_checks=(
            perform_startup_health_checks
        ),
        routing=RouterConfiguration(
            mode=routing_mode,
            default_provider=default_provider,
            fallback_provider=fallback_provider,
            allow_fallback=allow_fallback,
            check_health_before_routing=False,
            allow_unknown_health=True,
            allow_degraded_providers=True,
        ),
    )

    return AIManager(configuration)


_DEFAULT_MANAGER: AIManager | None = None
_DEFAULT_MANAGER_LOCK = threading.RLock()


def get_default_ai_manager() -> AIManager:
    """Return the process-wide default AI manager."""

    global _DEFAULT_MANAGER

    with _DEFAULT_MANAGER_LOCK:
        if _DEFAULT_MANAGER is None:
            _DEFAULT_MANAGER = create_ai_manager()

        return _DEFAULT_MANAGER


def shutdown_default_ai_manager() -> None:
    """Stop and clear the process-wide default manager."""

    global _DEFAULT_MANAGER

    with _DEFAULT_MANAGER_LOCK:
        if _DEFAULT_MANAGER is not None:
            _DEFAULT_MANAGER.stop()
            _DEFAULT_MANAGER = None


def _run_self_test() -> None:
    """Execute the manager self-test entirely offline."""

    manager = create_ai_manager(
        include_gemini=False,
        include_offline=True,
        routing_mode=RoutingMode.OFFLINE_ONLY,
        default_provider="offline",
        fallback_provider="offline",
    )

    translation = manager.translate(
        "Officials issued a warning over continuing heavy rainfall.",
        source_language="en",
        target_language="te",
    )

    summary = manager.summarize(
        (
            "Heavy rain continued across several districts. "
            "Officials issued a warning. "
            "Emergency teams were deployed. "
            "Residents were advised to remain cautious."
        )
    )

    classification = manager.classify(
        "The cricket team won the final match of the tournament.",
        categories=("sports", "politics", "business"),
    )

    polished = manager.polish(
        "officials  said that heavy rain will continue"
    )

    script = manager.generate_script(
        (
            "Heavy rain continued in several districts. "
            "Officials issued a weather warning."
        )
    )

    health = manager.health_report()
    metrics = manager.metrics()

    assert manager.state is AIManagerState.READY
    assert manager.providers() == ("offline",)

    assert translation.success
    assert translation.provider == "offline"
    assert "హెచ్చరిక" in translation.text

    assert summary.success
    assert summary.text.startswith("Heavy rain continued")

    assert classification.success
    assert classification.provider == "offline"
    assert classification.response.structured_data is not None
    assert (
        classification.response.structured_data["category"]
        == "sports"
    )

    assert polished.success
    assert polished.text.startswith("Officials")
    assert polished.text.endswith(".")

    assert script.success
    assert "బహువు న్యూస్‌కు స్వాగతం" in script.text

    assert health["overall_status"] == "healthy"
    assert health["provider_count"] == 1
    assert health["healthy_provider_count"] == 1

    assert metrics["manager"]["generation_count"] == 5
    assert metrics["manager"]["successful_count"] == 5
    assert metrics["manager"]["failed_count"] == 0
    assert metrics["manager"]["success_rate"] == 100.0

    print(MODULE_NAME)
    print(f"Module version : {MODULE_VERSION}")
    print(f"Manager state  : {manager.state.value}")
    print(f"Providers      : {', '.join(manager.providers())}")
    print(f"Translation    : {translation.text}")
    print(f"Summary        : {summary.text}")
    print(
        "Classification : "
        f"{classification.response.structured_data['category']}"
    )
    print(f"Polished text  : {polished.text}")
    print(f"Script provider: {script.provider}")
    print(
        "Health status  : "
        f"{health['overall_status']}"
    )
    print(
        "Success rate   : "
        f"{metrics['manager']['success_rate']:.2f}%"
    )
    print("Unified AI manager self-test passed.")

    manager.stop()
    assert manager.state is AIManagerState.STOPPED


if __name__ == "__main__":
    _run_self_test()