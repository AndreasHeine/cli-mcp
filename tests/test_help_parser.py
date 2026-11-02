"""Unit tests for the generic help-text grammar."""

from cli_mcp.discovery.help_parser import is_help_noise, parse_help, parse_markers

ARGPARSE = """usage: reducer reduce [-h] --input INPUT --output OUTPUT [--format {xml,json}]
                      [--strip-aliases]

Reduce a nodeset to its core nodes.

options:
  -h, --help           show this help message and exit
  --input INPUT        Source nodeset XML file
  --output OUTPUT      Destination file
  --format {xml,json}  Output format
  --strip-aliases      Drop alias entries
"""

COBRA = """Available Commands:
  complete  Generate completion scripts
  help      Help about any command
  serve     Start the API server

Flags:
  --config string   config file (default is "cfg.yaml")
  -h, --help        help for cli
      --verbose     verbose logging (required)
"""

CLAP = """Commands:
  reduce  Reduce a nodeset
  diff    Compare two files

Options:
  --input <INPUT>   Source file [default: model.xml]
  --format          Output format [possible values: xml, json]
  -h, --help        Print help
"""

YARGS = """bundle <entry>

Positionals:
  entry  Entry file                [string] [required]

Options:
      --help     Show help             [boolean]
      --outdir   Output directory      [string] [default: "dist"]
      --minify   Minify output         [boolean]
      --level    Compression level     [number] [choices: 1, 2, 3] [default: 2]
"""

COMMANDER = """usage: nodesample [options] <command>

Fetch and transform remote documents.

Options:
  -v, --verbose   verbose output
  -h, --help      output usage information

Commands:
  fetch <url>     Fetch a document
  transform       Transform a file
"""

CLICK = """Usage: cli [OPTIONS] COMMAND [ARGS]...

  Publish documents to a registry.

Options:
  --verbose  Verbose logging
  --help     Show this message and exit.

Commands:
  publish  Publish a document
  status   Show registry status
"""

DOTNET = """Direct commands:
  run    Run the pipeline
  show   Show metadata

Options:
  --path <PATH>  Project path
  --help       Show help and usage
"""


def test_parse_markers_extracts_every_marker() -> None:
    markers, text = parse_markers('--level L [default: 2] [choices: 1, 2] [required] [type: number] [env var: LEVEL]')
    assert markers["default"] == "2"
    assert markers["choices"] == "1, 2"
    assert markers["required"] == "true"
    assert markers["type"] == "number"
    assert markers["env"] == "LEVEL"
    assert text == "--level L"


def test_parse_markers_optional_and_aliases() -> None:
    markers, text = parse_markers("--tag TAG [optional] [aliases: -t]")
    assert markers["required"] == "false"
    assert markers["aliases"] == "-t"
    assert "--tag TAG" in text


def test_parse_markers_ignores_plain_brackets() -> None:
    markers, text = parse_markers("--mode [fast|slow] toggle")
    assert markers == {}
    assert text == "--mode [fast|slow] toggle"


def test_parse_argparse_page() -> None:
    parsed = parse_help(ARGPARSE)
    assert parsed.description == "Reduce a nodeset to its core nodes."
    names = {option.name for option in parsed.options}
    assert names == {"help", "input", "output", "format", "strip-aliases"}
    input_option = next(option for option in parsed.options if option.name == "input")
    assert input_option.required is True
    assert input_option.type == "string"
    assert input_option.metavar == "INPUT"
    assert input_option.is_flag is False

    format_option = next(option for option in parsed.options if option.name == "format")
    assert format_option.choices == ["xml", "json"]
    assert format_option.is_flag is False

    strip = next(option for option in parsed.options if option.name == "strip-aliases")
    assert strip.is_flag is True
    assert parsed.positionals == []


def test_parse_cobra_page() -> None:
    parsed = parse_help(COBRA)
    assert [command.name for command in parsed.subcommands] == ["complete", "help", "serve"]
    config = next(option for option in parsed.options if option.name == "config")
    assert config.default == "cfg.yaml"
    assert config.type == "string"
    verbose = next(option for option in parsed.options if option.name == "verbose")
    assert verbose.is_flag is True


def test_parse_clap_page() -> None:
    parsed = parse_help(CLAP)
    assert [command.name for command in parsed.subcommands] == ["reduce", "diff"]
    input_option = next(option for option in parsed.options if option.name == "input")
    assert input_option.default == "model.xml"
    assert input_option.metavar == "INPUT"
    format_option = next(option for option in parsed.options if option.name == "format")
    assert format_option.choices == ["xml", "json"]


def test_parse_yargs_page() -> None:
    parsed = parse_help(YARGS)
    positional = parsed.positionals[0]
    assert positional.name == "entry"
    assert positional.required is True
    level = next(option for option in parsed.options if option.name == "level")
    assert level.type == "number"
    assert level.choices == ["1", "2", "3"]
    assert level.default == "2"
    outdir = next(option for option in parsed.options if option.name == "outdir")
    assert outdir.default == "dist"
    minify = next(option for option in parsed.options if option.name == "minify")
    assert minify.is_flag is True


def test_parse_commander_page() -> None:
    parsed = parse_help(COMMANDER)
    assert parsed.description == "Fetch and transform remote documents."
    assert [command.name for command in parsed.subcommands] == ["fetch", "transform"]
    verbose = next(option for option in parsed.options if option.name == "verbose")
    assert verbose.short == "v"
    assert verbose.is_flag is True


def test_parse_click_page() -> None:
    parsed = parse_help(CLICK)
    assert parsed.description == "Publish documents to a registry."
    assert {command.name for command in parsed.subcommands} == {"publish", "status"}
    assert next(option for option in parsed.options if option.name == "verbose").is_flag is True


def test_parse_dotnet_page() -> None:
    parsed = parse_help(DOTNET)
    assert [command.name for command in parsed.subcommands] == ["run", "show"]
    path_option = next(option for option in parsed.options if option.name == "path")
    assert path_option.metavar == "PATH"


def test_usage_line_marks_positionals_and_required_options() -> None:
    parsed = parse_help("usage: tool [-v] <left> [right] --config FILE\n\noptions:\n  --config FILE  config path\n")
    assert [positional.name for positional in parsed.positionals] == ["left", "right"]
    assert parsed.positionals[1].required is False
    assert parsed.required_options == {"config"}
    option = next(item for item in parsed.options if item.name == "config")
    assert option.required is True


def test_continuation_lines_extend_descriptions() -> None:
    parsed = parse_help(
        "options:\n  --input FILE\n                     Source file in XML\n  --output FILE      Destination\n"
    )
    input_option = next(option for option in parsed.options if option.name == "input")
    assert "Source file in XML" in input_option.description


def test_short_only_flags_get_a_name() -> None:
    parsed = parse_help("options:\n  -x           extra debugging\n")
    assert parsed.options[0].name == "x"


def test_is_help_noise_detects_boilerplate() -> None:
    assert is_help_noise("Show this message and exit")
    assert is_help_noise("help for serve")
    assert is_help_noise("Reduce a nodeset") is False


def test_unmatched_sections_are_ignored() -> None:
    parsed = parse_help("Environment:\n  HOME  home directory\n\noptions:\n  --flag  toggle\n")
    assert [option.name for option in parsed.options] == ["flag"]
