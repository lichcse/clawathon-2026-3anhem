import argparse
import json
import pathlib
import sys

import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--params", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--outputs", required=True)
    args = ap.parse_args()

    workdir = pathlib.Path(args.workdir)
    params = json.loads(pathlib.Path(args.params).read_text())

    src = pathlib.Path(params["path"]).expanduser().resolve()
    if not src.exists():
        print(f"load_csv: input file not found: {src}", file=sys.stderr)
        return 2

    df = pd.read_csv(src)
    out = workdir / "data.parquet"
    df.to_parquet(out, index=False)

    pathlib.Path(args.outputs).write_text(json.dumps({"data": str(out)}))
    print(f"load_csv: read {len(df)} rows ({list(df.columns)}) from {src.name} -> {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
