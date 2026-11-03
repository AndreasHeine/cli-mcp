# Discovery

Discovery answers one question: which commands does this CLI accept, and what arguments do they
take? cli-mcp answers it with three strategies, tried in the order configured in
`discovery.strategies` (default `[reflection, help, manifest]`).

## 1. Reflection

Reflection asks the CLI's own argument parser for the truth, which beats any text parsing.
It is opt-in because it imports or executes target code:

```bash
cli-mcp expose ./tools/reducer.py --allow-reflection
```

or `discovery.allow_import_reflection: true`. Supported frameworks:

| Framework | How it is read |
| --- | --- |
| Python `argparse`, `click`, `typer` | imports the module and walks the parser objects |
| Node `commander`, `yargs` | loads the module and reads its option table |
| Go `cobra`, Rust `clap`, .NET `System.CommandLine` | parsed from help output via grammar providers |

Interpreter choice comes from the target's origin, and can be overridden with
`CLI_MCP_PYTHON` / `CLI_MCP_NODE`.

## 2. Recursive help parsing

The fallback works on anything that prints help: `<cli> --help`, then `<cli> <command> --help`
for every subcommand found, down to `discovery.max_depth`. The generic grammar understands
`usage:` lines, `options:` / `flags:` / `positional arguments:` sections, `--flag <METAVAR>`
pairs, `(default: x)` and `[required]` markers, short/long aliases and continuation lines.

`discovery.max_commands` limits both published tools and uncached help invocations across
the shared discovery context. The root query, failures and alternate help flags count;
cache hits do not. The budget is checked before spawning a process. Reaching either limit
stops further child queries and produces a discovery warning; already discovered tools are
retained. Consequently, fewer than `max_commands` tools may be discovered.

Include/exclude filters apply to publication, not to process permissions. They do not prevent
help queries for excluded commands. Discovery help still runs on the host even when execution
uses read-only mode or a container; only inspect trusted CLIs.

Framework grammars refine that generic pass when a fingerprint matches:

| Provider | Rewrites |
| --- | --- |
| `git` | `--[no-]verbose` to `--verbose`, `[=<version>]` to `<version>`, and uses `-h` for subcommand help because `git status --help` opens a man pager and prints nothing when its output is captured |
| `cobra` | `(default "x")` and `(required)` markers, trailing type words |
| `clap` | `--flag <VALUE>` with `[default: x]` |
| `dotnet` | `--option <TYPE>  description` tables |
| `click` / `typer` | `Usage:` sections, `--opt TEXT` metavars |
| `yargs` / `commander` | `[default: x]`, `[required]`, choices lists |
| `argparse` | optional/positional sections |

`cli-mcp providers` lists the active providers and the frameworks each one understands.

## 3. Manifest

A `cli-mcp:` manifest declares tools explicitly and overrides discovery. See
[configuration.md](configuration.md).

## Tool names

Tool names come from the command path, normalised to the MCP rule `^[A-Za-z0-9._-]{1,128}$`:
`git status` becomes `status`, `opcua-nodeset-linker reduce` becomes `reduce`. A script target
is named after its file stem (`reducer.py` → `reducer`), and `mcp.tool_prefix: true` prefixes
the binary name (`git_status`) when several servers share a client.

Argument names are normalised the same way: `--show-stash` publishes as `show_stash`, with the
CLI spelling kept in the tool description.

## What discovery reports

`DiscoveryResult` carries the commands, the framework it detected, the strategies that ran and
human-readable warnings: filtered commands, depth caps, commands without help output. `expose`
prints them after the checklist, and `inspect` shows them at the end of the table.
