# dynatracedev — development setup

A Dynatrace Extension Framework 2.0 **Python** extension (`custom:dynatracedev`),
scaffolded with `dt-sdk create`.

## Toolchain

- **Python 3.10** — required by `dt-extensions-sdk` (`>=3.10,<3.15`) and matches the
  Dynatrace extension runtime. Provisioned via `uv` (system Python 3.9 is too old).
- **`dt-sdk`** — from the `dt-extensions-sdk[cli]` package. Scaffolds, runs, builds, signs.
- **`dt`** — from the `dt-cli` package. Used under the hood by `dt-sdk` for cert
  generation, assembling, and signing.

Both CLIs are installed globally as `uv` tools (on `~/.local/bin`):

```bash
uv python install 3.10
uv tool install "dt-extensions-sdk[cli]" --python 3.10   # provides: dt-sdk
uv tool install dt-cli --python 3.10                     # provides: dt
```

## Project environment

```bash
cd ~/Projects/dynatracedev
uv venv --python 3.10
source .venv/bin/activate
uv pip install -e ".[dev]"
uv pip install pip          # NOTE: `dt-sdk build` shells out to `python -m pip wheel`,
                            # and uv venvs don't include pip by default.
```

## Signing certificates

Dev certs live in `~/.dynatrace/certificates/` (CA + developer.pem), generated once:

```bash
dt-sdk gencerts
```

To run a signed extension in a real environment, the CA cert (`ca.pem`) must be
uploaded to the Dynatrace tenant's credential vault.

## Common commands

```bash
dt-sdk run      # run the extension locally in simulation (uses activation.json + secrets.json)
dt-sdk build    # download deps -> assemble -> sign -> dist/custom_dynatracedev-<ver>.zip
dt-sdk lint     # ruff check
dt-sdk format   # ruff format
dt-sdk upload   # upload the signed zip to a Dynatrace environment
```

## Building for deployment (Linux wheels)

The Dynatrace ActiveGate/OneAgent Python runtime is **Linux**. A plain `dt-sdk
build` on macOS bundles macOS wheels (e.g. `protobuf-...-macosx`), which will not
load on the runtime. For a deployable artifact, download Linux wheels:

```bash
dt-sdk build -e manylinux2014_x86_64 -p 3.10 -o
```

- `-e/--extra-platform` — target platform tag
- `-p/--python-version` — runtime Python (3.10)
- `-o/--only-extra-platforms` — skip the host (macOS) wheels

## Dynatrace token scope

Path A sends spans to the OTLP trace-ingest API, which requires an API token with
the **`openTelemetryTrace.ingest`** scope. Endpoint:
`https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/traces` (HTTP + protobuf only).

## Layout

- `dynatracedev/__main__.py` — extension entrypoint (`ExtensionImpl`: `query()`, `fastcheck()`).
- `dynatracedev/netscout.py` — generic NetScout REST client.
- `dynatracedev/mapping.py` — record → span mapping + trace-context parsing.
- `dynatracedev/otlp.py` — builds leaf spans with a remote parent context, exports via OTLP.
- `scripts/demo_emit.py` — local proof of the mapping+emit path (console exporter).
- `extension/extension.yaml` — extension manifest (name, version, runtime).
- `extension/activationSchema.json` — config schema shown in the Dynatrace UI.
- `activation.json` / `secrets.json` — local config for `dt-sdk run` (`secrets.json` is gitignored).
- `setup.py` — version is read from `extension/extension.yaml`.

Bump the version in `extension/extension.yaml` for each release.
