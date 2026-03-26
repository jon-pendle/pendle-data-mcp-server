#!/usr/bin/env python3
"""
Validate per-market TOML files against the schema defined in
risk/market-params/market-params-overview.md.

Usage:
    python3 scripts/validate_toml.py                    # check all TOMLs
    python3 scripts/validate_toml.py path/to/file.toml  # check specific files
    python3 scripts/validate_toml.py --staged           # check only git-staged TOMLs

Exit code: 0 if all valid, 1 if any errors found.
"""

import re
import sys
import subprocess
from pathlib import Path

try:
    import tomllib                  # stdlib in Python 3.11+
except ImportError:
    try:
        import tomli as tomllib     # backport: pip install tomli
    except ImportError:
        sys.exit(
            "error: tomllib not found.\n"
            "  Python ≥ 3.11: it's in the stdlib — check your Python version.\n"
            "  Python < 3.11: run `pip install tomli` (or `./scripts/setup.sh`)."
        )

# ── Schema ──────────────────────────────────────────────────────────────────

# Required top-level string fields
TOP_LEVEL_REQUIRED = ["margin_type", "maturity"]

# Required sections (must exist as a dict key in the TOML)
REQUIRED_SECTIONS = ["Margin", "OrderBounds", "MitigatingMeasure", "Oracle"]

# Required fields within each section
SECTION_REQUIRED_FIELDS = {
    "Margin": ["kIM", "kMM", "I_threshold", "t_threshold"],
    "OrderBounds": [
        "k_MD",
        "k_CO",
        "limit_Order_Upper_Slope",
        "limit_Order_Lower_Slope",
    ],
    "MitigatingMeasure": ["hard_OI_cap"],
    "Oracle": ["mark_rate_twap_duration"],
}

# Optional sections — validated only if present
OPTIONAL_SECTIONS = {
    "AMM": [
        # "initial_supply_cap_usd" OR "initial_supply_cap" (older BTC/ETH-collateral markets)
        # checked separately below via AMM_SUPPLY_CAP_FIELDS
        "min_rate",
        "max_rate",
        "initial_rate",
        "initial_size",
        "flip_liquidity",
        "initial_cash",
    ],
    "AutomaticResponses": [],   # no required sub-fields defined
    "MaturityAdjustment": [],   # no required sub-fields defined
}

# AMM supply cap: one of these must be present (old vs new schema)
AMM_SUPPLY_CAP_FIELDS = ["initial_supply_cap_usd", "initial_supply_cap"]

VALID_MARGIN_TYPES = {"Cross", "Isolated"}

# ── Validator ────────────────────────────────────────────────────────────────

# boros-research MarketParams files use several non-standard TOML value literals.
# We preprocess them into valid TOML before parsing so we can check required fields.

# 1. Bare fraction: `kIM = 1/3.2`
_FRACTION_RE = re.compile(
    r"^(\s*\w+\s*=\s*)(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)\s*$",
    re.MULTILINE,
)
# 2. Dollar-shorthand: `hard_OI_cap = $20M` or `initial_supply_cap_usd = $15k`
_DOLLAR_RE = re.compile(
    r"^(\s*\w+\s*=\s*)(\$[^\s#\n]+)",
    re.MULTILINE,
)
# 3. Percent literal: `fee_rate = 0%`
_PERCENT_RE = re.compile(
    r"^(\s*\w+\s*=\s*)(\d+(?:\.\d+)?)%\s*$",
    re.MULTILINE,
)
# 4. Comma-formatted numbers: `initial_size = 29,870.96` (not valid TOML)
_COMMA_NUM_RE = re.compile(
    r"^(\s*\w+\s*=\s*)(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s*$",
    re.MULTILINE,
)


def _preprocess(raw: str) -> str:
    """Normalise non-standard value literals so standard tomllib can parse them.

    All non-standard forms are converted to their nearest valid TOML equivalent
    (floats for fractions/percents, quoted strings for dollar-shorthands).
    Field-presence checking is not affected by type coercions.
    """
    def _eval_fraction(m: re.Match) -> str:
        try:
            value = float(m.group(2)) / float(m.group(3))
            return f"{m.group(1)}{value}"
        except ZeroDivisionError:
            return m.group(0)

    def _quote_dollar(m: re.Match) -> str:
        return f'{m.group(1)}"{m.group(2)}"'

    def _eval_percent(m: re.Match) -> str:
        return f"{m.group(1)}{float(m.group(2)) / 100}"

    def _strip_commas(m: re.Match) -> str:
        return f"{m.group(1)}{m.group(2).replace(',', '')}"

    raw = _FRACTION_RE.sub(_eval_fraction, raw)
    raw = _DOLLAR_RE.sub(_quote_dollar, raw)
    raw = _PERCENT_RE.sub(_eval_percent, raw)
    raw = _COMMA_NUM_RE.sub(_strip_commas, raw)
    return raw


def validate_file(path: Path) -> list[str]:
    """Return a list of error strings for the given TOML file, or [] if valid."""
    errors = []

    try:
        raw = path.read_text(encoding="utf-8")
        processed = _preprocess(raw)
        data = tomllib.loads(processed)
    except tomllib.TOMLDecodeError as e:
        return [f"TOML parse error: {e}"]

    # Top-level required fields
    for field in TOP_LEVEL_REQUIRED:
        if field not in data:
            errors.append(f"missing top-level field: `{field}`")

    # margin_type value check
    if "margin_type" in data and data["margin_type"] not in VALID_MARGIN_TYPES:
        errors.append(
            f"`margin_type` must be one of {VALID_MARGIN_TYPES}, got: {data['margin_type']!r}"
        )

    # Required sections and their fields
    for section in REQUIRED_SECTIONS:
        if section not in data:
            errors.append(f"missing required section: `[{section}]`")
            continue
        sec = data[section]
        for field in SECTION_REQUIRED_FIELDS.get(section, []):
            if field not in sec:
                errors.append(f"`[{section}]` missing required field: `{field}`")

    # Optional sections — only validate fields if the section exists
    for section, required_fields in OPTIONAL_SECTIONS.items():
        if section not in data:
            continue
        sec = data[section]
        for field in required_fields:
            if field not in sec:
                errors.append(f"`[{section}]` missing required field: `{field}`")

    # AMM supply cap: accept either initial_supply_cap_usd (new) or initial_supply_cap (old)
    if "AMM" in data:
        if not any(f in data["AMM"] for f in AMM_SUPPLY_CAP_FIELDS):
            errors.append(
                f"`[AMM]` missing required field: `initial_supply_cap_usd` "
                f"(or legacy `initial_supply_cap`)"
            )

    return errors


# ── Entry point ──────────────────────────────────────────────────────────────

def get_staged_toml_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return [
        repo_root / p
        for p in result.stdout.splitlines()
        if p.startswith("risk/market-params/") and p.endswith(".toml")
    ]


def get_all_toml_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "risk" / "market-params").rglob("*.toml"))


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    args = sys.argv[1:]

    if "--staged" in args:
        files = get_staged_toml_files(repo_root)
        if not files:
            print("validate_toml: no staged TOML files to check.")
            return 0
    elif args:
        files = [Path(a).resolve() for a in args if not a.startswith("--")]
    else:
        files = get_all_toml_files(repo_root)

    if not files:
        print("validate_toml: no TOML files found.")
        return 0

    total_errors = 0
    for path in files:
        errors = validate_file(path)
        if errors:
            rel = path.relative_to(repo_root)
            for e in errors:
                print(f"  ❌  {rel}: {e}")
            total_errors += len(errors)

    if total_errors:
        print(f"\nvalidate_toml: {total_errors} error(s) found across {sum(1 for p in files if validate_file(p))} file(s).")
        return 1

    print(f"validate_toml: all {len(files)} file(s) OK ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
