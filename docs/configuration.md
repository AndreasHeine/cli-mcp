# Configuration

cli-mcp reads YAML configuration from `cli-mcp.yaml`, `cli-mcp.yml` or `.cli-mcp.yaml`
in the current directory. Pass an explicit file with `--config <path>`. Both shapes work:
a flat document, or everything nested under a top-level `cli-mcp:` key.

Generate a commented starting point:

```bash
cli-mcp init git --readonly --transport streamable-http --sandbox-image alpine:3.20
```

## Full reference

| Key | Default | Meaning |
| --- | --- | --- |
| `binary` | required | CLI to expose: a name on `PATH`, or a path to a script. |
| `mcp.transport` | `stdio` | `stdio`, `http`, `streamable-http` or `sse`. |
| `mcp.host` | `127.0.0.1` | Bind host for HTTP transports. |
| `mcp.port` | `8801` | Bind port for HTTP transports. |
| `mcp.path` | `/mcp` | Endpoint path for HTTP transports. |
| `mcp.name` | derived from `binary` | MCP server name reported in `initialize`. |
| `mcp.title`, `mcp.description`, `mcp.instructions` | unset | Server metadata shown to clients. |
| `mcp.version` | `0.1.0` | Server version string. |
| `mcp.include_docs_tool` | `true` | Also publish a `<binary>_docs` tool returning Markdown. |
| `mcp.tool_prefix` | `false` | Prefix tool names with the binary name. |
| `mcp.json_response` | `false` | Stream JSON instead of SSE events (HTTP transports). |
| `mcp.stateless_http` | `false` | No session state between requests. |
| `security.allowlist` | unset | Binaries that may run at all; empty means "the configured binary". |
| `security.readonly` | `false` | Reject destructive verbs, dangerous argv and blocked binaries. |
| `security.approval` | `false` | Ask for approval before risky commands. |
| `security.approval_mode` | `auto` | `auto`, `prompt` or `explicit`. |
| `security.block_patterns` | `[]` | Substrings in the final argv that are always rejected. |
| `security.allow_patterns` | `[]` | Substrings that override read-only and block patterns. |
| `security.timeout_seconds` | `60` | Hard limit per executed command. |
| `security.max_output_bytes` | `200000` | Output is truncated past this size. |
| `security.sandbox.backend` | `docker` | `docker` or `podman`. |
| `security.sandbox.image` | `alpine:3.20` | Container image the command runs in. |
| `security.sandbox.network` | `false` | Attach the container network. |
| `security.sandbox.workdir_mount` | `true` | Mount the working directory at `/work`. |
| `security.sandbox.container_workdir` | `/work` | Working directory inside the container. |
| `security.sandbox.extra_args` | `[]` | Extra arguments for the container runtime. |
| `discovery.strategies` | `[reflection, help, manifest]` | Ordered strategies to try. |
| `discovery.include` | unset | Only expose these command names. |
| `discovery.exclude` | unset | Never expose these command names. |
| `discovery.max_depth` | `2` | How deep to walk subcommands. |
| `discovery.max_commands` | `120` | Cap on published tools. |
| `discovery.allow_import_reflection` | `false` | Allow reflection, which imports or executes the target. |
| `discovery.help_timeout_seconds` | `10` | Timeout for each `--help` invocation. |
| `manifest` | unset | Inline manifest tools; see below. |

## Command-line overrides

Every flag overrides the config file, and only flags you pass are applied:

```bash
cli-mcp expose git --transport http --port 8802 --readonly --approval \
  --allow git --include status --include diff --max-depth 1 --timeout 30
```

`--transport`, `--host`, `--port`, `--readonly/--no-readonly`, `--approval/--no-approval`,
`--approval-mode`, `--allow`, `--timeout`, `--include`, `--exclude`, `--max-depth`,
`--allow-reflection`, `--tool-prefix`, `--docs/--no-docs`, `--config`.

## Manifest: declaring tools by hand

Discovery is automatic, but a manifest wins. Use it for wrappers whose `--help` output
cli-mcp cannot read, or to expose only a chosen few commands:

```yaml
cli-mcp:
  binary: opcua-nodeset-linker
  tools:
    - name: reduce
      path: [reduce]
      description: Reduce a nodeset file to the aliases it uses.
      parameters:
        - name: input
          kind: option
          cli_name: input
          type: string
          required: true
        - name: output
          kind: option
          cli_name: output
          type: string
          required: true
        - name: verbose
          kind: flag
          cli_name: verbose
          description: Include detail.
```

`kind` is `option`, `flag` or `positional`. Flags are always published as booleans,
whatever the manifest says. Argument names are snake_case identifiers; the CLI spelling
lives in `cli_name`.
