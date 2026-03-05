#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import List


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def process_file(path: Path, mode: str, keys: List[str], inplace: bool, suffix: str, backup: bool):
    data = load_json(path)
    original_keys = list(data.keys()) if isinstance(data, dict) else []

    if not isinstance(data, dict):
        raise ValueError(f"File {path} does not contain a top-level JSON object; skipping.")

    if mode == "keep":
        pruned = {k: data[k] for k in keys if k in data}
    else:  # remove
        pruned = {k: v for k, v in data.items() if k not in set(keys)}

    if inplace:
        out_path = path
        if backup:
            bak = path.with_suffix(path.suffix + ".bak.json")
            write_json(bak, data)
    else:
        out_path = path.with_name(path.stem + suffix + path.suffix)

    write_json(out_path, pruned)

    kept = list(pruned.keys())
    removed = [k for k in original_keys if k not in kept]
    print(f"Processed {path.name}: kept={kept}, removed={removed}, output={out_path.name}")


def gather_files(paths: List[str]):
    files = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend([str(x) for x in pp.glob("*.json")])
        else:
            files.append(str(pp))
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description="Strip unwanted top-level sections from conference proceeding JSON files.")
    parser.add_argument("paths", nargs="+", help="Files or directories to process")
    parser.add_argument("--mode", choices=("keep", "remove"), default="keep", help="Whether `keys` lists keys to keep or to remove (default: keep)")
    parser.add_argument("--keys", nargs="*", help="List of top-level keys to keep/remove (overrides config)")
    parser.add_argument("--config", help="JSON config file with shape {\"mode\":\"keep\"|\"remove\", \"keys\": [..]}"
                        )
    parser.add_argument("--inplace", action="store_true", help="Overwrite original files (a .bak.json backup will be created if --backup is set)")
    parser.add_argument("--backup", action="store_true", help="Save a .bak.json backup when --inplace is used")
    parser.add_argument("--suffix", default=".stripped", help="Suffix to append to output files before extension (default .stripped)")

    args = parser.parse_args(argv)

    config_mode = None
    config_keys = None
    if args.config:
        cfg = load_json(Path(args.config))
        config_mode = cfg.get("mode")
        config_keys = cfg.get("keys")

    mode = args.mode if args.keys is None or len(args.keys) == 0 and not config_mode is None else args.mode
    keys = args.keys if args.keys else config_keys

    if not keys:
        print("No keys provided (via --keys or --config). Nothing to do.")
        sys.exit(1)

    files = gather_files(args.paths)
    if not files:
        print("No files found to process.")
        sys.exit(1)

    for f in files:
        try:
            process_file(Path(f), mode if config_mode is None else config_mode, keys, args.inplace, args.suffix, args.backup)
        except Exception as e:
            print(f"Error processing {f}: {e}")


if __name__ == "__main__":
    main()
