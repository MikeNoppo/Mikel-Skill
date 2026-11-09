import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ('session-report', 'day-report')


def install(home):
    plans = []
    for name in NAMES:
        source = ROOT / 'skills' / name
        if not (source / 'SKILL.md').is_file():
            raise ValueError(f'Sumber skill belum lengkap: {name}')
        for base in ('.agents/skills', '.claude/skills'):
            destination = home / base / name
            if destination.is_symlink() or destination.exists():
                if destination.resolve() != source.resolve():
                    raise ValueError(f'{destination} sudah digunakan instalasi lain; tidak ditimpa.')
            else:
                plans.append((source, destination))
    for source, destination in plans:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source, target_is_directory=True)
    return [str(home / base / name) for name in NAMES for base in ('.agents/skills', '.claude/skills')]


def main():
    parser = argparse.ArgumentParser(description='Tautkan skill Mikel-Skill ke Codex dan Claude Code.')
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    try:
        for location in install(args.home.expanduser().resolve()):
            print(location)
        return 0
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
