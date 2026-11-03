# cli-mcp

**Swagger for Command Line Tools**

`cli-mcp` exposes command-line applications through a
[Model Context Protocol](https://modelcontextprotocol.io) (MCP) server — without you
writing a single line of MCP code.

Like Swagger/OpenAPI describes an HTTP API, cli-mcp describes CLI commands, their arguments,
and their results as structured tools. It also executes those tools with argument validation
and configured execution controls, and can export OpenAPI documentation.
Automatic discovery depends on the CLI's help format or supported framework; use a manifest
when explicit metadata is needed. Windows `.bat`/`.cmd` targets are not supported.

```text
Today:      CLI Tool  ->  custom MCP wrapper  ->  MCP client
With cli-mcp: CLI Tool ->  cli-mcp             ->  MCP client
```

```bash
cli-mcp expose git
cli-mcp expose kubectl
cli-mcp expose docker
cli-mcp expose opcua-nodeset-linker
```

```text
✓ Binary detected
✓ Commands discovered
✓ Schemas generated
✓ MCP tools published
✓ MCP server started
```

Works with Claude, Copilot, Cursor, VS Code, Cline, Roo Code, Open WebUI and any other
MCP-compatible client.

---

## Install

Requires Python 3.13 or newer. CI covers Windows and Linux with Python 3.13 and 3.14.

```bash
pip install cli-mcp
```

or, for development:

```bash
git clone https://github.com/AndreasHeine/cli-mcp
cd cli-mcp
uv sync --extra dev
uv run cli-mcp --help
```

## Quick start

Only expose trusted programs. These quick-start examples do **not** enable read-only mode
or sandboxing; discovery itself runs help commands on the host.

```bash
# Discover commands and serve them over stdio (the default transport)
cli-mcp expose git

# Look at the generated tools without starting a server
cli-mcp inspect kubectl

# Serve over Streamable HTTP
cli-mcp serve docker --transport streamable-http --port 8801

# Export machine-readable artefacts
cli-mcp export git -o tools.md
cli-mcp export-schema git -o schemas.json
cli-mcp export-openapi git -o openapi.json

# Validate discovery quality
cli-mcp doctor git

# Generate a configuration template
cli-mcp init opcua-nodeset-linker -o cli-mcp.yaml
```

Client configuration (`.mcp.json`, Claude Desktop, Cursor, VS Code, …):

The following is a common client configuration shape; VS Code and other clients may use
different keys. See [clients.md](docs/clients.md) for client-specific recipes.

```json
{
  "mcpServers": {
    "git": {
      "command": "cli-mcp",
      "args": ["serve", "git"]
    },
    "docker": {
      "url": "http://127.0.0.1:8801/mcp"
    }
  }
}
```

---

## Working directory and Windows shells

Some CLIs resolve paths inside their input configuration relative to the process working
directory, not relative to that configuration file. Configure an absolute existing directory
for both discovery and execution:

```yaml
binary: my-cli
execution:
  cwd: 'C:\projects\my-cli'
```

Without `execution.cwd`, the launch directory is used. Use an absolute manifest path when
changing the discovery directory. Configuration and tool definitions are loaded at startup:
restart the server and reconnect the client after changes.

PowerShell:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\projects\cli-mcp\.venv\Scripts\python.exe' -B -m cli_mcp.cli.main expose --config 'C:\projects\cli-mcp\cli-mcp.yaml'
```

cmd.exe (run these as two separate commands):

```bat
set PYTHONDONTWRITEBYTECODE=1
"C:\projects\cli-mcp\.venv\Scripts\python.exe" -B -m cli_mcp.cli.main expose --config "C:\projects\cli-mcp\cli-mcp.yaml"
```

These examples assume an existing development environment at the shown location.

---

## How discovery works

`cli-mcp` tries discovery strategies in order. The first strategy that yields usable commands
wins; manifest entries then add tools or replace discovered tools with the same name.
The final include/exclude filters select which tools are published, not which help commands
may execute.

Import reflection is **disabled by default** and requires `--allow-reflection` or
`discovery.allow_import_reflection: true`. It may execute target code.
`discovery.max_depth` limits the recursive walk; `discovery.max_commands` limits both published
tools and uncached help invocations, including root queries, failures and fallback flags.
The help budget is checked before spawning processes; cache hits do not consume it.

| Strategy | How it works | Frameworks |
| --- | --- | --- |
| **Native reflection** | Inspects the real command objects in the target process | Python: argparse, click, typer · Node.js: commander.js |
| **Framework help grammars** | Parses framework-specific help output with type/default/required semantics | Go: cobra · Rust: clap · .NET: System.CommandLine · Node.js: yargs · click · argparse |
| **Generic help parsing** | Recursive `tool --help` / `tool <command> --help` parser | anything with `--help` |
| **Manifest file** | User-provided YAML metadata, authoritative for matching tool names | supported executables and scripts |

Every discovered command becomes an MCP tool:

```json
{
  "name": "reduce",
  "description": "Reduce an OPC UA nodeset",
  "inputSchema": {
    "type": "object",
    "properties": {
      "input": { "type": "string", "description": "Input nodeset file" },
      "output": { "type": "string", "description": "Reduced nodeset file" }
    },
    "required": ["input", "output"]
  }
}
```

Calling the tool executes the original CLI:

```bash
linker reduce --input model.xml --output reduced.xml
```

and returns:

```json
{
  "stdout": "...",
  "stderr": "",
  "exitCode": 0,
  "executionTimeMs": 125,
  "argv": ["linker", "reduce", "--input", "model.xml", "--output", "reduced.xml"],
  "sandboxed": false,
  "truncated": false
}
```

The actual `argv` contains the resolved launch command, including interpreter prefixes where
needed. A connected client or completed MCP call does not prove CLI success: inspect `exitCode`
and `stderr`. Exitcode 0 does not establish side-effect freedom; `sandboxed: false` means the
target ran on the host.

---

## Security

Security is a first-class concern, not an afterthought.

```yaml
binary: opcua-nodeset-linker

security:
  allowlist: [git, kubectl, docker, opcua-nodeset-linker]
  readonly: true          # deny unless the complete argv is explicitly listed
  readonly_argv: []       # configure verified exact invocations before use
  approval: true          # human confirmation required
  timeout_seconds: 30
  max_output_bytes: 200000
  sandbox:
    backend: docker
    image: my-cli-image:latest
    network: false
```

- **Allow list** — a non-empty list restricts configured binaries by basename;
  an empty list permits the configured binary. This is not an OS permission boundary.
- **Read-only mode** — only explicitly listed complete argv vectors may execute;
  known risky commands and flags are additionally blocked. An empty `readonly_argv` blocks
  every execution and triggers a startup warning; publishing tools does not authorize them.
- **Approval mode** — `auto`/`prompt` require a local human at a terminal; without a TTY
  approval-required execution is refused. Clients cannot approve their own calls. Legacy
  `explicit` refuses approval-required calls. Normal stdio clients do not provide a local TTY.
- **Sandboxing** — run the CLI inside Docker or Podman; the default working-directory
  mount is writable. Discovery still runs on the host. Firecracker support planned.
- **Argument validation** — arguments are validated against the generated JSON schema
  before the requested tool process is spawned. Arguments are not interpolated into
  a shell string.

Read-only, approval and sandboxing are opt-in. Exact argv permissions do not prove that a
program, its environment or its input files are harmless. Discovery is outside tool execution
guards. Output limits bound retained stdout/stderr, not the target's own CPU or memory use.
HTTP/SSE defaults to loopback and does not configure authentication or TLS; do not expose it
publicly without appropriate protection.

Windows batch targets (`.bat`/`.cmd`) are rejected. Output is retained within a byte budget,
including timeouts. See [security.md](docs/security.md) for limitations, configuration migration,
and non-invasive Windows/Linux tests using a single loopback ping.

---

## Architecture

Clean architecture, one responsibility per package:

```text
src/cli_mcp/
├── cli/            # Typer entry point (expose/inspect/serve/export/doctor/init)
├── discovery/      # provider protocol + strategies
├── schema/         # JSON Schema, Markdown docs, OpenAPI
├── executor/       # argv building, subprocess execution, approval, sandbox
├── mcp/            # MCPServer assembly, tool adapters
├── security/       # allow list, read-only rules, access policy
├── config/         # pydantic settings + YAML loading
├── transport/      # stdio, HTTP, Streamable HTTP, SSE
└── plugins/        # entry-point based provider discovery
```

Dependencies point inward: the CLI depends on discovery/schema/executor/security; the MCP
layer depends on nothing framework-specific. See
[docs/architecture.md](docs/architecture.md).

---

## Plugin system

Third parties add discovery providers without touching core code:

```python
from cli_mcp.discovery.base import DiscoveryContext, DiscoveryResult, TargetInfo


class MyProvider:
    name = "my-framework"
    strategy = "help"
    frameworks = ("my-framework",)

    def supports(self, target: TargetInfo) -> bool:
        return target.framework == "my-framework"

    def discover(self, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        ...  # return CommandSpecs
```

Register it:

```toml
[project.entry-points."cli_mcp.discovery"]
my-framework = "my_pkg.provider:MyProvider"
```

`cli-mcp providers` lists every registered provider.

---

## Development

```bash
uv run ruff check .
uv run mypy src
uv run pytest            # unit + integration + e2e, coverage gate at 90%
pre-commit run --all-files
```

The full test suite creates temporary files and runs Git integration commands.
For non-invasive validation without test caches, coverage files or generated target scripts,
use the focused Windows/Linux commands in [security.md](docs/security.md).

GitHub Actions run lint, type checking, Windows/Linux tests (Python 3.13/3.14), and
distribution builds on pushes to `master`/`main` and pull requests. CI can also be started
manually from the Actions tab. Dependencies are installed from the checked-in lockfile.

Published GitHub releases (or a manual Release workflow run) validate and build distributions,
then upload wheels and source distributions as workflow artifacts. **PyPI publishing is
disabled** until a publishing account and trusted publisher are explicitly configured.

---

## Examples

- [`examples/cli-mcp.yaml`](examples/cli-mcp.yaml) — full configuration
- [`examples/sample-clis/`](examples/sample-clis) — small argparse/click/typer/commander apps used by the tests

## Documentation

- [configuration.md](docs/configuration.md) — every config key and CLI flag
- [discovery.md](docs/discovery.md) — reflection, help parsing and manifests
- [security.md](docs/security.md) — allow list, read-only, approval, sandboxing
- [transports.md](docs/transports.md) — stdio, HTTP, Streamable HTTP, SSE
- [clients.md](docs/clients.md) — configuration recipes for Claude, VS Code, Cursor, Cline, Open WebUI
- [plugins.md](docs/plugins.md) — adding a discovery provider for a new framework
- [architecture.md](docs/architecture.md) — how the pipeline fits together

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
