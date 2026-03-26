# Boros Knowledge Base

Structured knowledge base for **Boros** — an onchain interest rate swap platform for perpetual funding rates.

Intended as LLM context. Start with [`INDEX.md`](INDEX.md) for a full file map.

## Structure

```
overview/          Platform overview
mechanics/         Lite paper, whitepaper, proofs
risk/              Risk framework, parameters, alert specs
  global/          Global param values and constraints
  market-params/   Per-market TOML configs by maturity
markets/           Listed markets and listing strategy
liquidity/         Market makers, terms, depth requirements
user-acquisition/  Trading strategies and use cases
```

## Conventions

- See [`CLAUDE.md`](CLAUDE.md) for authoring rules and LLM integration instructions
- Markdown for docs, YAML for structured data, TOML for market params
- YAML frontmatter on every `.md` file (`description`, `last_updated`, `related`)
- Keep `INDEX.md` in sync when adding/removing files
