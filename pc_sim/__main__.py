"""Unified command entrypoint; import only the selected implementation."""
import argparse
import importlib
import sys

COMMANDS = {
    'gui': ('ui.gui', 'Open the desktop HIL console'),
    'simulate': ('cli.run_sim', 'Generate or send target scenarios'),
    'evaluate': ('evaluation.evaluate', 'Run an evaluation or analyze a saved session'),
    'noise-sweep': ('evaluation.noise_sweep', 'Evaluate multiple noise conditions'),
    'spike-sweep': ('evaluation.spike_sweep', 'Evaluate multiple outlier conditions'),
    'turn-noise': ('evaluation.turn_noise', 'Replay noisy turn input and evaluate board reports'),
    'input': ('cli.prepare_input', 'Generate or verify reusable input files'),
    'status': ('cli.status_client', 'Request board STATUS'),
    'send-frame': ('cli.frame_sender', 'Send one control or data frame'),
    'send-radar': ('cli.radar_sender', 'Send simple range-rate measurements'),
}


def main(argv: list[str] | None = None) -> int:
    """Dispatch arguments without duplicating command parsers or losing exit status."""
    arguments = sys.argv[1:] if argv is None else argv
    descriptions = '\n'.join(f'  {name:12} {description}'
                             for name, (_, description) in COMMANDS.items())
    parser = argparse.ArgumentParser(
        prog='python -m pc_sim', description='Radar simulation and board tools.',
        epilog=descriptions + '\n\nUse COMMAND --help for command options.',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=COMMANDS, metavar='COMMAND')
    if not arguments:
        parser.print_help()
        return 0
    # Parse only the command so the selected tool owns all remaining options.
    command = parser.parse_args(arguments[:1]).command
    remaining = arguments[1:]
    if command == 'gui':
        # Help and invalid options must not require Qt or start a window.
        argparse.ArgumentParser(prog=f'{parser.prog} gui',
                                description=COMMANDS['gui'][1]).parse_args(remaining)
    implementation = importlib.import_module(f'pc_sim.{COMMANDS[command][0]}')
    original_argv = sys.argv
    try:
        sys.argv = [f'{parser.prog} {command}', *remaining]
        result = implementation.main()
    finally:
        sys.argv = original_argv
    return 0 if result is None else result


if __name__ == '__main__':
    raise SystemExit(main())
