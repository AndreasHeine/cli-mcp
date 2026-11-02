#!/usr/bin/env node
// Sample Node CLI whose help output follows the yargs grammar.

const HELP = `bundle <entry> [options]

Bundle a fixture directory into a single file.

Positionals:
  entry                   Entry file to bundle                [string] [required]

Options:
  --help                  Show help                          [boolean]
  --outdir                Output directory    [string] [default: "dist"]
  --minify                Minify the output                  [boolean]
  --level                 Bundle level        [number] [default: 2] [choices: 1, 2, 3]
`;

const main = (argv) => {
  if (argv.length === 0 || argv.includes('--help')) {
    process.stdout.write(HELP);
    return 0;
  }
  const [entry, ...flags] = argv;
  process.stdout.write(JSON.stringify({ entry, flags }) + '\n');
  return 0;
};

process.exit(main(process.argv.slice(2)));
