# Clients

Any MCP client works: cli-mcp publishes `tools/list` and `tools/call` over stdio, HTTP,
Streamable HTTP or SSE. Start a server with `cli-mcp serve <binary>` (no checklist, so stdio
stays clean) and point the client at it.

## Claude Desktop / Claude Code (`.mcp.json`)

```json
{
  "mcpServers": {
    "git": {
      "command": "cli-mcp",
      "args": ["serve", "git"]
    },
    "linker": {
      "command": "cli-mcp",
      "args": ["serve", "opcua-nodeset-linker", "--config", "cli-mcp.yaml"]
    }
  }
}
```

## VS Code / Copilot

```json
{
  "mcp": {
    "servers": {
      "docker": {
        "type": "stdio",
        "command": "cli-mcp",
        "args": ["serve", "docker", "--readonly"]
      }
    }
  }
}
```

## Cursor, Cline, Roo Code

```json
{
  "mcpServers": {
    "kubectl": {
      "command": "cli-mcp",
      "args": ["serve", "kubectl", "--readonly", "--approval"]
    }
  }
}
```

## Open WebUI and other HTTP clients

Start a network server and use its URL:

```bash
cli-mcp expose kubectl --transport streamable-http --port 8801 --readonly
```

```json
{
  "mcpServers": {
    "kubectl": {
      "url": "http://127.0.0.1:8801/mcp"
    }
  }
}
```

## Reading the tools

Ask the server what it published, without starting a client:

```bash
cli-mcp inspect git                 # table of tools, arguments and provider
cli-mcp export-schema git           # MCP tool definitions as JSON
cli-mcp export git                  # Markdown documentation
cli-mcp export-openapi git          # OpenAPI 3.1 document
cli-mcp doctor git                  # readiness check: binary, discovery, transport
```

## Naming when you expose several CLIs

Publishing more than one binary in the same client can collide (`docker ps` and `kubectl ps`).
Use `--tool-prefix` to namespace the tools (`docker_ps`, `kubectl_ps`).
