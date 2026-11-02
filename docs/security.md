# Security

A model calling your CLI is a remote caller. cli-mcp decides what may run *before* the process is
spawned, in one place: `security/policy.py`.

## Allow list

```yaml
cli-mcp:
  binary: git
  security:
    allowlist: [git, docker]
```

Only binaries whose basename is on the list can be exposed or executed. Blocked binaries —
`rm`, `del`, `shutdown`, `reboot`, `mkfs`, `format` and friends — are refused even if they appear
on the allow list.

## Read-only mode

```bash
cli-mcp expose git --readonly
```

Read-only rejects commands whose verb is destructive (`rm`, `del`, `push`, `delete`, `remove`,
`format`, `shutdown`, …), commands carrying destructive flags (`--force`, `-f`, `--yes`,
`--no-confirm`) and argv that matches dangerous patterns (`rm -rf /`, `mkfs`, pipes into shells).
Rejection is a tool error, not a failed command: nothing runs.

## Block and allow patterns

```yaml
security:
  block_patterns: ["rm -rf", "docker rm"]
  allow_patterns: ["git push origin feature/*"]
```

`block_patterns` always apply. `allow_patterns` overrides both read-only and block patterns, so
you can carve out narrow exceptions instead of turning protection off.

## Approval

```yaml
security:
  approval: true
  approval_mode: prompt   # auto | prompt | explicit
```

Risky commands need a human:

```
Tool Request: git push origin main
Approve? [y/N]
```

Over stdio the client owns stdin, so an interactive prompt is only offered when stdin is a TTY.
Otherwise pass the decision in the tool call:

```json
{"name": "push", "arguments": {"remote": "origin", "approve": true}}
```

`approval_mode: explicit` never prompts and requires `approve: true`; `auto` approves commands the
policy already allowed and asks for the rest. `ApprovalRequired` is raised when approval is missing.

## Sandbox

Run the command inside a container instead of on the host:

```yaml
security:
  sandbox:
    backend: docker        # docker or podman
    image: alpine:3.20
    network: false
    workdir_mount: true    # the working directory is mounted read-write at /work
    extra_args: ["--memory", "512m"]
```

cli-mcp checks the runtime is available (`docker`/`podman` on `PATH`) and prefixes the command with
`run --rm`. Firecracker microVMs are planned for a later release.

## Limits

`timeout_seconds` kills the process and reports `exitCode: -1` with a
`[cli-mcp] timed out after Ns` note; `max_output_bytes` truncates stdout and stderr and says so in
the result. Both apply per executed command, whatever the client asked for.
