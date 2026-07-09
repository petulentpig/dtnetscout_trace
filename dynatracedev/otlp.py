"""Emit NetScout-derived leaf spans into existing Dynatrace PurePaths via OTLP.

Each span is created with a *remote* parent :class:`SpanContext` reconstructed
from the NetScout record's trace context, so it shares the PurePath's trace-id
and hangs off the OneAgent span as a leaf -- the only shape Dynatrace supports
for externally-ingested spans. Timestamps come from the NetScout observation, not
from wall-clock at emit time, so the span lands at the correct point in the
trace's timeline.

If no Dynatrace endpoint/token is configured, spans are printed to the console
instead (useful for ``dt-sdk run`` and local development).
"""

from __future__ import annotations

from opentelemetry import trace as ot_trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    TraceFlags,
)

from .mapping import NetworkSpan


def _dynatrace_exporter(endpoint: str, api_token: str) -> SpanExporter:
    # Imported lazily so console-only mode has no hard dependency on the exporter.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(
        endpoint=endpoint,
        headers={"Authorization": f"Api-Token {api_token}"},
    )


class TraceEmitter:
    """Builds spans that attach to existing Dynatrace traces and exports them."""

    def __init__(self, endpoint: str, api_token: str, service_name: str = "netscout"):
        resource = Resource.create(
            {
                "service.name": service_name or "netscout",
                "telemetry.sdk.name": "dynatracedev-netscout",
            }
        )
        self._provider = TracerProvider(resource=resource)
        if endpoint and api_token:
            exporter: SpanExporter = _dynatrace_exporter(endpoint, api_token)
            self.target = endpoint
        else:
            exporter = ConsoleSpanExporter()
            self.target = "console"
        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        self._tracer = self._provider.get_tracer("dynatracedev.netscout")

    def emit(self, network_span: NetworkSpan) -> None:
        parent = self._remote_parent(network_span.trace_id, network_span.parent_span_id)
        span = self._tracer.start_span(
            name=network_span.name,
            context=parent,
            kind=SpanKind.CLIENT,
            start_time=network_span.start_time_ns,
            attributes=network_span.attributes,
        )
        span.end(end_time=network_span.end_time_ns)

    def flush(self, timeout_millis: int = 30_000) -> bool:
        return self._provider.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self._provider.shutdown()

    @staticmethod
    def _remote_parent(trace_id: int, span_id: int) -> Context:
        span_context = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=True,
            # SAMPLED is required or ParentBased sampling drops the span.
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        return ot_trace.set_span_in_context(NonRecordingSpan(span_context))
