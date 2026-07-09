# dynatracedev

A Dynatrace Extension Framework 2.0 (Python) extension that pulls **NetScout**
network-transaction data and stitches it into existing **Dynatrace PurePath
traces** as OpenTelemetry leaf spans.

## What it does

Each scheduling cycle the extension:

1. Polls one or more NetScout endpoints (nGeniusONE-style REST API) for recent
   network-transaction records.
2. Maps each record that carries a **trace context** to an OpenTelemetry span,
   using the NetScout observation's own start/end timestamps.
3. Exports the span to Dynatrace via OTLP so it **attaches to the matching
   PurePath** — surfacing network-level detail (RTT, retransmissions, packet
   loss, network vs. app time) right inside the distributed trace.

It also reports self-monitoring metrics: `netscout.records.fetched`,
`netscout.spans.emitted`, `netscout.records.skipped`, `netscout.errors`.

## How the trace stitching works (Path A)

Dynatrace only merges externally-ingested OpenTelemetry spans into a OneAgent
PurePath when the span is a **leaf** that carries a valid parent context — you
cannot splice a span *between* OneAgent spans. So each span is created with a
*remote* parent `SpanContext` built from the record's trace context:

- `trace_id` ← the PurePath's trace-id (32 hex)
- parent `span_id` ← the OneAgent span the NetScout observation relates to (16 hex)
- a fresh child span-id is generated, `SAMPLED` flag set
- start/end times come from the NetScout record, not wall-clock

See `dynatracedev/otlp.py` (`TraceEmitter`) and `dynatracedev/mapping.py`.

### ⚠️ Hard requirement & caveats

- **NetScout must expose the trace context per record** — either a W3C
  `traceparent`, or a `trace_id` + `parent_span_id` pair that matches what
  OneAgent produced. Records without a usable parent span-id are **skipped**
  (counted in `netscout.records.skipped`), because they can't be attached to a
  PurePath. This shared identifier is the whole basis of Path A; if NetScout
  can't provide it, this approach can't correlate at the trace level.
- **Timing matters.** Spans carry their real observation timestamps. Very late
  arrivals may fall outside Dynatrace's trace-completion window and not merge.
- **One-way, leaf-only.** The extension adds spans; it never modifies OneAgent
  spans. Keep NetScout spans as leaves per Dynatrace guidance.
- Do **not** also enable the OneAgent OpenTelemetry Span Sensor for the same
  data, or you'll get duplicate spans.

## Configuration

Configured per monitoring configuration (see `activationSchema.json`). Top level:

| Field | Description |
|-------|-------------|
| `otlp_endpoint` | `https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/traces` (or ActiveGate `:9999/e/{env}/...`). Blank = print spans to the log instead of sending. |
| `otlp_api_token` | Dynatrace API token with the **`openTelemetryTrace.ingest`** scope. |
| `service_name` | OTel `service.name` on emitted spans. |
| `endpoints[]` | One or more NetScout sources (below). |

Per NetScout source:

| Field | Description |
|-------|-------------|
| `base_url`, `records_path`, `records_json_path` | Where to fetch records and where the array lives in the JSON. |
| `netscout_api_token` / `netscout_username`+`netscout_password` | Auth (bearer or basic). |
| `verify_tls`, `lookback_seconds` | TLS verification; how far back to query each cycle. |
| `traceparent_field` **or** `trace_id_field` + `parent_span_id_field` | Where the trace context lives in each record. |
| `start_time_field`, `end_time_field`, `time_format` | Timestamps (`epoch_ms` / `epoch_s` / `epoch_ns` / `iso8601`). |
| `span_name_field`, `span_name_default` | Span name source and fallback. |
| `attribute_fields` | Comma-separated record fields to copy onto the span as `netscout.*` attributes. |

> The NetScout REST request shape (query params, paging) is a generic default in
> `dynatracedev/netscout.py` — adjust `fetch_records()` to your product/version.

## Local development

```bash
source .venv/bin/activate
python scripts/demo_emit.py   # prove mapping+emit with a sample record (console exporter)
dt-sdk run                    # run against activation.json / secrets.json
```

With `otlp_endpoint` blank, spans print to the log — no Dynatrace tenant needed.

## Build & deploy

```bash
# Local (macOS) build — for local checks only:
dt-sdk build

# Deployment build: the Dynatrace runtime is Linux, so download Linux wheels.
dt-sdk build -e manylinux2014_x86_64 -p 3.10 -o

# Then upload the signed dist/custom_dynatracedev-<ver>.zip (dt-sdk upload,
# or the Extensions UI). The dev CA (~/.dynatrace/certificates/ca.pem) must be
# in the tenant credential vault for a self-signed build to be accepted.
```

Bump `version` in `extension/extension.yaml` before each build.

See `DEVELOPMENT.md` for the toolchain setup.
