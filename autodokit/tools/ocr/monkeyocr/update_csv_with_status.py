from __future__ import annotations

import argparse
import csv
from pathlib import Path
import shutil


def find_best_key(row: dict) -> str | None:
    for k in ("pdf_attachment_name", "input_pdf_path", "file_name", "source_value", "input"):
        value = row.get(k)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in row.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--backup", action="store_true", default=True)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    outputs_dir = Path(args.outputs)

    if not csv_path.exists():
        print(f"[ERR] CSV not found: {csv_path}")
        return 2
    if not outputs_dir.exists():
        print(f"[WARN] outputs dir not found (treated as empty): {outputs_dir}")

    backup_path = csv_path.with_suffix(csv_path.suffix + ".bak")
    if args.backup:
        shutil.copy2(csv_path, backup_path)
        print(f"[INFO] backup saved to {backup_path}")

    output_stems = [path.stem for path in outputs_dir.iterdir()] if outputs_dir.exists() else []

    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            key = find_best_key(row)
            status = "MISSING"
            if key:
                try:
                    stem = Path(key).stem
                except Exception:
                    stem = key
                norm_key = str(stem).lower()
                matched = False
                for out_stem in output_stems:
                    if not out_stem:
                        continue
                    out_norm = out_stem.lower()
                    if out_norm == norm_key or norm_key in out_norm or out_norm in norm_key:
                        matched = True
                        break
                if matched:
                    status = "SUCCEEDED"
            else:
                status = "UNKNOWN"
            row["monkeyocr_status"] = status
            rows.append(row)

    if "monkeyocr_status" not in fieldnames:
        fieldnames.append("monkeyocr_status")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    counts = {"SUCCEEDED": 0, "MISSING": 0, "UNKNOWN": 0}
    for row in rows:
        counts.setdefault(row.get("monkeyocr_status", "MISSING"), 0)
        counts[row.get("monkeyocr_status", "MISSING")] += 1

    print(
        f"[INFO] Updated CSV {csv_path} — SUCCEEDED={counts['SUCCEEDED']} "
        f"MISSING={counts['MISSING']} UNKNOWN={counts['UNKNOWN']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
