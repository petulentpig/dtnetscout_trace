"""dynatracedev -- stitch NetScout network data into Dynatrace PurePaths.

Every scheduling cycle the extension polls one or more NetScout endpoints for
recent network-transaction records, maps each record that carries a trace
context to an OpenTelemetry leaf span, and exports those spans to Dynatrace so
they attach to the matching PurePath. Self-monitoring counters are reported as
metrics so you can see how many records were fetched, emitted, and skipped.
"""

from __future__ import annotations

import time

from dynatrace_extension import Extension, Status, StatusValue

from .mapping import MappingConfig, MappingError, NetworkSpan, RecordMapper, dig
from .netscout import NetScoutClient, NetScoutConfig, NetScoutError
from .otlp import TraceEmitter

# Cap on how many dedup keys to remember per cycle (safety valve for huge volumes).
_MAX_SEEN_PER_CYCLE = 100_000


class ExtensionImpl(Extension):
    def query(self):
        """Scheduled every minute: poll NetScout, emit correlated spans."""
        cfg = self.activation_config
        emitter = self._get_emitter(cfg)
        # Rolling dedup: a record can appear in two consecutive fetches because the
        # lookback window overlaps the run interval. Remember this cycle and the
        # previous one so we never emit the same span (and duplicate it in the
        # trace) twice.
        seen_prev = getattr(self, "_seen_now", set())
        seen_now: set = set()

        fetched = emitted = skipped = duplicates = errors = 0
        for endpoint in cfg.get("endpoints", []):
            label = endpoint.get("name") or endpoint.get("base_url", "netscout")
            record_id_field = endpoint.get("record_id_field", "")
            try:
                records = self._fetch(endpoint)
            except NetScoutError as exc:
                self.logger.error(f"[{label}] fetch failed: {exc}")
                errors += 1
                continue

            fetched += len(records)
            mapper = RecordMapper(self._mapping_config(endpoint))
            for record in records:
                try:
                    network_span = mapper.to_span(record)
                except MappingError as exc:
                    self.logger.debug(f"[{label}] skipping record: {exc}")
                    skipped += 1
                    continue

                key = self._dedup_key(record, record_id_field, network_span)
                if key in seen_prev or key in seen_now:
                    duplicates += 1
                    continue
                if len(seen_now) < _MAX_SEEN_PER_CYCLE:
                    seen_now.add(key)

                try:
                    emitter.emit(network_span)
                    emitted += 1
                except Exception as exc:  # noqa: BLE001 - never let one span kill the cycle
                    self.logger.warning(f"[{label}] emit failed: {exc}")
                    errors += 1

        self._seen_now = seen_now

        if not emitter.flush():
            self.logger.warning("span export did not flush within the timeout")

        self.report_metric("netscout.records.fetched", fetched)
        self.report_metric("netscout.spans.emitted", emitted)
        self.report_metric("netscout.records.skipped", skipped)
        self.report_metric("netscout.records.duplicates", duplicates)
        self.report_metric("netscout.errors", errors)
        self.logger.info(
            f"netscout -> dynatrace ({emitter.target}): fetched={fetched} "
            f"emitted={emitted} skipped={skipped} duplicates={duplicates} errors={errors}"
        )

    def fastcheck(self) -> Status:
        """Validate configuration before the extension is scheduled to run."""
        cfg = self.activation_config
        endpoints = cfg.get("endpoints", [])
        if not endpoints:
            return Status(StatusValue.ERROR, "no NetScout endpoints configured")
        for endpoint in endpoints:
            if not endpoint.get("base_url"):
                return Status(StatusValue.ERROR, "a NetScout endpoint is missing base_url")
        if not cfg.get("otlp_endpoint"):
            self.logger.warning(
                "otlp_endpoint is not set; spans will be printed locally, not sent to Dynatrace"
            )
        return Status(StatusValue.OK)

    def _get_emitter(self, cfg: dict) -> TraceEmitter:
        # One long-lived emitter per process; config is static for a monitoring config.
        if getattr(self, "_emitter", None) is None:
            self._emitter = TraceEmitter(
                endpoint=cfg.get("otlp_endpoint", ""),
                api_token=cfg.get("otlp_api_token", ""),
                service_name=cfg.get("service_name", "netscout"),
            )
        return self._emitter

    @staticmethod
    def _dedup_key(record: dict, record_id_field: str, span: NetworkSpan) -> tuple:
        # Prefer a stable record id if the source provides one; otherwise fall back
        # to the span's identity (trace, parent, and time window).
        if record_id_field:
            record_id = dig(record, record_id_field)
            if record_id is not None:
                return ("id", str(record_id))
        return ("span", span.trace_id, span.parent_span_id, span.start_time_ns, span.end_time_ns)

    @staticmethod
    def _fetch(endpoint: dict) -> list[dict]:
        ns_config = NetScoutConfig(
            base_url=endpoint["base_url"],
            records_path=endpoint.get("records_path", ""),
            records_json_path=endpoint.get("records_json_path", ""),
            api_token=endpoint.get("netscout_api_token", ""),
            username=endpoint.get("netscout_username", ""),
            password=endpoint.get("netscout_password", ""),
            verify_tls=endpoint.get("verify_tls", True),
            lookback_seconds=int(endpoint.get("lookback_seconds", 120)),
        )
        client = NetScoutClient(ns_config)
        return client.fetch_records(time.time() - ns_config.lookback_seconds)

    @staticmethod
    def _mapping_config(endpoint: dict) -> MappingConfig:
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


def main():
    ExtensionImpl(name="dynatracedev").run()


if __name__ == "__main__":
    main()
