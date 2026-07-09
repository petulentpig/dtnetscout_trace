"""Executable spec for the record -> span mapping (the NetScout contract).

Run: pytest
"""

from __future__ import annotations

import pytest

from dynatracedev.mapping import MappingConfig, MappingError, RecordMapper, parse_traceparent

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"


def test_parse_traceparent():
    trace_id, span_id = parse_traceparent(f"00-{TRACE_ID}-{SPAN_ID}-01")
    assert trace_id == int(TRACE_ID, 16)
    assert span_id == int(SPAN_ID, 16)


def test_traceparent_record_maps_to_leaf_span():
    record = {
        "traceparent": f"00-{TRACE_ID}-{SPAN_ID}-01",
        "name": "db call",
        "start_time_ms": 1_720_000_000_000,
        "end_time_ms": 1_720_000_000_042,
        "rtt": 12.4,
    }
    config = MappingConfig(
        attribute_fields=("rtt",), start_time_field="start_time_ms", end_time_field="end_time_ms"
    )
    span = RecordMapper(config).to_span(record)
    assert span.trace_id == int(TRACE_ID, 16)
    assert span.parent_span_id == int(SPAN_ID, 16)
    assert span.name == "db call"
    assert span.end_time_ns - span.start_time_ns == 42_000_000
    assert span.attributes == {"netscout.rtt": 12.4}


def test_explicit_trace_and_span_id_fields():
    record = {"tid": TRACE_ID, "pid": SPAN_ID, "start_time": 1_720_000_000}
    config = MappingConfig(
        trace_id_field="tid", parent_span_id_field="pid", time_format="epoch_s", end_time_field=""
    )
    span = RecordMapper(config).to_span(record)
    assert span.trace_id == int(TRACE_ID, 16)
    assert span.parent_span_id == int(SPAN_ID, 16)
    assert span.start_time_ns == span.end_time_ns  # no end field -> zero duration


def test_iso8601_timestamps():
    record = {
        "traceparent": f"00-{TRACE_ID}-{SPAN_ID}-01",
        "start_time": "2024-07-03T09:46:40Z",
        "end_time": "2024-07-03T09:46:40.042Z",
    }
    span = RecordMapper(MappingConfig(time_format="iso8601")).to_span(record)
    assert span.end_time_ns - span.start_time_ns == 42_000_000


def test_missing_trace_context_is_rejected():
    record = {"name": "x", "start_time": 1, "end_time": 2}
    with pytest.raises(MappingError):
        RecordMapper(MappingConfig()).to_span(record)


def test_trace_id_field_without_parent_span_id_is_rejected():
    record = {"tid": TRACE_ID, "start_time": 1}
    config = MappingConfig(trace_id_field="tid", parent_span_id_field="pid")
    with pytest.raises(MappingError):
        RecordMapper(config).to_span(record)


def test_all_zero_ids_are_rejected():
    zero_trace = "0" * 32
    zero_span = "0" * 16
    with pytest.raises(MappingError):
        parse_traceparent(f"00-{zero_trace}-{zero_span}-01")


def test_end_before_start_is_clamped():
    record = {
        "traceparent": f"00-{TRACE_ID}-{SPAN_ID}-01",
        "start_time_ms": 1_720_000_000_100,
        "end_time_ms": 1_720_000_000_000,
    }
    config = MappingConfig(start_time_field="start_time_ms", end_time_field="end_time_ms")
    span = RecordMapper(config).to_span(record)
    assert span.end_time_ns == span.start_time_ns
