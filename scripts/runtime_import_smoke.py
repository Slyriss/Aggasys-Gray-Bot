from __future__ import annotations

import importlib
import argparse


CORE_RUNTIME_IMPORTS = {
    "python-telegram-bot": "telegram",
    "asyncpg": "asyncpg",
    "pgvector": "pgvector",
    "redis": "redis",
    "python-dotenv": "dotenv",
    "duckduckgo-search": "duckduckgo_search",
    "pytz": "pytz",
    "tzdata": "tzdata",
    "httpx": "httpx",
    "pdfplumber": "pdfplumber",
}

HEAVY_RUNTIME_IMPORTS = {
    "faster-whisper": "faster_whisper",
}

RUNTIME_IMPORTS = {**CORE_RUNTIME_IMPORTS, **HEAVY_RUNTIME_IMPORTS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import runtime dependencies needed by Gray.")
    parser.add_argument(
        "--include-heavy",
        action="store_true",
        help="Also import heavyweight optional runtime modules such as faster-whisper.",
    )
    args = parser.parse_args(argv)

    imports = dict(CORE_RUNTIME_IMPORTS)
    if args.include_heavy:
        imports.update(HEAVY_RUNTIME_IMPORTS)

    errors: list[str] = []
    for package, module in sorted(imports.items()):
        try:
            importlib.import_module(module)
        except Exception as exc:
            errors.append(f"{package} ({module}) failed to import: {type(exc).__name__}: {exc}")

    if errors:
        print("Runtime import smoke failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    suffix = " including heavyweight imports" if args.include_heavy else ""
    print(f"Runtime import smoke OK{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
