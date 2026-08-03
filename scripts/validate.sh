#!/usr/bin/env bash
# Validate the Forge toolkit structure: frontmatter, JSON, and hook scripts.
# Exit non-zero on any failure. Used locally and in CI.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

fail=0
err() { printf '  ✗ %s\n' "$1"; fail=1; }
ok() { printf '  ✓ %s\n' "$1"; }

# Extract the YAML frontmatter block (between the first two --- lines) and test
# whether a given key is present as a top-level key.
has_key() {
  awk -v key="$1" '
    NR==1 && $0!="---" { exit 1 }
    NR==1 { infm=1; next }
    infm && $0=="---" { exit 1 }   # reached end without finding key
    infm && $0 ~ "^"key":" { found=1; exit 0 }
  ' "$2"
}

frontmatter_check() {
  local label="$1"; shift
  local glob_dir="$1"; local pattern="$2"; shift 2
  local required=("$@")
  printf '\n%s\n' "$label"
  local found_any=0
  while IFS= read -r -d '' f; do
    found_any=1
    local missing=()
    # First line must be the frontmatter fence.
    if [[ "$(head -n1 "$f")" != "---" ]]; then
      err "$f — missing YAML frontmatter (must start with ---)"
      continue
    fi
    for k in "${required[@]}"; do
      has_key "$k" "$f" || missing+=("$k")
    done
    if ((${#missing[@]})); then
      err "$f — missing key(s): ${missing[*]}"
    else
      ok "$f"
    fi
  done < <(find "$glob_dir" -name "$pattern" -type f -print0)
  ((found_any)) || err "$label — no files found under $glob_dir"
}

PLUGIN="plugins/forge"

# --- Agents: require name + description ---
frontmatter_check "Agents ($PLUGIN/agents/*.md)" "$PLUGIN/agents" "*.md" name description

# --- Skills: require name + description on SKILL.md ---
frontmatter_check "Skills ($PLUGIN/skills/*/SKILL.md)" "$PLUGIN/skills" "SKILL.md" name description

# --- Commands: require description ---
frontmatter_check "Commands ($PLUGIN/commands/*.md)" "$PLUGIN/commands" "*.md" description

# --- Output styles: require name + description ---
if [ -d "$PLUGIN/output-styles" ]; then
  frontmatter_check "Output styles ($PLUGIN/output-styles/*.md)" "$PLUGIN/output-styles" "*.md" name description
fi

# --- JSON files parse (incl. *.json.example templates) ---
printf '\nJSON files\n'
while IFS= read -r -d '' j; do
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$j" 2>/dev/null; then
    ok "$j"
  else
    err "$j — invalid JSON"
  fi
done < <(find . \( -name "*.json" -o -name "*.json.example" \) -not -path "./.git/*" -not -path "./node_modules/*" -print0)

# --- Hook scripts are executable + python scripts compile ---
printf '\nHook scripts\n'
while IFS= read -r -d '' s; do
  if [[ -x "$s" ]]; then ok "$s (executable)"; else err "$s — not executable (chmod +x)"; fi
  if [[ "$s" == *.py ]]; then
    if python3 -m py_compile "$s" 2>/dev/null; then
      ok "$s (compiles)"
    else
      err "$s — syntax error"
    fi
  fi
done < <(find "$PLUGIN/hooks/scripts" -type f -print0)

# --- Skill scripts are executable + Python scripts compile ---
printf '\nSkill scripts\n'
while IFS= read -r -d '' s; do
  if [[ -x "$s" ]]; then ok "$s (executable)"; else err "$s — not executable"; fi
  if [[ "$s" == *.py ]]; then
    if python3 -m py_compile "$s" 2>/dev/null; then
      ok "$s (compiles)"
    else
      err "$s — syntax error"
    fi
  fi
done < <(find "$PLUGIN/skills" -path "*/scripts/*" -type f -print0)

# --- Marketplace source paths resolve to real plugin dirs ---
printf '\nMarketplace sources\n'
while IFS= read -r src; do
  [ -z "$src" ] && continue
  if [ -d "$src" ] && [ -f "$src/.claude-plugin/plugin.json" ]; then
    ok "$src (plugin manifest present)"
  else
    err "marketplace source '$src' has no plugin.json"
  fi
done < <(python3 -c '
import json
m = json.load(open(".claude-plugin/marketplace.json"))
for p in m.get("plugins", []):
    s = p.get("source")
    print(s if isinstance(s, str) else "")
')

# --- Claude/Codex/marketplace versions stay in lockstep ---
printf '\nManifest version parity\n'
if versions="$(python3 -c '
import json
paths = [
    "plugins/forge/.claude-plugin/plugin.json",
    "plugins/forge/.codex-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
]
claude = json.load(open(paths[0]))["version"]
codex = json.load(open(paths[1]))["version"]
market = json.load(open(paths[2]))
versions = [claude, codex, market["metadata"]["version"], market["plugins"][0]["version"]]
if len(set(versions)) != 1:
    raise SystemExit("version mismatch: " + ", ".join(versions))
print(claude)
')"; then
  ok "all manifests report $versions"
else
  err "Claude, Codex, and marketplace manifest versions differ"
fi

# --- Codex marketplace source resolves ---
printf '\nCodex marketplace source\n'
codex_source="$(python3 -c '
import json
p = json.load(open(".agents/plugins/marketplace.json"))["plugins"][0]["source"]
print(p["path"])
')"
if [ -d "$codex_source" ] && [ -f "$codex_source/.codex-plugin/plugin.json" ]; then
  ok "$codex_source (Codex plugin manifest present)"
else
  err "Codex marketplace source '$codex_source' has no plugin.json"
fi

# --- Canonical capability graph is up to date ---
printf '\nCanonical capability graph\n'
if python3 scripts/compile_capabilities.py --check >/dev/null 2>&1; then
  ok "data/capabilities.json matches Forge sources and host projections"
else
  err "capability graph is stale — run python3 scripts/compile_capabilities.py --write"
fi

# --- Deterministic host projections are reproducible ---
printf '\nCapability projections\n'
if python3 scripts/render_capabilities.py --check >/dev/null 2>&1; then
  ok "Claude, Codex, and Agent Skills projections are deterministic"
else
  err "capability projections are stale or non-deterministic"
fi

# --- Generated catalog is up to date ---
printf '\nGenerated catalog\n'
if python3 scripts/generate_catalog.py --check >/dev/null 2>&1; then
  ok "CATALOG.md and data/catalog.json are up to date"
else
  err "catalog is stale — run python3 scripts/generate_catalog.py"
fi

printf '\n'
if ((fail)); then
  printf '❌ Validation failed.\n'; exit 1
else
  printf '✅ All checks passed.\n'; exit 0
fi
