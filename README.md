# cli-mcp

**Swagger for Command Line Tools**

`cli-mcp` turns any command-line application into a fully compliant
[Model Context Protocol](https://modelcontextprotocol.io) (MCP) server — without you
writing a single line of MCP code.

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

```bash
pip install cli-mcp
```

or, for development:

```bash
git clone https://github.com/anthony-chirco/cli-mcp
cd cli-mcp
uv sync --extra dev
uv run cli-mcp --help
```

## Quick start

```bash
# Discover commands and serve them over stdio (the default transport)
cli-mcp expose git

# Look at the generated tools without starting a server
cli-mcp inspect kubectl

# Serve over Streamable HTTP
cli-mcp serve docker --transport streamable-http --port 8801

# Export machine-readable artefacts
cli-mcp export git -o tools.json
cli-mcp export-schema git -o schemas.json
cli-mcp export-openapi git -o openapi.json

# Validate discovery quality
cli-mcp doctor git

# Generate a configuration template
cli-mcp init --binary opcua-nodeset-linker -o cli-mcp.yaml
```

Client configuration (`.mcp.json`, Claude Desktop, Cursor, VS Code, …):

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

## How discovery works

`cli-mcp` runs discovery strategies in order and merges the results. The first strategy
that yields usable commands wins; a manifest always overrides discovery.

| Strategy | How it works | Frameworks |
| --- | --- | --- |
| **Native reflection** | Inspects the real command objects in the target process | Python: argparse, click, typer · Node.js: commander.js |
| **Framework help grammars** | Parses framework-specific help output with type/default/required semantics | Go: cobra · Rust: clap · .NET: System.CommandLine · Node.js: yargs · click · argparse |
| **Generic help parsing** | Recursive `tool --help` / `tool <command> --help` parser | anything with `--help` |
| **Manifest file** | User-provided YAML metadata, always authoritative | anything |

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
{ "stdout": "...", "stderr": "...", "exitCode": 0, "executionTimeMs": 125 }
```

---

## Security

Security is a first-class concern, not an afterthought.

```yaml
binary: opcua-nodeset-linker

security:
  allowlist: [git, kubectl, docker, opcua-nodeset-linker]
  readonly: true          # block destructive verbs
  approval: true          # human confirmation required
  timeout_seconds: 30
  max_output_bytes: 200000
  sandbox:
    backend: docker
    image: my-cli-image:latest
    network: false
```

- **Allow list** — only approved binaries can be exposed.
- **Read-only mode** — rejects risky commands (`rm`, `del`, `mkfs`, `format`, `shutdown`,
  `reboot`, `delete`, `purge`, `--force`, `reset --hard`, …).
- **Approval mode** — `prompt` asks on a terminal; `explicit` requires the client to pass
  `_approve: true` (safe for stdio/HTTP where stdin is the protocol channel).
- **Sandboxing** — run the CLI inside Docker or Podman; Firecracker support planned.
- **Argument validation** — arguments are validated against the generated JSON schema
  before any process is spawned. No shell is used and no argument is ever interpolated into
  a shell string.

---

## Architecture

Clean architecture, one responsibility per package:

```text
src/cli_mcp/
├── cli/            # Typer entry point (expose/inspect/serve/export/doctor/init)
├── discovery/      # provider protocol + strategies
├── schema/         # JSON Schema, Markdown docs, OpenAPI
├── executor/       # argv building, subprocess execution, approval, sandbox
├── mcp/            # FastMCP server assembly, tool adapters
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

GitHub Actions run lint, type checking, tests, and build on every push; tagged releases
publish to PyPI.

---

## Examples

- [`examples/cli-mcp.yaml`](examples/cli-mcp.yaml) — full configuration
- [`examples/sample-clis/`](examples/sample-clis) — small argparse/click/typer/commander apps used by the tests
- [`docs/examples.md`](docs/examples.md) — client configuration recipes

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
