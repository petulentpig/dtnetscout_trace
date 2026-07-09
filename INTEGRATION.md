# NetScout → Dynatrace integration guide

**Audience:** the NetScout team. This assumes you know NetScout well and Dynatrace
not at all. It explains exactly what this integration needs *from your side* and
how to verify your data before anything touches Dynatrace.

---

## 1. What we're trying to do (in plain terms)

Dynatrace records **distributed traces** — for a single user request, a trace is
the end-to-end timeline of every service that handled it. Each step in that
timeline is a **span**. Dynatrace's agent ("OneAgent") sees the application side
(service A called service B, which took 40 ms), but it has **no visibility into
the network** between them.

You have exactly what it's missing: RTT, retransmissions, packet loss, network vs.
application time. This integration takes a NetScout network-transaction record and
adds it into the matching Dynatrace trace as one more span — so an engineer looking
at a slow request can see *"the 40 ms was mostly network: 3 retransmissions, 0.5%
loss"* right there in the trace.

## 2. The one thing that makes this possible: the trace context

To drop a network record into the *correct* trace, we need to know **which trace
and which step** it belongs to. Two identifiers do that:

- **trace id** — 32 hex characters. Identifies the whole trace.
- **span id** — 16 hex characters. Identifies the specific step (the app call your
  packets belong to).

These are the **W3C Trace Context** standard. On the wire they travel together as a
single HTTP request header called **`traceparent`**, formatted like this:

```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^  ^--------- trace id ---------^  ^-- span id --^  ^ flags
             |
             version (always 00 today)
```

**This is the linchpin.** If a NetScout record carries the `traceparent` that was
on that connection, we can attach it to the right trace. If it doesn't, we can't —
that record gets skipped.

### Where does `traceparent` come from?

Dynatrace's OneAgent can be configured to **stamp a `traceparent` header on the
application's outgoing HTTP requests** (Dynatrace setting: *Send W3C Trace Context
HTTP headers*). Once that's on, the header is present in the actual network traffic
you already inspect. **Your job is to extract that `traceparent` header via DPI and
include it on the corresponding network-transaction record.**

> Action item for the joint kickoff: confirm with the Dynatrace admin that *Send
> W3C Trace Context HTTP headers* is enabled, and confirm on your side that your
> NetScout product can surface the `traceparent` HTTP header for the flows we care
> about. If both are true, this works. If either is missing, let's talk before you
> build anything.

If your records can't carry `traceparent` but *can* carry the trace id and span id
as separate fields, that works too — see `trace_id_field` / `parent_span_id_field`
in the config.

## 3. What each record must contain

Minimum, per network-transaction record:

| Needs | Why | Example |
|-------|-----|---------|
| **Trace context** | attach to the right trace/step | `traceparent`: `00-4bf9...4736-00f0...02b7-01` |
| **Start time** | place the span on the timeline | `start_time_ms`: `1720000000000` |
| **End time** | span duration (optional; omit = zero-length) | `end_time_ms`: `1720000000042` |
| A name (optional) | label in the UI | `transaction_name`: `"checkout-svc -> orders-db"` |
| Any metrics you want visible | the actual value-add | `retransmissions`, `network_rtt_ms`, `packet_loss_pct`, ... |
| A stable record id (optional) | avoids duplicates across polls | `record_id`: `"ns-000001"` |

A complete example is in [`examples/sample-netscout-response.json`](examples/sample-netscout-response.json).
The response can be a bare JSON array, or an array nested under a key (we point at
it with `records_json_path`).

## 4. How we read your data (field mapping)

The extension doesn't assume your field names — you tell it which field is which in
`activation.json` (and, in production, the Dynatrace config screen). Defaults match
the sample file:

| Your data | Config setting | Sample value |
|-----------|----------------|--------------|
| API path returning recent records | `records_path` | `/api/v1/network-transactions` |
| Key the array lives under | `records_json_path` | `data` |
| Trace context field | `traceparent_field` | `traceparent` |
| …or split id fields | `trace_id_field` + `parent_span_id_field` | — |
| Start / end time fields | `start_time_field` / `end_time_field` | `start_time_ms` / `end_time_ms` |
| Time unit | `time_format` | `epoch_ms` (also `epoch_s`, `epoch_ns`, `iso8601`) |
| Name field | `span_name_field` | `transaction_name` |
| Metrics to attach | `attribute_fields` (comma-separated) | `retransmissions,network_rtt_ms,...` |
| Stable id for de-duplication | `record_id_field` | `record_id` |

Metrics you list in `attribute_fields` show up on the span prefixed with
`netscout.` (e.g. `network_rtt_ms` → `netscout.network_rtt_ms`).

## 5. Verify your data — no Dynatrace required

You can check your export against the mapping locally. Point the validator at a
saved sample of your API response:

```bash
python scripts/validate_records.py examples/sample-netscout-response.json
```

Expected output for the sample (2 good records, 1 intentionally missing a
`traceparent`):

```
[0] OK    name='checkout-svc -> orders-db' trace_id=4bf9...4736 parent=00f0...02b7 dur=42.0ms attrs=7
[1] OK    name='web -> checkout-svc' trace_id=4bf9...4736 parent=a1b2...0718 dur=25.0ms attrs=7
[2] SKIP  missing traceparent field 'traceparent'

2 would attach to a trace, 1 skipped, 3 total
```

Swap in a file of your **real** records and adjust `activation.json` to your field
names until everything you expect shows `OK`. When your data validates cleanly,
you're done — hand it back and we wire it to the live tenant.

## 6. What you do *not* need to do

- You don't need a Dynatrace account, API token, or the SDK to validate your data.
- You don't need to send anything to Dynatrace — the extension does that.
- You don't need to match timestamps to anything; just report the real observed
  times in a consistent unit.

## 7. Gotchas

- **No `traceparent`, no attachment.** Records without a usable trace context are
  skipped by design (counted, not errored). This is the most common reason a record
  "doesn't show up."
- **Report promptly.** Spans carry their real observed timestamps; a record
  surfaced long after the request happened may arrive too late to merge. Fresher is
  better.
- **Consistent time unit.** Pick one (`epoch_ms` is typical) and use it for both
  start and end.
- **Duplicates.** If your API returns the same record on successive polls, provide
  `record_id` so we can de-duplicate; otherwise we de-dupe on trace/span/time, which
  is usually enough.
