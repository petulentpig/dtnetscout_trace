"""Map raw NetScout network-transaction records to OTel-ready leaf spans.

NetScout products (nGeniusONE, Omnis, etc.) expose network transaction data with
product-specific field names, so the mapping from a raw record to a span is
driven by configuration (:class:`MappingConfig`) rather than hard-coded.

For Path A -- stitching a span into an existing Dynatrace PurePath -- each record
MUST carry the trace context of the OneAgent span it relates to, either as a W3C
``traceparent`` header or as separate trace-id / parent-span-id fields. Without a
parent span-id we cannot attach the span as a leaf of the PurePath, so such
records are rejected (and counted as skipped) rather than emitted as orphans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_TRACEPARENT_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_INVALID_ID = 0


class MappingError(Exception):
    """A record could not be turned into a valid, attachable span."""


@dataclass
class NetworkSpan:
    """A NetScout observation normalized for emission as an OTel leaf span."""

    trace_id: int
    parent_span_id: int
    name: str
    start_time_ns: int
    end_time_ns: int
    attributes: dict


@dataclass
class MappingConfig:
    """How to read a NetScout record. All field names are dot-paths into the JSON."""

    # Trace context: either a traceparent field, or explicit id fields.
    traceparent_field: str = "traceparent"
    trace_id_field: str = ""
    parent_span_id_field: str = ""
    # Timing.
    start_time_field: str = "start_time"
    end_time_field: str = "end_time"
    time_format: str = "epoch_ms"  # epoch_ms | epoch_s | epoch_ns | iso8601
    # Naming + attributes.
    span_name_field: str = "name"
    span_name_default: str = "netscout.network"
    attribute_fields: tuple[str, ...] = field(default_factory=tuple)
    attribute_prefix: str = "netscout."


def dig(record: dict, path: str):
    """Return the value at a dot-separated ``path`` within ``record`` (or None)."""
    cur = record
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def parse_traceparent(value: str) -> tuple[int, int]:
    """Return ``(trace_id, parent_span_id)`` from a W3C ``traceparent`` value."""
    match = _TRACEPARENT_RE.match(value.strip().lower())
    if not match:
        raise MappingError(f"invalid traceparent: {value!r}")
    trace_id = int(match.group(2), 16)
    span_id = int(match.group(3), 16)
    if trace_id == _INVALID_ID or span_id == _INVALID_ID:
        raise MappingError("traceparent has an all-zero trace or span id")
    return trace_id, span_id


def _hex_to_int(value: str, width: int, label: str) -> int:
    cleaned = value.strip().lower().removeprefix("0x")
    if len(cleaned) != width:
        raise MappingError(f"{label} must be {width} hex chars, got {value!r}")
    parsed = int(cleaned, 16)
    if parsed == _INVALID_ID:
        raise MappingError(f"{label} is all-zero: {value!r}")
    return parsed


def to_epoch_ns(value, time_format: str) -> int:
    """Convert a timestamp value in ``time_format`` to epoch nanoseconds."""
    if time_format == "epoch_ms":
        return int(float(value) * 1_000_000)
    if time_format == "epoch_s":
        return int(float(value) * 1_000_000_000)
    if time_format == "epoch_ns":
        return int(value)
    if time_format == "iso8601":
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    raise MappingError(f"unknown time_format: {time_format!r}")


def _attr_value(value):
    # OTel attributes must be str/bool/int/float (or sequences thereof).
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


class RecordMapper:
    """Turn raw NetScout records into :class:`NetworkSpan` objects."""

    def __init__(self, config: MappingConfig):
        self.config = config

    def to_span(self, record: dict) -> NetworkSpan:
        cfg = self.config
        trace_id, parent_span_id = self._trace_context(record)
        start_ns = self._time(record, cfg.start_time_field)
        end_ns = self._time(record, cfg.end_time_field) if cfg.end_time_field else start_ns
        if end_ns < start_ns:
            end_ns = start_ns
        name = dig(record, cfg.span_name_field) or cfg.span_name_default
        attributes = {}
        for name_path in cfg.attribute_fields:
            value = dig(record, name_path)
            if value is not None:
                attributes[f"{cfg.attribute_prefix}{name_path}"] = _attr_value(value)
        return NetworkSpan(
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=str(name),
            start_time_ns=start_ns,
            end_time_ns=end_ns,
            attributes=attributes,
        )

    def _trace_context(self, record: dict) -> tuple[int, int]:
        cfg = self.config
        if cfg.trace_id_field:
            raw_trace = dig(record, cfg.trace_id_field)
            if raw_trace is None:
                raise MappingError(f"missing trace-id field {cfg.trace_id_field!r}")
            trace_id = _hex_to_int(str(raw_trace), 32, "trace id")
            raw_parent = dig(record, cfg.parent_span_id_field) if cfg.parent_span_id_field else None
            if not raw_parent:
                raise MappingError("no parent span-id; cannot attach a leaf span to the PurePath")
            parent_span_id = _hex_to_int(str(raw_parent), 16, "parent span id")
            return trace_id, parent_span_id
        raw_tp = dig(record, cfg.traceparent_field)
        if not raw_tp:
            raise MappingError(f"missing traceparent field {cfg.traceparent_field!r}")
        return parse_traceparent(str(raw_tp))

    def _time(self, record: dict, field_name: str) -> int:
        raw = dig(record, field_name)
        if raw is None:
            raise MappingError(f"missing time field {field_name!r}")
        return to_epoch_ns(raw, self.config.time_format)
