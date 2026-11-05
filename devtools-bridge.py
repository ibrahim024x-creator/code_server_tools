#!/usr/bin/env python3
"""
devtools-bridge — auto-discover installed dev tools on PATH and wire them
into VS Code / code-server settings.json + install matching extensions.

Usage:
  python3 devtools-bridge.py [--dry-run] [--settings PATH] [--registry PATH] [--install-extensions] [--report PATH]

Flags:
  --dry-run             Show what would change without writing or installing.
  --settings PATH       Target settings.json (default: auto-detect code-server
                        then VS Code, then .vscode/settings.json in cwd).
  --registry PATH       Path to registry.json (default: beside this script).
  --install-extensions  Actually install missing extensions via code-server/cli.
  --report PATH         Write a JSON discovery report to PATH.
  --no-merge            Overwrite settings.json instead of merging.
  --languages a,b,c     Limit to specific languages (comma-separated).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REGISTRY = SCRIPT_DIR / "registry.json"

# Priority order: first tool found per role per language wins, unless a later
# entry has higher priority. We keep it simple: first match in registry order.

# code-server / vs code CLI names to try, in priority order
CLI_NAMES = ["code-server", "code", "vscode", "codium"]

ROLE_ORDER = ["lsp", "dap", "formatter", "linter", "treeSitter", "compiler"]

ROLE_LABELS = {
    "lsp": "Language Server",
    "dap": "Debug Adapter",
    "formatter": "Formatter",
    "linter": "Linter",
    "treeSitter": "Tree-sitter",
    "compiler": "Compiler / Build Tool",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_on_path(names: list[str]) -> str | None:
    """Return the full path of the first executable found on PATH, or None."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def detect_editor_cli() -> str | None:
    """Find the code-server / code CLI available on PATH."""
    return find_on_path(CLI_NAMES)


def detect_settings_path(cli: str | None, explicit: str | None) -> Path:
    """Determine the target settings.json path."""
    if explicit:
        return Path(explicit)

    home = Path.home()

    # code-server default
    cs_settings = home / ".local" / "share" / "code-server" / "User" / "settings.json"
    if cs_settings.parent.exists():
        return cs_settings

    # VS Code default
    vs_settings = home / ".config" / "Code" / "User" / "settings.json"
    if vs_settings.parent.exists():
        return vs_settings

    # VSCodium
    vsc_settings = home / ".config" / "VSCodium" / "User" / "settings.json"
    if vsc_settings.parent.exists():
        return vsc_settings

    # Fallback: .vscode in cwd
    local = Path.cwd() / ".vscode" / "settings.json"
    return local


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"ERROR: registry not found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["languages"]


def fill_placeholders(value: Any, tool_path: str) -> Any:
    """Replace {path}, {basename}, {dir}, {env:VAR} placeholders in settings."""
    if isinstance(value, str):
        result = value
        if tool_path:
            p = Path(tool_path)
            result = result.replace("{path}", str(p))
            result = result.replace("{basename}", p.name)
            result = result.replace("{dir}", str(p.parent))
        # {env:VAR}
        if "{env:" in result:
            import re
            def _env_replace(m: "re.Match[str]") -> str:
                return os.environ.get(m.group(1), "")
            result = re.sub(r"\{env:([^}]+)\}", _env_replace, result)
        return result
    elif isinstance(value, dict):
        return {k: fill_placeholders(v, tool_path) for k, v in value.items()}
    elif isinstance(value, list):
        return [fill_placeholders(v, tool_path) for v in value]
    return value


def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base (overlay wins)."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_tools(
    languages: dict[str, Any], only: list[str] | None = None
) -> tuple[dict[str, dict[str, list[dict]]], list[str]]:
    """
    Scan PATH for every tool listed in the registry.

    Returns:
      discovered: { language -> { role -> [ {tool entry + _path} ] } }
      extensions:  flat list of unique extension IDs to install
    """
    discovered: dict[str, dict[str, list[dict]]] = {}
    extensions_seen: list[str] = []
    extensions_set: set[str] = set()

    lang_keys = list(languages.keys())
    if only:
        lang_keys = [l for l in lang_keys if l in only]

    for lang_key in lang_keys:
        lang_info = languages[lang_key]
        tools_by_role = lang_info.get("tools", {})
        lang_result: dict[str, list[dict]] = {}

        for role in ROLE_ORDER:
            tool_list = tools_by_role.get(role, [])
            found_for_role: list[dict] = []

            for tool in tool_list:
                execs = tool.get("executables", [])
                if not execs:
                    continue
                path = find_on_path(execs)
                if not path:
                    continue

                entry = dict(tool)
                entry["_path"] = path
                entry["_exec"] = Path(path).name
                found_for_role.append(entry)

                ext = tool.get("vscodeExtension", "").strip()
                if ext and ext not in extensions_set:
                    extensions_set.add(ext)
                    extensions_seen.append(ext)

            if found_for_role:
                lang_result[role] = found_for_role

        if lang_result:
            discovered[lang_key] = lang_result

    return discovered, extensions_seen


def pick_primary(discovered: dict) -> dict[str, dict[str, dict | None]]:
    """Pick the first found tool per role per language (the 'primary' choice)."""
    primary: dict[str, dict[str, dict | None]] = {}
    for lang, roles in discovered.items():
        primary[lang] = {}
        for role in ROLE_ORDER:
            tools = roles.get(role, [])
            primary[lang][role] = tools[0] if tools else None
    return primary


# ---------------------------------------------------------------------------
# Settings generation
# ---------------------------------------------------------------------------

def build_settings(
    discovered: dict[str, dict[str, list[dict]]],
) -> dict[str, Any]:
    """Build a settings dict from discovered tools (first per role wins)."""
    settings: dict[str, Any] = {}

    for lang_key in discovered:
        roles = discovered[lang_key]
        for role in ROLE_ORDER:
            tools = roles.get(role, [])
            if not tools:
                continue
            # First found = primary
            tool = tools[0]
            tool_path = tool.get("_path", "")
            raw_settings = tool.get("settings", {})
            if raw_settings:
                filled = fill_placeholders(raw_settings, tool_path)
                if isinstance(filled, dict):
                    settings = deep_merge(settings, filled)

    # Global convenience settings
    settings.setdefault("editor.formatOnSave", True)

    return settings


def write_settings(
    target: Path, new_settings: dict, merge: bool, dry_run: bool
) -> bool:
    """Write (or merge into) settings.json. Returns True if something changed."""
    existing: dict[str, Any] = {}
    if merge and target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, dict):
                existing = {}
        except (json.JSONDecodeError, OSError):
            existing = {}

    final = deep_merge(existing, new_settings) if merge else new_settings

    if final == existing:
        return False

    if dry_run:
        print(f"\n[DRY-RUN] Would write settings to: {target}")
        print(json.dumps(final, indent=2, ensure_ascii=False))
        return True

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return True


# ---------------------------------------------------------------------------
# Extension installation
# ---------------------------------------------------------------------------

def list_installed_extensions(cli: str) -> set[str]:
    """Return the set of installed extension IDs via the editor CLI."""
    try:
        result = subprocess.run(
            [cli, "--list-extensions"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return set()


def install_extensions(
    cli: str, extensions: list[str], installed: set[str], dry_run: bool
) -> list[str]:
    """Install missing extensions. Returns list of newly installed IDs."""
    newly: list[str] = []
    for ext in extensions:
        ext_lower = ext.lower()
        if ext_lower in installed:
            continue
        print(f"  Installing: {ext}")
        if dry_run:
            newly.append(ext)
            continue
        try:
            result = subprocess.run(
                [cli, "--install-extension", ext, "--force"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                newly.append(ext)
            else:
                print(f"    WARN: install failed: {result.stderr.strip()}")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            print(f"    WARN: install error: {e}")
    return newly


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(discovered: dict, primary: dict, extensions: list[str]):
    """Print a human-readable summary of what was discovered."""
    print("=" * 70)
    print("  DEVTOOLS-BRIDGE — DISCOVERY REPORT")
    print("=" * 70)

    if not discovered:
        print("\n  No supported tools found on PATH.\n")
        return

    for lang_key in sorted(discovered.keys()):
        roles = discovered[lang_key]
        print(f"\n  [{lang_key}]")
        for role in ROLE_ORDER:
            tools = roles.get(role, [])
            if not tools:
                continue
            label = ROLE_LABELS.get(role, role)
            for i, tool in enumerate(tools):
                marker = "  *" if i == 0 else "   "
                ext = tool.get("vscodeExtension", "—")
                print(f"  {marker} {label:20s}  {tool['_exec']:25s}  {tool['_path']}")
                if ext and ext != "—":
                    print(f"       {'':20s}  extension: {ext}")
            # Show missing roles
        missing = [ROLE_LABELS[r] for r in ROLE_ORDER if r not in roles]
        if missing:
            print(f"       (not found: {', '.join(missing)})")

    print(f"\n  Extensions needed ({len(extensions)}):")
    for ext in extensions:
        print(f"    - {ext}")
    print("=" * 70)


def write_report_json(path: Path, discovered: dict, extensions: list[str]):
    """Write a machine-readable JSON report."""
    clean: dict[str, Any] = {}
    for lang, roles in discovered.items():
        clean[lang] = {}
        for role, tools in roles.items():
            clean[lang][role] = [
                {
                    "executable": t["_exec"],
                    "path": t["_path"],
                    "extension": t.get("vscodeExtension", ""),
                }
                for t in tools
            ]
    report = {
        "discovered": clean,
        "extensions": extensions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-discover dev tools on PATH and configure VS Code / code-server."
    )
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--settings", default=None, help="Path to settings.json.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Path to registry.json.")
    parser.add_argument("--install-extensions", action="store_true", help="Install missing extensions.")
    parser.add_argument("--report", default=None, help="Write JSON report to this path.")
    parser.add_argument("--no-merge", action="store_true", help="Overwrite settings instead of merging.")
    parser.add_argument("--languages", default=None, help="Comma-separated language keys to limit to.")
    args = parser.parse_args()

    # Load registry
    registry_path = Path(args.registry)
    languages = load_registry(registry_path)

    # Filter languages
    only = None
    if args.languages:
        only = [l.strip() for l in args.languages.split(",") if l.strip()]
        unknown = [l for l in only if l not in languages]
        if unknown:
            print(f"WARN: unknown language(s): {', '.join(unknown)}", file=sys.stderr)

    # Discover
    print("Scanning PATH for installed development tools...")
    discovered, extensions = discover_tools(languages, only=only)
    primary = pick_primary(discovered)

    # Report
    print_report(discovered, primary, extensions)

    if not discovered:
        print("\nNo tools found. Nothing to configure.")
        return 0

    # Settings
    cli = detect_editor_cli()
    settings_path = detect_settings_path(cli, args.settings)
    print(f"\nSettings target: {settings_path}")
    if cli:
        print(f"Editor CLI: {cli}")
    else:
        print("Editor CLI: not found on PATH (will still write settings)")

    new_settings = build_settings(discovered)
    changed = write_settings(
        settings_path, new_settings, merge=not args.no_merge, dry_run=args.dry_run
    )
    if changed:
        if args.dry_run:
            print("[DRY-RUN] Settings not written.")
        else:
            print(f"Settings written to {settings_path}")
    else:
        print("Settings already up to date.")

    # Extensions
    if args.install_extensions and cli:
        installed = list_installed_extensions(cli)
        newly = install_extensions(cli, extensions, installed, args.dry_run)
        if newly:
            print(f"\nInstalled {len(newly)} extension(s): {', '.join(newly)}")
        else:
            print("\nAll required extensions already installed.")
    elif extensions and not args.install_extensions:
        print(f"\n{len(extensions)} extension(s) needed. Use --install-extensions to install them.")

    # JSON report
    if args.report:
        report_path = Path(args.report)
        write_report_json(report_path, discovered, extensions)
        print(f"Report written to {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
