# Security

A model calling your CLI is an untrusted remote caller. Execution policy is checked before
tool execution, in `security/policy.py`. Only expose trusted executables: discovery runs
their help commands on the host, even when tool execution uses a sandbox. Import reflection
is disabled by default because it may execute arbitrary target code.

## Allow list

```yaml
cli-mcp:
  binary: git
  security:
    allowlist: [git, docker]
```

An empty allow list permits the configured binary; it is not an OS permission boundary.
Only binaries whose basename is on a non-empty list can be exposed. Blocked binaries —
`rm`, `del`, `shutdown`, `reboot`, `mkfs`, `format` and friends — are refused even if they appear
on the allow list. Authorization happens before discovery. Windows `.bat` and `.cmd`
targets are rejected before discovery or execution: Windows can interpret their arguments
through a shell even with `shell=False`. Use the underlying executable instead.

## Read-only mode

```yaml
binary: /usr/bin/ping
security:
  readonly: true
  readonly_argv:
    - [/usr/bin/ping, -c, "1", "127.0.0.1"]
```

Read-only is deny-by-default: every complete argv vector, including the resolved executable
path, interpreter/script prefix where applicable, and all arguments, must exactly match an
entry in `security.readonly_argv`. Matching preserves token boundaries, order and case; there
are no wildcards or regex exceptions. An empty list blocks every tool execution.

Destructive verbs, known destructive flags and dangerous argv patterns are additionally
rejected, even if an exact invocation was listed. Unrecognized commands such as `git config`
are not implicitly safe. Rejection is a tool error: the requested tool process does not run.

The operator must verify each listed invocation and trust its executable, environment and
input files. An exact allow list cannot prove that a program never writes files, accesses
credentials or makes network requests. Discovery is outside this execution guard.

## Block and allow patterns

```yaml
security:
  block_patterns: ["rm -rf", "docker rm"]
  allow_patterns: ["git push origin feature/*"]
```

Patterns are regular expressions over the space-joined argv, not shell globs.
`block_patterns` apply in both modes. Outside read-only mode, `allow_patterns` can override
custom block patterns. In read-only mode, allow patterns cannot bypass any guard or replace
the exact invocation allow list.

## Approval

```yaml
security:
  approval: true
  approval_mode: prompt   # auto | prompt | explicit
```

Commands classified as risky, or every command when `approval: true`, need a local human:

```
Tool Request: ["git", "push", "origin", "main"]
Approve? [y/N]
```

`auto` and `prompt` ask only when server stdin is a local TTY; prompts use stderr by default
and escape control characters in argv. Without a terminal, execution is refused.
Over stdio, stdin normally carries MCP messages, so approval-required calls cannot run.
The legacy `explicit` mode is retained for configuration compatibility but always refuses
approval-required executions. `ApprovalRequired` reports the missing local approval.

There is no client-side approval control argument. Supplying `approve: true` cannot grant
permission: it is rejected unless the underlying CLI actually declares that parameter, and
even then it does not approve the execution. This intentionally replaces the previous
self-approval behavior; no automatic headless approval is provided.

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
`run --rm`. The working directory is not mounted by default. Set `workdir_mount: true` only when
the command needs host files; that bind mount is writable, so the command can change files in the
directory. Do not expose runtime sockets or privileged mounts. Set runtime memory/CPU limits as
appropriate; sandboxing is opt-in and does not sandbox discovery. Firecracker microVMs are planned
for a later release.

## Limits

`timeout_seconds` limits execution and reports `exitCode: -1` with a
`[cli-mcp] timed out after Ns` note. `max_output_bytes` bounds retained raw bytes separately
for stdout and stderr, including partial timeout output; excess output is drained and discarded.
Truncation is reported in the result. `max_argv_tokens` and `max_argv_bytes` bound each complete
invocation, counting the executable and NUL separators; oversized or NUL-containing invocations
are rejected before approval or process creation. These limits do not bound the target program's
own RAM or CPU usage. Discovery also uses bounded output capture.

`execution.cwd` sets the process working directory but does not confine file access. Paths passed
as CLI arguments are interpreted by the target program and are not generally normalized or
restricted by cli-mcp; their behavior differs between CLIs. Use a container without host directory
mounts, or define and enforce CLI-specific path rules when filesystem confinement is required.

`discovery.max_commands` additionally limits uncached help invocations, checked before
process creation. The root query, failed attempts and alternate help flags consume this
shared budget; cached responses do not. Recursive discovery stops querying children at
the budget or tool limit and reports truncation in discovery warnings. This can produce
fewer tools than the limit, especially when root help or fallback attempts consume calls.
Include/exclude filters select published tools; they are not execution permissions and
do not guarantee that an excluded command's help will never be queried.

Windows native output is decoded with the OEM code page when it is not valid UTF-8.
Undecodable bytes are visibly escaped rather than losing output or raising an unobserved
reader-thread exception.

## Network exposure

The default transport is stdio; HTTP/SSE defaults to loopback. cli-mcp does not configure
authentication or TLS. Do not bind an unauthenticated server to an externally reachable
interface. Use an authenticated TLS reverse proxy and a firewall when remote access is needed.

## Non-invasive tests

The focused suite below does not create target scripts, initialize Git repositories, or start
containers. It uses in-memory policy tests, mocked sandbox commands and isolated Python
`-I -S -B -c` subprocesses. The ping test is restricted to one probe to `127.0.0.1`.
Ping creates network traffic, so it is not literally side-effect-free; it does not intentionally
change files or configuration. Host monitoring and OS logs remain outside our control.

Windows PowerShell, with an existing development environment:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -p pytest_asyncio.plugin --override-ini=addopts= tests\test_security.py tests\test_executor.py tests\test_safety.py tests\test_runner_safe.py
```

Linux, with an existing development environment:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -B -m pytest -p no:cacheprovider -p pytest_asyncio.plugin \
  --override-ini=addopts= tests/test_security.py tests/test_executor.py \
  tests/test_safety.py tests/test_runner_safe.py
```

This disables project coverage output, pytest cache and bytecode writes without installing
dependencies. The complete existing suite includes temporary-file and Git integration tests;
do not substitute an unfiltered `pytest` invocation when avoiding filesystem changes.

Direct loopback equivalents are `ping.exe -n 1 127.0.0.1` on Windows and
`ping -c 1 127.0.0.1` on Linux. Their flags and help output differ; the adapter supports
short-only options, but automatic discovery of every localized ping implementation is not
guaranteed. The safe test uses explicit metadata rather than assuming a common help grammar.
