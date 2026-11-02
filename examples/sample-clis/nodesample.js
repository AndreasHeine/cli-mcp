#!/usr/bin/env node
// Sample Node CLI whose help output follows the commander grammar.
// No npm dependencies: the help text is printed by hand so cli-mcp can parse it.

const HELP = `Usage: nodesample <command> [options]

Manage fixture files for the sample pipeline.

Commands:
  fetch <url>            Download a fixture into the cache directory
  transform <file>       Rewrite a fixture in place
  purge                  Empty the fixture cache

Options:
  --cache <dir>          Cache directory (default: "fixtures")
  --timeout <ms>         Request timeout in milliseconds (default: 5000)
  --verbose              Print every request
  -h, --help             Show this help
`;

const FETCH_HELP = `Usage: nodesample fetch <url> [options]

Download a fixture into the cache directory.

Options:
  --cache <dir>          Cache directory (default: "fixtures")
  --timeout <ms>         Request timeout in milliseconds (default: 5000)
  --retries <n>          Retry count (default: 2)
  --verbose              Print every request
`;

const TRANSFORM_HELP = `Usage: nodesample transform <file> [options]

Rewrite a fixture in place.

Options:
  --format <name>        Output format (choices: json, csv)
  --dry-run              Show the rewrite without writing it
`;

const HELP_FLAGS = ['--help', '-h'];

function main(argv) {
  const [command, ...rest] = argv;
  if (command === undefined || HELP_FLAGS.includes(command)) {
    process.stdout.write(HELP);
    return 0;
  }
  if (command === 'fetch') {
    if (HELP_FLAGS.some((flag) => rest.includes(flag))) {
      process.stdout.write(FETCH_HELP);
      return 0;
    }
    if (rest.length === 0) {
      process.stderr.write('missing required argument: url\n');
      return 2;
    }
    process.stdout.write(JSON.stringify({ command: 'fetch', url: rest[0], flags: rest.slice(1) }) + '\n');
    return 0;
  }
  if (command === 'transform') {
    if (HELP_FLAGS.some((flag) => rest.includes(flag))) {
      process.stdout.write(TRANSFORM_HELP);
      return 0;
    }
    if (rest.length === 0) {
      process.stderr.write('missing required argument: file\n');
      return 2;
    }
    process.stdout.write(JSON.stringify({ command: 'transform', file: rest[0], flags: rest.slice(1) }) + '\n');
    return 0;
  }
  if (command === 'purge') {
    process.stdout.write(JSON.stringify({ command: 'purge' }) + '\n');
    return 0;
  }
  process.stderr.write(`${command}: unknown command\n`);
  return 1;
}

process.exit(main(process.argv.slice(2)));
