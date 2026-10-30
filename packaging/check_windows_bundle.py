"""Developer regression for Windows Qt/system-ICU packaging compatibility."""

import argparse
import json
from pathlib import Path

import pefile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Directory containing SOMA.exe and _internal")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    forbidden = sorted(str(path.relative_to(bundle)) for path in bundle.rglob("*")
                       if path.is_file() and path.name.lower() in {"icuuc.dll", "icudt78.dll"})
    core = bundle / "_internal/PySide6/Qt6Core.dll"
    result = {"passed": False, "bundle": str(bundle), "forbidden_icu_files": forbidden,
              "scope": "static PE import and bundle inventory regression; native smoke remains required"}
    try:
        if forbidden:
            raise ValueError("Third-party ICU basename collision is present")
        with pefile.PE(str(core), fast_load=True) as binary:
            binary.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            imports = [entry for entry in binary.DIRECTORY_ENTRY_IMPORT if entry.dll.lower() == b"icuuc.dll"]
            symbols = sorted(item.name.decode("ascii") for entry in imports for item in entry.imports if item.name)
        result["qt_system_icu_imports"] = symbols
        if "ucnv_open" not in symbols or "ucnv_close" not in symbols:
            raise ValueError("Qt system-ICU import assumption changed; review packaging policy")
        result["passed"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
