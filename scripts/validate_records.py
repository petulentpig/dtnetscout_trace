"""Validate NetScout records against the extension's mapping -- no Dynatrace needed.

For the NetScout team: run this against a sample of your API response to confirm
each record has what Dynatrace needs (a trace context + timestamps). It reports,
per record, whether it would become a span or be skipped and why -- so you can
verify your data *before* the extension is ever pointed at a live Dynatrace tenant.

Usage:
    python scripts/validate_records.py examples/sample-netscout-response.json

The mapping is read from the first endpoint in activation.json, so edit that file
to match your field names, then re-run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dynatracedev.mapping import MappingConfig, MappingError, RecordMapper

ROOT = Path(__file__).resolve().parent.parent


def load_endpoint_config() -> dict:
    activation = json.loads((ROOT / "activation.json").read_text())
    section = activation.get("pythonRemote") or activation.get("pythonLocal") or {}
    endpoints = section.get("endpoints") or []
    if not endpoints:
        sys.exit("activation.json has no endpoints to read a mapping from")
    return endpoints[0]


def mapping_config(endpoint: dict) -> MappingConfig:
    raw_attrs = endpoint.get("attribute_fields", "")
    attribute_fields = tuple(part.strip() for part in raw_attrs.split(",") if part.strip())
    return MappingConfig(
        traceparent_field=endpoint.get("traceparent_field", "traceparent"),
        trace_id_field=endpoint.get("trace_id_field", ""),
        parent_span_id_field=endpoint.get("parent_span_id_field", ""),
        start_time_field=endpoint.get("start_time_field", "start_time"),
        end_time_field=endpoint.get("end_time_field", "end_time"),
        time_format=endpoint.get("time_format", "epoch_ms"),
        span_name_field=endpoint.get("span_name_field", "name"),
        span_name_default=endpoint.get("span_name_default", "netscout.network"),
        attribute_fields=attribute_fields,
    )


def extract_records(payload, records_json_path: str) -> list:
    if records_json_path:
        for part in records_json_path.split("."):
            payload = payload.get(part) if isinstance(payload, dict) else None
    if isinstance(payload, dict):
        return [payload]
    return payload if isinstance(payload, list) else []


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/validate_records.py <records.json>")

    endpoint = load_endpoint_config()
    mapper = RecordMapper(mapping_config(endpoint))
    payload = json.loads(Path(sys.argv[1]).read_text())
    records = extract_records(payload, endpoint.get("records_json_path", ""))

    if not records:
        sys.exit("no records found (check records_json_path in activation.json)")

    ok = skipped = 0
    for index, record in enumerate(records):
        try:
            span = mapper.to_span(record)
        except MappingError as exc:
            skipped += 1
            print(f"[{index}] SKIP  {exc}")
            continue
        ok += 1
        duration_ms = (span.end_time_ns - span.start_time_ns) / 1_000_000
        print(
            f"[{index}] OK    name={span.name!r} "
            f"trace_id={span.trace_id:032x} parent={span.parent_span_id:016x} "
            f"dur={duration_ms:.1f}ms attrs={len(span.attributes)}"
        )

    print(f"\n{ok} would attach to a trace, {skipped} skipped, {len(records)} total")
    if skipped:
        print("Skipped records lack a usable trace context or timestamps -- see reasons above.")


if __name__ == "__main__":
    main()
