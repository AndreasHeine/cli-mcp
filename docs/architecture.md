# Architecture

cli-mcp turns a binary into an MCP server in four steps: resolve, discover, schema, serve.
Each step is a module with one job, and every step can be replaced without touching the others.

```
src/cli_mcp/
  version.py        package version
  errors.py         error hierarchy: ConfigError, BinaryNotFoundError, DiscoveryError,
                    SchemaError, SecurityViolation, ApprovalRequired, ExecutionError, TransportError
  models.py         Parameter, CommandSpec, DiscoveryResult, identifier normalisation
  detect.py         binary resolution, script vs executable, framework fingerprint
  core.py           orchestration: settings + detection + discovery -> PreparedCli
  config/           settings model, YAML loader, template generator
  discovery/        providers, registry, help grammar, framework grammars, reflection, manifest
  schema/           JSON Schema, argument validation, Markdown docs, OpenAPI export
  executor/         argv building, subprocess runner, timeouts, sandbox, approval gate
  security/         read-only rules, access policy
  mcp/              tool adapter, server construction, schema pinning
  transport/        stdio / HTTP / Streamable HTTP / SSE
  cli/              the cli-mcp command line
  plugins/          third-party provider loading
```

## The pipeline

1. **Resolve** — `detect.resolve_binary` finds the binary on `PATH` or as a path, classifies it
   as an executable or a script and fingerprints its framework from `--help` output.
   Script targets are launched through an interpreter (`launch_for`), so a `.py` script runs as
   `python script.py`, not as a direct process.
2. **Discover** — the provider registry runs the configured strategies in order
   (`reflection`, `help`, `manifest`). The first provider that returns a `DiscoveryResult` wins;
   a manifest merges into whatever discovery found and can replace it.
   `include`/`exclude` filter the result and `max_commands` caps it, with a warning telling you what happened.
3. **Schema** — `schema/jsonschema.py` turns each `CommandSpec` into an MCP `inputSchema`
   with `additionalProperties: false`; `schema/validate.py` coerces and rejects arguments
   *before* the process is spawned, so an unknown argument never reaches the CLI.
4. **Serve** — `mcp/tool_adapter.py` wraps a command as a handler with a synthesised signature,
   `mcp/server.py` publishes it on an `MCPServer` and pins the exact schema, and
   `transport/run_server` wires the transport.

## Handler order

Every tool call runs in this order, and nothing after a denial executes:

```
validate arguments -> build argv -> access policy -> approval gate -> subprocess -> JSON result
```

The result is `{stdout, stderr, exitCode, executionTimeMs}`, so a client can tell a failing
command from a rejected one.

## Why schemas are pinned

The MCP SDK derives a tool schema from the handler's Python signature. cli-mcp synthesises that
signature from discovery metadata, then replaces the derived schema with its own, so descriptions,
enums, defaults and `additionalProperties: false` survive exactly as discovered. Extra keys are
rejected by cli-mcp's validator, because the SDK silently drops them.
