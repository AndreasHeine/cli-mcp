# Transports

cli-mcp speaks the four MCP transports. Pick one with `--transport` or `mcp.transport`.

## stdio (default)

The server talks over the client's stdin/stdout. This is what every MCP client expects for a
local server, and there is nothing to bind.

```bash
cli-mcp serve git
```

## Streamable HTTP

The current HTTP transport: one endpoint, optional session state.

```bash
cli-mcp expose git --transport streamable-http --port 8801
```

```yaml
cli-mcp:
  binary: git
  mcp:
    transport: streamable-http
    host: 127.0.0.1
    port: 8801
    path: /mcp
    stateless_http: true   # no session state between requests
    json_response: true    # JSON responses instead of SSE streams
```

Endpoint: `http://127.0.0.1:8801/mcp`.

## HTTP

Plain request/response HTTP (JSON responses forced on). Useful for gateways that cannot stream.

```bash
cli-mcp expose git --transport http --port 8802
```

## SSE (deprecated)

The legacy two-endpoint transport, kept for clients that still need it:

```bash
cli-mcp expose git --transport sse --port 8803
```

Events on `http://127.0.0.1:8803/mcp`, client messages on `http://127.0.0.1:8803/messages/`.
Prefer Streamable HTTP; MCP is moving away from standalone SSE.

## Protocol behaviour

`tools/list` returns the generated tools with their exact schemas; `tools/call` validates arguments,
consults the security policy, runs the CLI and returns `{stdout, stderr, exitCode, executionTimeMs}`.
Tools are generated at startup from discovery — no hand-written MCP code — and a docs tool
(`<binary>_docs`) returns the generated Markdown unless `include_docs_tool: false`.
