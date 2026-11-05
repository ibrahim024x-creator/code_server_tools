#!/usr/bin/env python3
"""
Tests for registry.json correctness — verifies no deprecated VS Code settings,
no incorrect extension IDs, no wrong role assignments, and valid JSON structure.

Run: python3 test_registry.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PASS = 0
FAIL = 0

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}  {detail}")


REGISTRY_PATH = Path(__file__).resolve().parent / "registry.json"

with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
    registry = json.load(f)

languages = registry["languages"]

# Deprecated Python settings that should NOT appear anywhere
DEPRECATED_PYTHON_SETTINGS = {
    "python.formatting.provider",
    "python.linting.enabled",
    "python.linting.ruffEnabled",
    "python.linting.flake8Enabled",
    "python.linting.pylintEnabled",
    "python.linting.mypyEnabled",
    "python.linting.pycodestyleEnabled",
    "python.linting.pydocstyleEnabled",
    "python.formatting.blackPath",
    "python.formatting.autopep8Path",
    "python.formatting.yapfPath",
}

# Settings that belong only in launch.json, not settings.json
LAUNCH_ONLY_SETTINGS = {
    "miDebuggerPath",
    "MIMode",
}

# Known-fake extension IDs that should not be used
FAKE_EXTENSIONS = {
    "nvim-treesitter.python",  # Neovim, not VS Code
    "nvim-treesitter.javascript",
    "vscodevim.vim",  # Was incorrectly used for vtsls
    "github.vscode-codeql",  # Was incorrectly used for cppcheck
    "ms-vscode.node-extension-pack",  # Does not exist on Marketplace
    "MS-CEINTUL.vscode-cppcheck",  # Does not exist on Marketplace
}

# python.languageServer valid values (from official docs)
VALID_PYTHON_LS_VALUES = {"Pylance", "Pylsp", "Jedi", "JediLSP", "None", "Default"}


def collect_all_settings(obj: dict, prefix: str = "") -> list[str]:
    """Recursively collect all setting keys from a nested dict."""
    keys = []
    for k, v in obj.items():
        full = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict) and k != "[python]" and not k.startswith("["):
            keys.extend(collect_all_settings(v, full))
        else:
            keys.append(full)
    return keys


def get_all_settings_strings(obj: dict) -> dict:
    """Flatten a settings dict into {full_key: value} pairs."""
    result = {}
    for k, v in obj.items():
        if isinstance(v, dict) and not k.startswith("["):
            for sub_k, sub_v in get_all_settings_strings(v).items():
                result[f"{k}.{sub_k}"] = sub_v
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# JSON structure
# ---------------------------------------------------------------------------

def test_json_structure():
    print("\n--- JSON structure ---")
    check("$schema replaced with _description", "_description" in registry, "found $schema" if "$schema" in registry else "")
    check("languages key exists", "languages" in registry)
    check("at least 10 languages", len(languages) >= 10, f"got {len(languages)}")


def test_no_tree_sitter_arrays():
    """No language should have a treeSitter array in tools (removed from discovery)."""
    print("\n--- No treeSitter arrays in languages ---")
    for lang_key, lang_info in languages.items():
        tools = lang_info.get("tools", {})
        check(f"{lang_key}: no treeSitter key in tools", "treeSitter" not in tools, f"found treeSitter in {lang_key}")


def test_tree_sitter_no_neovim():
    """treeSitter section should not contain Neovim extension IDs."""
    print("\n--- treeSitter section cleanup ---")
    ts = registry.get("treeSitter", {})
    check("treeSitter has note", "note" in ts)
    check("treeSitter has no extensions dict", "extensions" not in ts, "still has Neovim extensions")


# ---------------------------------------------------------------------------
# Python settings
# ---------------------------------------------------------------------------

def test_python_no_deprecated():
    print("\n--- Python: no deprecated settings ---")
    for lang_key, lang_info in languages.items():
        tools = lang_info.get("tools", {})
        for role, tool_list in tools.items():
            if not isinstance(tool_list, list):
                continue
            for tool in tool_list:
                settings = tool.get("settings", {})
                if not settings:
                    continue
                flat = get_all_settings_strings(settings)
                for dep_key in DEPRECATED_PYTHON_SETTINGS:
                    if dep_key in flat:
                        check(f"{lang_key}.{role}: no '{dep_key}'", False, f"found in {tool.get('executables', [])}")
                # Also check top-level keys
                for key in settings:
                    if key in DEPRECATED_PYTHON_SETTINGS:
                        check(f"{lang_key}.{role}: no '{key}'", False, "deprecated at top level")


def test_python_language_server_values():
    """python.languageServer should only have valid values, not 'Ruff'."""
    print("\n--- Python: valid languageServer values ---")
    py = languages.get("python", {})
    tools = py.get("tools", {})
    for role, tool_list in tools.items():
        for tool in tool_list:
            settings = tool.get("settings", {})
            ls_val = settings.get("python.languageServer")
            if ls_val is not None:
                check(
                    f"python.{role}: languageServer='{ls_val}' is valid",
                    ls_val in VALID_PYTHON_LS_VALUES,
                    f"'{ls_val}' not in {VALID_PYTHON_LS_VALUES}",
                )


def test_python_ruff_settings():
    """Ruff should use modern extension settings, not python.languageServer."""
    print("\n--- Python: Ruff uses modern settings ---")
    py = languages.get("python", {})
    tools = py.get("tools", {})
    for role, tool_list in tools.items():
        for tool in tool_list:
            execs = tool.get("executables", [])
            if "ruff" not in execs:
                continue
            settings = tool.get("settings", {})
            # Ruff should NOT set python.languageServer
            check(
                f"python.{role} ruff: no python.languageServer",
                "python.languageServer" not in settings,
                f"found python.languageServer={settings.get('python.languageServer')}",
            )
            # Ruff should set ruff.path
            check(
                f"python.{role} ruff: has ruff.path",
                "ruff.path" in settings,
                f"settings keys: {list(settings.keys())}",
            )


def test_python_formatter_extensions():
    """Python formatters should use correct modern extension IDs."""
    print("\n--- Python: formatter extension IDs ---")
    py = languages.get("python", {})
    formatters = py.get("tools", {}).get("formatter", [])
    for tool in formatters:
        execs = tool.get("executables", [])
        ext = tool.get("vscodeExtension", "")
        if "black" in execs:
            check(f"black extension is ms-python.vscode-black-formatter", ext == "ms-python.vscode-black-formatter", f"got {ext}")
        if "autopep8" in execs:
            check(f"autopep8 extension is ms-python.autopep8", ext == "ms-python.autopep8", f"got {ext}")
        if "ruff" in execs:
            check(f"ruff extension is charliermarsh.ruff", ext == "charliermarsh.ruff", f"got {ext}")


def test_python_linter_extensions():
    """Python linters should use correct modern extension IDs and settings."""
    print("\n--- Python: linter extension IDs ---")
    py = languages.get("python", {})
    linters = py.get("tools", {}).get("linter", [])
    for tool in linters:
        execs = tool.get("executables", [])
        ext = tool.get("vscodeExtension", "")
        settings = tool.get("settings", {})
        if "flake8" in execs:
            check(f"flake8 extension is ms-python.flake8", ext == "ms-python.flake8", f"got {ext}")
            check(f"flake8 uses flake8.path", "flake8.path" in settings, f"settings: {list(settings.keys())}")
        if "pylint" in execs:
            check(f"pylint extension is ms-python.pylint", ext == "ms-python.pylint", f"got {ext}")
            check(f"pylint uses pylint.path", "pylint.path" in settings, f"settings: {list(settings.keys())}")
        if "mypy" in execs:
            check(f"mypy extension is ms-python.mypy-type-checker", ext == "ms-python.mypy-type-checker", f"got {ext}")


def test_python_ruff_not_in_lsp():
    """Ruff should not be listed as an LSP — it's a formatter/linter, not a language server."""
    print("\n--- Python: Ruff not in LSP role ---")
    py = languages.get("python", {})
    lsps = py.get("tools", {}).get("lsp", [])
    ruff_in_lsp = any("ruff" in t.get("executables", []) for t in lsps)
    check("ruff not in python LSP", not ruff_in_lsp, "ruff found in LSP list")


def test_python_pyright_extension():
    """Pyright should use ms-pyright.pyright, not ms-python.python."""
    print("\n--- Python: Pyright extension ID ---")
    py = languages.get("python", {})
    lsps = py.get("tools", {}).get("lsp", [])
    for tool in lsps:
        if "pyright" in tool.get("executables", []):
            ext = tool.get("vscodeExtension", "")
            check(f"pyright extension is ms-pyright.pyright", ext == "ms-pyright.pyright", f"got {ext}")


# ---------------------------------------------------------------------------
# C/C++ settings
# ---------------------------------------------------------------------------

def test_cpp_no_fake_lsp():
    """cpptools/cpp-tools should not be listed as LSP executables."""
    print("\n--- C/C++: no fake LSP executables ---")
    cpp = languages.get("c_cpp", {})
    lsps = cpp.get("tools", {}).get("lsp", [])
    for tool in lsps:
        execs = tool.get("executables", [])
        check(f"no 'cpptools' in LSP", "cpptools" not in execs, f"found in {execs}")
        check(f"no 'cpp-tools' in LSP", "cpp-tools" not in execs, f"found in {execs}")


def test_cpp_no_midebugger_in_settings():
    """miDebuggerPath should not appear in settings.json — it's launch.json only."""
    print("\n--- C/C++: miDebuggerPath not in settings ---")
    for lang_key, lang_info in languages.items():
        tools = lang_info.get("tools", {})
        for role, tool_list in tools.items():
            if not isinstance(tool_list, list):
                continue
            for tool in tool_list:
                settings = tool.get("settings", {})
                flat = get_all_settings_strings(settings)
                for launch_key in LAUNCH_ONLY_SETTINGS:
                    check(f"{lang_key}.{role}: no '{launch_key}' in settings", launch_key not in flat, f"found in {tool.get('executables', [])}")


def test_cpp_clangd_disables_cpptools_intellisense():
    """When clangd is the LSP, C_Cpp.intellisenseEngine should be disabled."""
    print("\n--- C/C++: clangd disables IntelliSense ---")
    cpp = languages.get("c_cpp", {})
    lsps = cpp.get("tools", {}).get("lsp", [])
    for tool in lsps:
        if "clangd" in tool.get("executables", []):
            settings = tool.get("settings", {})
            check(
                "clangd settings disable C_Cpp.intellisenseEngine",
                settings.get("C_Cpp.intellisenseEngine") == "disabled",
                f"got {settings.get('C_Cpp.intellisenseEngine')}",
            )


def test_cpp_cppcheck_extension():
    """cppcheck should use the official CppcheckSolutionsAB extension."""
    print("\n--- C/C++: cppcheck extension ---")
    cpp = languages.get("c_cpp", {})
    linters = cpp.get("tools", {}).get("linter", [])
    for tool in linters:
        if "cppcheck" in tool.get("executables", []):
            ext = tool.get("vscodeExtension", "")
            check(f"cppcheck extension is not github.vscode-codeql", ext != "github.vscode-codeql", f"got {ext}")
            check(f"cppcheck extension is CppcheckSolutionsAB.cppcheck-official", ext == "CppcheckSolutionsAB.cppcheck-official", f"got {ext}")


def test_cpp_gdb_no_settings():
    """GDB should not have miDebuggerPath in settings.json."""
    print("\n--- C/C++: GDB no settings ---")
    cpp = languages.get("c_cpp", {})
    daps = cpp.get("tools", {}).get("dap", [])
    for tool in daps:
        if "gdb" in tool.get("executables", []):
            settings = tool.get("settings", {})
            check("gdb has no miDebuggerPath setting", "miDebuggerPath" not in settings, f"found: {settings}")


# ---------------------------------------------------------------------------
# JS/TS settings
# ---------------------------------------------------------------------------

def test_js_vtsls_extension():
    """vtsls should use yiontech.vtsls, not vscodevim.vim."""
    print("\n--- JS/TS: vtsls extension ---")
    js = languages.get("javascript_typescript", {})
    lsps = js.get("tools", {}).get("lsp", [])
    for tool in lsps:
        if "vtsls" in tool.get("executables", []):
            ext = tool.get("vscodeExtension", "")
            check(f"vtsls extension is yiontech.vtsls", ext == "yiontech.vtsls", f"got {ext}")


def test_js_eslint_extension():
    """eslint should use dbaeumer.vscode-eslint."""
    print("\n--- JS/TS: eslint extension ---")
    js = languages.get("javascript_typescript", {})
    linters = js.get("tools", {}).get("linter", [])
    for tool in linters:
        if "eslint" in tool.get("executables", []):
            ext = tool.get("vscodeExtension", "")
            check(f"eslint extension is dbaeumer.vscode-eslint", ext == "dbaeumer.vscode-eslint", f"got {ext}")


# ---------------------------------------------------------------------------
# Ruby
# ---------------------------------------------------------------------------

def test_ruby_rubocop_not_lsp():
    """RuboCop is a linter/formatter, not an LSP."""
    print("\n--- Ruby: RuboCop not in LSP ---")
    rb = languages.get("ruby", {})
    lsps = rb.get("tools", {}).get("lsp", [])
    rubocop_in_lsp = any("rubocop" in t.get("executables", []) for t in lsps)
    check("rubocop not in ruby LSP", not rubocop_in_lsp, "rubocop found in LSP")


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------

def test_php_dap():
    """PHP DAP should not list xdebug as an executable."""
    print("\n--- PHP: DAP executables ---")
    php = languages.get("php", {})
    daps = php.get("tools", {}).get("dap", [])
    for tool in daps:
        execs = tool.get("executables", [])
        check("no 'xdebug' in PHP DAP executables", "xdebug" not in execs, f"found in {execs}")


# ---------------------------------------------------------------------------
# C#
# ---------------------------------------------------------------------------

def test_csharp_lsp():
    """C# LSP should not list dotnet/roslyn as standalone LSP executables."""
    print("\n--- C#: LSP executables ---")
    cs = languages.get("csharp", {})
    lsps = cs.get("tools", {}).get("lsp", [])
    for tool in lsps:
        execs = tool.get("executables", [])
        check("no 'dotnet' in C# LSP", "dotnet" not in execs, f"found in {execs}")
        check("no 'roslyn' in C# LSP", "roslyn" not in execs, f"found in {execs}")


# ---------------------------------------------------------------------------
# Lua
# ---------------------------------------------------------------------------

def test_lua_emmylua_not_lsp():
    """emmylua-ls should not be in LSP with a debug extension."""
    print("\n--- Lua: emmylua-ls not in LSP ---")
    lua = languages.get("lua", {})
    lsps = lua.get("tools", {}).get("lsp", [])
    for tool in lsps:
        execs = tool.get("executables", [])
        if "emmylua-ls" in execs:
            ext = tool.get("vscodeExtension", "")
            check(f"emmylua-ls not using debug extension", ext != "actboy168.lua-debug", f"got {ext}")


# ---------------------------------------------------------------------------
# Dart
# ---------------------------------------------------------------------------

def test_dart_dap():
    """Dart DAP should have dart/flutter — the Dart extension provides DAP, this is acceptable."""
    print("\n--- Dart: DAP ---")
    dart = languages.get("dart", {})
    daps = dart.get("tools", {}).get("dap", [])
    check("dart DAP has entries", len(daps) > 0)
    for tool in daps:
        ext = tool.get("vscodeExtension", "")
        check(f"dart DAP uses Dart-Code.dart-code", ext == "Dart-Code.dart-code", f"got {ext}")


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def test_sql_extension_no_space():
    """SQL extension ID should not have a leading space."""
    print("\n--- SQL: extension ID no space ---")
    sql = languages.get("sql", {})
    for role, tool_list in sql.get("tools", {}).items():
        if not isinstance(tool_list, list):
            continue
        for tool in tool_list:
            ext = tool.get("vscodeExtension", "")
            check(f"sql.{role} extension '{ext}' has no leading space", not ext.startswith(" "), f"found space in '{ext}'")


# ---------------------------------------------------------------------------
# languageId arrays
# ---------------------------------------------------------------------------

def test_language_id_arrays():
    """Merged languages should have languageId as array."""
    print("\n--- languageId as arrays ---")
    for lang_key, lang_info in languages.items():
        lid = lang_info.get("languageId")
        check(f"{lang_key}: languageId is a list", isinstance(lid, list), f"got {type(lid).__name__}: {lid}")


# ---------------------------------------------------------------------------
# No fake extension IDs anywhere
# ---------------------------------------------------------------------------

def test_no_fake_extensions():
    """No extension ID in the registry should be a known-fake ID."""
    print("\n--- No fake extension IDs ---")
    for lang_key, lang_info in languages.items():
        tools = lang_info.get("tools", {})
        for role, tool_list in tools.items():
            if not isinstance(tool_list, list):
                continue
            for tool in tool_list:
                ext = tool.get("vscodeExtension", "")
                for fake in FAKE_EXTENSIONS:
                    check(f"{lang_key}.{role}: ext '{ext}' != '{fake}'", ext != fake, "fake extension found")


# ---------------------------------------------------------------------------
# No empty treeSitter arrays in tools
# ---------------------------------------------------------------------------

def test_no_empty_tools():
    """Tools should not have empty treeSitter arrays."""
    print("\n--- No empty treeSitter in tools ---")
    for lang_key, lang_info in languages.items():
        tools = lang_info.get("tools", {})
        for role in ["treeSitter"]:
            check(f"{lang_key}: no treeSitter role in tools", role not in tools)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  REGISTRY.JSON CORRECTNESS TEST SUITE")
    print("=" * 60)

    test_json_structure()
    test_no_tree_sitter_arrays()
    test_tree_sitter_no_neovim()
    test_python_no_deprecated()
    test_python_language_server_values()
    test_python_ruff_settings()
    test_python_formatter_extensions()
    test_python_linter_extensions()
    test_python_ruff_not_in_lsp()
    test_python_pyright_extension()
    test_cpp_no_fake_lsp()
    test_cpp_no_midebugger_in_settings()
    test_cpp_clangd_disables_cpptools_intellisense()
    test_cpp_cppcheck_extension()
    test_cpp_gdb_no_settings()
    test_js_vtsls_extension()
    test_js_eslint_extension()
    test_ruby_rubocop_not_lsp()
    test_php_dap()
    test_csharp_lsp()
    test_lua_emmylua_not_lsp()
    test_dart_dap()
    test_sql_extension_no_space()
    test_language_id_arrays()
    test_no_fake_extensions()
    test_no_empty_tools()

    print("\n" + "=" * 60)
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    return 1 if FAIL > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
