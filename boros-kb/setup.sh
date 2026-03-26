#!/usr/bin/env bash
# One-time setup for the boros-knowledge-base repo.
# Run after cloning (or re-cloning) to install deps and git hooks.
#
#   ./setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_TARGET="$REPO_ROOT/.git/hooks/pre-commit"

# ── 1. Python deps ───────────────────────────────────────────────────────────
echo "→ Installing Python dependencies..."
python3 -m pip install --quiet -r "$REPO_ROOT/requirements.txt"
echo "  done."

# ── 2. Pre-commit hook ───────────────────────────────────────────────────────
echo "→ Installing pre-commit hook..."

cat > "$HOOK_TARGET" << 'HOOK'
#!/usr/bin/env bash
# pre-commit hook: validate staged market-params TOML files

set -euo pipefail

STAGED=$(git diff --cached --name-only --diff-filter=ACM | grep '^risk/market-params/.*\.toml$' || true)
if [ -z "$STAGED" ]; then
  exit 0
fi

echo "validate_toml: checking staged TOML files..."
python3 "$(git rev-parse --show-toplevel)/scripts/validate_toml.py" --staged
HOOK

chmod +x "$HOOK_TARGET"
echo "  installed → .git/hooks/pre-commit"

# ── 3. Submodule ─────────────────────────────────────────────────────────────
echo "→ Initialising git submodule (dev-docs)..."
git -C "$REPO_ROOT" submodule update --init --recursive
echo "  done."

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "Setup complete. Run 'python3 scripts/validate_toml.py' to validate all TOMLs."
