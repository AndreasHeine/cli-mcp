# Plugins

Third-party discovery providers plug into cli-mcp without touching its core. A provider is a
class implementing the `DiscoveryProvider` protocol:

```python
name: str             display name, e.g. "my-framework"
strategy: str         "reflection", "help" or "manifest"
frameworks: tuple     framework fingerprints this provider understands
supports(target)      whether the provider can handle this binary
discover(target, ctx) return a DiscoveryResult, or None to abstain
```

Optional extras: `preprocess(text)` rewrites help text before the generic grammar parses it, and
`refine(spec, help_result)` adjusts a command after it was built. Providers are constructed with
the current `Settings` when they accept a `settings` parameter, otherwise with no arguments.

## Example: exposing a Java picocli CLI

```python
# my_provider.py
from cli_mcp.discovery.base import DiscoveryContext, DiscoveryProvider
from cli_mcp.discovery.engine import command_for, discover_from_help
from cli_mcp.models import DiscoveryResult


class PicocliProvider(DiscoveryProvider):
    name = "picocli"
    strategy = "help"
    frameworks = ("picocli",)

    def __init__(self, settings) -> None:
        self.settings = settings

    def supports(self, target) -> bool:
        return target.framework == "picocli" or "picocli" in target.root_help.lower()

    def discover(self, target, ctx: DiscoveryContext) -> DiscoveryResult | None:
        return discover_from_help(target, ctx, self.settings, provider=self.name)
```

Register it through the `cli_mcp.discovery` entry-point group:

```toml
[project.entry-points."cli_mcp.discovery"]
picocli = "my_provider:PicocliProvider"
```

Install the package alongside cli-mcp and it appears in `cli-mcp providers` and in the discovery
pipeline. `cli-mcp expose <binary> --strategies help` restricts the run to one strategy; plugins
are loaded unless you pass `load_plugins=False` in library code.

## Detection

`detect.py` fingerprints frameworks from root help text. To teach cli-mcp a new fingerprint, a
plugin can also ship a detection hint by matching its own marker in `supports()` — cli-mcp then
routes that target to the plugin even when the built-in fingerprints do not match.
