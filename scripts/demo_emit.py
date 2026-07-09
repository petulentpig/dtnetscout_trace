"""Local demo: prove a NetScout record becomes a span attached to a trace.

Runs the real mapping + emit path against a hand-written sample record, using the
ConsoleSpanExporter (no Dynatrace needed). The printed span should show the same
trace_id as the sample traceparent and a parent_id equal to its span-id -- i.e.
it would attach as a leaf of that PurePath.

    python scripts/demo_emit.py
"""

from __future__ import annotations

from dynatracedev.mapping import MappingConfig, RecordMapper
from dynatracedev.otlp import TraceEmitter

# A OneAgent span this NetScout observation relates to.
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN_ID = "00f067aa0ba902b7"

SAMPLE_RECORD = {
    "traceparent": f"00-{TRACE_ID}-{PARENT_SPAN_ID}-01",
    "transaction_name": "checkout-db network segment",
    "start_time_ms": 1_720_000_000_000,
    "end_time_ms": 1_720_000_000_042,
    "src_ip": "10.0.1.7",
    "dst_ip": "10.0.2.19",
    "dst_port": 5432,
    "retransmissions": 3,
    "network_rtt_ms": 12.4,
    "packet_loss_pct": 0.5,
    "app_response_time_ms": 41.8,
}

CONFIG = MappingConfig(
    traceparent_field="traceparent",
    start_time_field="start_time_ms",
    end_time_field="end_time_ms",
    time_format="epoch_ms",
    span_name_field="transaction_name",
    attribute_fields=(
        "src_ip",
        "dst_ip",
        "dst_port",
        "retransmissions",
        "network_rtt_ms",
        "packet_loss_pct",
        "app_response_time_ms",
    ),
)


def main() -> None:
    span = RecordMapper(CONFIG).to_span(SAMPLE_RECORD)
    print(f"mapped trace_id      = {span.trace_id:032x}  (expected {TRACE_ID})")
    print(f"mapped parent_span_id= {span.parent_span_id:016x}  (expected {PARENT_SPAN_ID})")
    print("--- exported span (ConsoleSpanExporter) ---")
    emitter = TraceEmitter(endpoint="", api_token="")  # console mode
    emitter.emit(span)
    emitter.flush()
    emitter.shutdown()


if __name__ == "__main__":
    main()
