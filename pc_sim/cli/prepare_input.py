"""Generate or verify a saved measurement sequence without opening serial ports."""
import argparse
from pathlib import Path

from pc_sim.simulation.prepared_input import InputSettings, SINGLE_TARGET_SCENARIOS, generate_input
from pc_sim.storage.prepared_storage import load_input, save_input


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    generate = commands.add_parser('generate', help='Create a new saved input directory')
    generate.add_argument('directory', type=Path)
    generate.add_argument('--scenario', choices=SINGLE_TARGET_SCENARIOS, default='single_approach')
    generate.add_argument('--duration', type=float, default=1, help='Requested sensor duration (s)')
    generate.add_argument('--dt', type=float, default=.02, help='Sensor sample interval (s)')
    generate.add_argument('--pd', type=float, default=1, help='Detection probability (0..1)')
    generate.add_argument('--noise', type=float, default=10, help='Range noise standard deviation (m)')
    generate.add_argument('--azimuth-noise', type=float, default=.01,
                          help='Azimuth noise standard deviation (rad)')
    generate.add_argument('--seed', type=int, default=42)
    verify = commands.add_parser('verify', help='Validate saved input without regenerating it')
    verify.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'generate':
            data = generate_input(InputSettings(
                scenario=args.scenario, duration_s=args.duration, dt_s=args.dt, pd=args.pd,
                range_noise_std_m=args.noise, azimuth_noise_std_rad=args.azimuth_noise,
                seed=args.seed))
            save_input(args.directory, data)
        else:
            data = load_input(args.directory)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Input failed: {error}\n')
    frames = sum(sample.frame is not None for sample in data.samples)
    print(f'input: action={args.command} samples={len(data.samples)} frames={frames} '
          f'duration_s={data.metadata["effective_duration_s"]} directory={args.directory}')


if __name__ == '__main__':
    main()
