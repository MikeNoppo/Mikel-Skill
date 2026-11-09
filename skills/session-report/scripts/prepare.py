import argparse
import json
import sys
from pathlib import Path

import common
import render


def main():
    parser = argparse.ArgumentParser(description="Locate the current session report before creating or updating it.")
    parser.add_argument("session", nargs="?", default="auto")
    parser.add_argument("--harness", choices=sorted(render.HARNESS), required=True)
    args = parser.parse_args()
    try:
        sid = render.resolve_session(args.session, str(Path.cwd()), args.harness)
        meta = common.load_meta(sid)
        previous = meta.get("report")
        html = meta.get("html")
        result = {
            "session_id": sid,
            "data_path": str(common.session_dir(sid) / "report.json"),
            "previous_data": previous if previous and common.is_under(previous, common.root()) and Path(previous).is_file() else None,
            "html": html if html and common.is_under(html, common.root()) and Path(html).is_file() else None,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (render.ReportError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
