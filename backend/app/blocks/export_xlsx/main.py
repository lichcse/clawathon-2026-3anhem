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
    inputs = json.loads(pathlib.Path(args.inputs).read_text())

    data_path = inputs.get("data")
    if not data_path:
        print("export_xlsx: missing required input 'data'", file=sys.stderr)
        return 2

    df = pd.read_parquet(data_path)
    filename = params.get("filename") or "output.xlsx"
    if not filename.lower().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    sheet_name = params.get("sheet_name") or "Sheet1"

    out = workdir / filename
    df.to_excel(out, index=False, sheet_name=sheet_name, engine="openpyxl")

    pathlib.Path(args.outputs).write_text(json.dumps({"file": str(out)}))
    print(f"export_xlsx: wrote {len(df)} rows -> {out.name} (sheet: {sheet_name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
