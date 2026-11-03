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
| `execution.cwd` | unset | Absolute existing directory for discovery and tool execution; otherwise the launch directory is used. |
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
| `security.readonly` | `false` | Deny execution unless its full argv exactly matches `readonly_argv`; known destructive invocations still rejected. |
| `security.readonly_argv` | `[]` | Operator-approved full argv vectors, including executable path and all arguments; empty denies every read-only invocation. |
| `security.approval` | `false` | Require local human approval for every command (classified risky commands always require it). |
| `security.approval_mode` | `auto` | `auto`/`prompt` require a local TTY; legacy `explicit` always refuses approval-required execution. |
| `security.block_patterns` | `[]` | Substrings in the final argv that are always rejected. |
| `security.allow_patterns` | `[]` | Regex overrides for custom block patterns outside read-only mode only. |
| `security.timeout_seconds` | `60` | Hard limit per executed command. |
| `security.max_output_bytes` | `200000` | Maximum retained raw bytes per output stream, including timeouts. |
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
| `discovery.max_commands` | `120` | Cap on published tools and total uncached help invocations per discovery context (including root and fallback calls). |
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

For a short-only option use `short: n` without a `cli_name`, or set `short_only: true`
alongside its short spelling. It is emitted as `-n`, not `--n`.

Read-only is intentionally restrictive: adding `--readonly` alone now blocks every tool
execution until exact invocations are configured. Client-supplied `approve: true` is no
longer an approval mechanism. See [security.md](security.md) for migration and safe tests.

## Working directory and restart

An absolute target configuration filename does not make paths inside that file absolute.
The target CLI decides how its relative paths are resolved. Set `execution.cwd` explicitly
when it expects paths relative to a project root:

```yaml
execution:
  cwd: 'C:\projects\nodeset-linker'
```

The server reads its configuration and discovers tools at startup. Restart it after changes
to working directory, tools or read-only permissions; reconnect the MCP client afterwards.
Use an absolute `manifest` path when changing the discovery working directory.

Windows PowerShell:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\projects\cli-mcp\.venv\Scripts\python.exe' -B -m cli_mcp.cli.main expose --config 'C:\projects\cli-mcp\cli-mcp.yaml'
```

Windows cmd.exe (two separate commands; PowerShell syntax does not apply):

```bat
set PYTHONDONTWRITEBYTECODE=1
"C:\projects\cli-mcp\.venv\Scripts\python.exe" -B -m cli_mcp.cli.main expose --config "C:\projects\cli-mcp\cli-mcp.yaml"
```
