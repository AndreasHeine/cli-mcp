"""Strategy 1 for Node.js CLIs: reflect on a commander.js program object."""

from __future__ import annotations

import os

from cli_mcp.config.settings import Settings
from cli_mcp.detect import TargetInfo
from cli_mcp.discovery.base import DiscoveryContext
from cli_mcp.discovery.reflection_payload import commands_from_payload, parse_payload
from cli_mcp.models import DiscoveryResult

#: Probe executed with ``node -e``. It requires the entry module and walks any
#: commander program it can find. Requires modules that export their program.
NODE_PROBE = """
const path = require('path');
const target = process.env.CLI_MCP_NODE_TARGET;
const out = [];

function optionType(option) {
  const hint = (option.argName || option.flag || '').toLowerCase();
  if (/\\b(number|count|int)\\b/.test(hint)) return 'number';
  return 'string';
}

function walk(command, prefix) {
  const entry = {
    path: prefix,
    description: command.description() || '',
    parameters: [],
    has_subcommands: (command.commands || []).length > 0,
  };
  for (const option of command.options || []) {
    const long = (option.long || '').replace(/^--/, '');
    const short = (option.short || '').replace(/^--?/, '');
    entry.parameters.push({
      name: long || short || 'arg',
      kind: option.required ? 'option' : 'flag',
      cli_name: long || short || null,
      short: short || null,
      short_only: !long && Boolean(short),
      type: optionType(option),
      description: option.description || '',
      required: Boolean(option.required),
      default: option.defaultValue === undefined ? null : option.defaultValue,
      repeatable: Boolean(option.variadic)
        || Boolean(option.implied && option.implied.value && option.implied.value.repeatable),
      metavar: option.argName || null,
    });
  }
  const positionals = command.registeredArguments || command._args || [];
  for (const argument of positionals) {
    entry.parameters.push({
      name: argument.name || 'arg',
      kind: 'positional',
      type: argument.variadic ? 'array' : 'string',
      description: argument.description || '',
      required: Boolean(argument.required),
      repeatable: Boolean(argument.variadic),
    });
  }
  out.push(entry);
  for (const sub of command.commands || []) {
    walk(sub, prefix.concat(sub.name()));
  }
}

try {
  const loaded = require(path.resolve(target));
  const candidates = [];
  if (loaded && typeof loaded === 'object') {
    for (const value of Object.values(loaded)) {
      if (value && typeof value === 'object' && Array.isArray(value.commands)) candidates.push(value);
    }
    if (Array.isArray(loaded.commands) && typeof loaded.description === 'function') candidates.push(loaded);
  }
  for (const candidate of candidates) walk(candidate, []);
  process.stdout.write(JSON.stringify({ framework: 'commander', commands: out }));
} catch (error) {
  process.stdout.write(JSON.stringify({ framework: null, commands: [], error: String(error) }));
}
"""


class NodeReflectionProvider:
    """Require a Node CLI entry module and read its commander command tree."""

    name = "reflection-node"
    strategy = "reflection"
    frameworks: tuple[str, ...] = ("node", "commander")

    def __init__(self, settings: Settings) -> None:
        """Store the settings that gate reflection."""
        self.settings = settings

    def supports(self, target: TargetInfo) -> bool:
        """Reflection executes the target module, so it needs a Node target and opt-in."""
        if not self.settings.discovery.allow_import_reflection:
            return False
        return target.origin == "node"

    def discover(self, target: TargetInfo, ctx: DiscoveryContext) -> DiscoveryResult | None:
        """Run the probe and convert its JSON document."""
        node = os.environ.get("CLI_MCP_NODE") or ctx.interpreter("node")
        if not node:
            return None
        help_result = ctx.run(
            [node, "-e", NODE_PROBE],
            timeout=self.settings.discovery.help_timeout_seconds,
            env={"CLI_MCP_NODE_TARGET": target.resolved_path},
        )
        payload = parse_payload(help_result.stdout)
        if payload is None:
            return None
        commands = commands_from_payload(payload, target, self.settings.mcp.tool_prefix)
        if not commands:
            return None
        warnings = [f"reflection error: {payload['error']}"] if payload.get("error") else []
        return DiscoveryResult(
            binary=target.binary,
            resolved_path=target.resolved_path,
            framework=payload.get("framework") or target.framework,
            commands=commands,
            strategies=[self.name],
            warnings=warnings,
        )
