# Boros Knowledge Base

This repository is the **internal** knowledge base for **Boros**, an onchain trading platform for interest rate swaps on funding rates. It's intended as context for LLM.

For protocol mechanics and architecture, the **canonical source of truth is the `dev-docs/` git submodule** (pinned to `pendle-finance/documentation`, accessible at `dev-docs/docs/boros-dev-docs/`). This KB covers internal/operational knowledge not found there: risk parameters, market makers, market listing, user acquisition strategies, known addresses, and **contract implementation details** (`contracts/`).

The `contracts/` section is the **internal-only** deep-dive into Boros smart contract internals (storage layout, type system, order book data structures, settlement algorithm, margin engine, AMM math, etc.).

## [To human] First-time setup

After cloning, run:
```bash
./setup.sh
```
This installs Python dependencies (only `tomli` on Python < 3.11; nothing on 3.11+), sets up the pre-commit hook that validates market-params TOML files, and initialises the `dev-docs` submodule.

To manually validate all TOML files at any time:
```bash
python3 scripts/validate_toml.py
```

## [To human] How to use this KB
Add this to your project's CLAUDE.md:

"When you need domain knowledge about Boros, read files from /path/to/boros-knowledge-base/.
  Start with INDEX.md to find the right files."

## How the KB is Structured

Start with `INDEX.md` — it maps every topic to its file path with a one-line summary. LLM will use it to decide which files to load for a given task.

### Submodule structure

The `dev-docs/` directory is a git submodule pointing to `pendle-finance/documentation`. `./setup.sh` initialises it automatically. To pull the latest dev docs manually:
```bash
git submodule update --remote dev-docs
```

### Where to look

| Need | Where to look |
|---|---|
| Risk params, zone thresholds, alert specs | This KB (`risk/`) |
| Market listing, MM terms, addresses | This KB (`markets/`, `liquidity/`, `known-addresses.yaml`) |
| User acquisition strategies | This KB (`user-acquisition/`) |
| **Contract internals** (storage, types, order book, settlement, margin, AMM, liquidation, bots, invariants) | This KB (`contracts/`) |
| Margin mechanics, fees, settlement, orderbook (user-facing) | Dev docs (`dev-docs/docs/boros-dev-docs/Mechanics/`) |
| Contract architecture, Router/MarketHub/Market (user-facing) | Dev docs (`dev-docs/docs/boros-dev-docs/HighLevelArchitecture.mdx`) |
| API/SDK integration | Dev docs (`dev-docs/docs/boros-dev-docs/Backend/`) |

**Do not duplicate content from the dev docs into this KB.** Reference it via `INDEX.md` instead.

### File Formats

- **Markdown** for prose documentation
- **YAML** for structured data lists (`markets.yaml`, `market-makers.yaml`)
- **TOML** for per-market risk parameters (follows `boros-research/MarketParams` format); see `risk/market-params/market-params-overview.md` for schema

## Authoring Conventions

1. **One topic per file.** Split if a file exceeds ~1500 words.
2. **YAML frontmatter on every markdown file** with `description`, `last_updated`, and `related` fields.
3. **Always update `last_updated`** in frontmatter when editing a file.
4. **Keep `INDEX.md` in sync** when adding or removing files.
5. **Log significant changes** in `changelog/CHANGELOG.md`.
6. **Structured data files are the source of truth.** Markdown docs reference them — don't duplicate values.
7. **Use relative paths** for all cross-references between files.
8. **Max 2 levels of directory nesting.** Keep the hierarchy flat for discoverability.
