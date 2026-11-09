import argparse
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def main():
    parser = argparse.ArgumentParser(description='Siapkan lokasi laporan harian berdasarkan hari dan proyek.')
    parser.add_argument('--date', default='today')
    parser.add_argument('--timezone', required=True)
    parser.add_argument('--scope', required=True)
    parser.add_argument('--root', type=Path, default=Path.home() / 'Reports' / 'day-reports')
    args = parser.parse_args()
    try:
        zone = ZoneInfo(args.timezone)
        day = datetime.now(zone).date() if args.date == 'today' else date.fromisoformat(args.date)
        scope = re.sub(r'[^a-z0-9_-]+', '-', args.scope.lower()).strip('-_')
        if not scope or len(scope) > 100:
            raise ValueError('Scope perlu nama proyek yang jelas, maksimal 100 karakter.')
        start = datetime.combine(day, time.min, zone)
        end = datetime.combine(day + timedelta(days=1), time.min, zone)
        folder = args.root.expanduser().resolve() / day.isoformat() / scope
        folder.mkdir(parents=True, exist_ok=True)
        data = folder / 'report.json'
        html = folder / 'report.html'
        print(json.dumps({
            'date': day.isoformat(), 'timezone': args.timezone, 'scope': scope,
            'data_path': str(data), 'html': str(html),
            'previous_data': str(data) if data.is_file() else None,
            'utc_start_inclusive': start.astimezone(timezone.utc).isoformat(),
            'utc_end_exclusive': end.astimezone(timezone.utc).isoformat(),
        }, ensure_ascii=False))
        return 0
    except (ValueError, ZoneInfoNotFoundError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
