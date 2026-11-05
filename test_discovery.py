#!/usr/bin/env python3
"""
Tests for devtools-bridge — version-suffixed executable discovery,
version parsing, deduplication, and sorting logic.

Run: python3 test_discovery.py
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

# Import devtools-bridge.py (dash in filename prevents normal import)
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "devtools_bridge", str(Path(__file__).resolve().parent / "devtools-bridge.py")
)
dt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dt)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

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


def make_executable(path: Path):
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def create_fake_tools(tmpdir: Path, names: list[str]) -> None:
    """Create dummy executables in tmpdir."""
    for name in names:
        p = tmpdir / name
        p.write_text("#!/bin/sh\necho '1.0.0'\n")
        make_executable(p)


# ---------------------------------------------------------------------------
# Version suffix parsing
# ---------------------------------------------------------------------------

def test_version_suffix_parsing():
    print("\n--- Version suffix parsing ---")

    check(
        "clangd-23 -> (23,)",
        dt.parse_version_suffix("clangd-23", "clangd") == (23,),
        f"got {dt.parse_version_suffix('clangd-23', 'clangd')}",
    )
    check(
        "clang-format-19 -> (19,)",
        dt.parse_version_suffix("clang-format-19", "clang-format") == (19,),
        f"got {dt.parse_version_suffix('clang-format-19', 'clang-format')}",
    )
    check(
        "clang-tidy-18 -> (18,)",
        dt.parse_version_suffix("clang-tidy-18", "clang-tidy") == (18,),
    )
    check(
        "python3.13 -> (3, 13)",
        dt.parse_version_suffix("python3.13", "python") == (3, 13),
        f"got {dt.parse_version_suffix('python3.13', 'python')}",
    )
    check(
        "python3 -> (3,)",
        dt.parse_version_suffix("python3", "python") == (3,),
    )
    check(
        "node22 -> (22,)",
        dt.parse_version_suffix("node22", "node") == (22,),
    )
    check(
        "clangd (exact) -> None",
        dt.parse_version_suffix("clangd", "clangd") is None,
    )
    check(
        "clangd-something -> None (non-numeric suffix)",
        dt.parse_version_suffix("clangd-something", "clangd") is None,
    )
    check(
        "gcc-14.2.0 -> (14, 2, 0)",
        dt.parse_version_suffix("gcc-14.2.0", "gcc") == (14, 2, 0),
    )
    check(
        "rust-analyzer (no version) -> None",
        dt.parse_version_suffix("rust-analyzer", "rust-analyzer") is None,
    )
    check(
        "rust-analyzer-1.85 -> (1, 85)",
        dt.parse_version_suffix("rust-analyzer-1.85", "rust-analyzer") == (1, 85),
    )
    check(
        "g++-14 -> (14,)",
        dt.parse_version_suffix("g++-14", "g++") == (14,),
    )
    check(
        "shellcheck-0.10.0 -> (0, 10, 0)",
        dt.parse_version_suffix("shellcheck-0.10.0", "shellcheck") == (0, 10, 0),
    )
    check(
        "sqlfluff-3.2 -> (3, 2)",
        dt.parse_version_suffix("sqlfluff-3.2", "sqlfluff") == (3, 2),
    )
    check(
        "base123abc -> None (trailing non-digits after version)",
        dt.parse_version_suffix("base123abc", "base") is None,
    )


def test_version_str():
    print("\n--- version_str formatting ---")
    check("version_str((23,)) == '23'", dt.version_str((23,)) == "23")
    check("version_str((3, 13)) == '3.13'", dt.version_str((3, 13)) == "3.13")
    check("version_str(None) == ''", dt.version_str(None) == "")
    check("version_str((14, 2, 0)) == '14.2.0'", dt.version_str((14, 2, 0)) == "14.2.0")


# ---------------------------------------------------------------------------
# find_all_versions_on_path
# ---------------------------------------------------------------------------

def test_find_all_versions_basic():
    print("\n--- find_all_versions_on_path: basic ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["clangd", "clangd-18", "clangd-19", "clangd-20"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            results = dt.find_all_versions_on_path(["clangd"])
        finally:
            os.environ["PATH"] = old_path

        check("found 4 variants", len(results) == 4, f"got {len(results)}")
        # unversioned should be first (highest priority)
        check(
            "unversioned clangd is first",
            results[0]["exec"] == "clangd" and results[0]["version"] is None,
            f"first={results[0]}",
        )
        # versioned should be sorted descending
        check(
            "clangd-20 is second (highest version)",
            results[1]["exec"] == "clangd-20" and results[1]["version"] == (20,),
            f"second={results[1]}",
        )
        check(
            "clangd-19 is third",
            results[2]["exec"] == "clangd-19",
        )
        check(
            "clangd-18 is fourth",
            results[3]["exec"] == "clangd-18",
        )
        # All paths should be in tmpdir
        for r in results:
            check(f"path {r['path']} in tmpdir", str(tmpdir) in r["path"])


def test_find_all_versions_dedup():
    print("\n--- find_all_versions_on_path: deduplication ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # Only versioned, no plain
        create_fake_tools(tmpdir, ["clangd-18", "clangd-19"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            results = dt.find_all_versions_on_path(["clangd"])
        finally:
            os.environ["PATH"] = old_path

        check("found 2 (no unversioned)", len(results) == 2, f"got {len(results)}")
        check("highest version first", results[0]["exec"] == "clangd-19")
        check("lower version second", results[1]["exec"] == "clangd-18")


def test_find_all_versions_multi_dir_dedup():
    """If same executable appears in two PATH dirs, only the first is kept."""
    print("\n--- find_all_versions_on_path: multi-dir dedup ---")
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        d1, d2 = Path(tmp1), Path(tmp2)
        create_fake_tools(d1, ["clangd-20"])
        create_fake_tools(d2, ["clangd-20"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{d1}{os.pathsep}{d2}"
        try:
            results = dt.find_all_versions_on_path(["clangd"])
        finally:
            os.environ["PATH"] = old_path

        check("only one clangd-20 despite two dirs", len(results) == 1, f"got {len(results)}")
        if results:
            check("path is from first dir", str(d1) in results[0]["path"], f"path={results[0]['path']}")


def test_find_all_versions_no_matches():
    print("\n--- find_all_versions_on_path: no matches ---")
    with tempfile.TemporaryDirectory() as tmp:
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmp)
        try:
            results = dt.find_all_versions_on_path(["nonexistent-tool-xyz"])
        finally:
            os.environ["PATH"] = old_path
        check("empty result for nonexistent tool", len(results) == 0)


def test_find_all_versions_dash_suffix():
    """Test tools with dash in base name: clang-format-19, clang-tidy-18."""
    print("\n--- find_all_versions_on_path: dash-suffix tools ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["clang-format", "clang-format-18", "clang-format-19"])
        create_fake_tools(tmpdir, ["clang-tidy-17", "clang-tidy-18"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            fmt_results = dt.find_all_versions_on_path(["clang-format"])
            tidy_results = dt.find_all_versions_on_path(["clang-tidy"])
        finally:
            os.environ["PATH"] = old_path

        check("clang-format: 3 found", len(fmt_results) == 3, f"got {len(fmt_results)}")
        check("clang-format (unversioned) first", fmt_results[0]["exec"] == "clang-format")
        check("clang-format-19 second", fmt_results[1]["exec"] == "clang-format-19")
        check("clang-format-18 third", fmt_results[2]["exec"] == "clang-format-18")

        check("clang-tidy: 2 found", len(tidy_results) == 2, f"got {len(tidy_results)}")
        check("clang-tidy-18 first (highest)", tidy_results[0]["exec"] == "clang-tidy-18")
        check("clang-tidy-17 second", tidy_results[1]["exec"] == "clang-tidy-17")


def test_find_all_versions_direct_suffix():
    """Test tools with direct version suffix: python3.13, node22."""
    print("\n--- find_all_versions_on_path: direct-suffix tools ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["python3.12", "python3.13", "python3"])
        create_fake_tools(tmpdir, ["node", "node20", "node22"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            py_results = dt.find_all_versions_on_path(["python", "python3"])
            node_results = dt.find_all_versions_on_path(["node"])
        finally:
            os.environ["PATH"] = old_path

        # python3 (exact) + python3.12 + python3.13
        check("python variants: 3 found", len(py_results) == 3, f"got {len(py_results)}: {py_results}")
        check("python3 (exact) first", py_results[0]["exec"] == "python3", f"first={py_results[0]}")
        check("python3.13 second (highest)", py_results[1]["exec"] == "python3.13", f"second={py_results[1]}")
        check("python3.12 third", py_results[2]["exec"] == "python3.12", f"third={py_results[2]}")

        # node (exact) + node22 + node20
        check("node variants: 3 found", len(node_results) == 3, f"got {len(node_results)}")
        check("node (exact) first", node_results[0]["exec"] == "node")
        check("node22 second (highest)", node_results[1]["exec"] == "node22")
        check("node20 third", node_results[2]["exec"] == "node20")


def test_find_all_versions_multi_name():
    """When multiple base names given, results from all are merged."""
    print("\n--- find_all_versions_on_path: multiple base names ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["gcc", "gcc-13", "gcc-14"])
        create_fake_tools(tmpdir, ["clang", "clang-18"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            results = dt.find_all_versions_on_path(["gcc", "g++", "cc", "c++", "clang", "clang++"])
        finally:
            os.environ["PATH"] = old_path

        exec_names = [r["exec"] for r in results]
        check("gcc in results", "gcc" in exec_names)
        check("gcc-14 in results", "gcc-14" in exec_names)
        check("gcc-13 in results", "gcc-13" in exec_names)
        check("clang in results", "clang" in exec_names)
        check("clang-18 in results", "clang-18" in exec_names)


def test_find_all_versions_preserves_full_path():
    """All returned paths must be full absolute paths."""
    print("\n--- find_all_versions_on_path: full paths ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp).resolve()
        create_fake_tools(tmpdir, ["clangd", "clangd-19"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            results = dt.find_all_versions_on_path(["clangd"])
        finally:
            os.environ["PATH"] = old_path

        for r in results:
            p = Path(r["path"])
            check(f"{r['exec']} path is absolute", p.is_absolute(), f"path={r['path']}")
            check(f"{r['exec']} path exists", p.exists())


def test_find_all_versions_non_executable_ignored():
    """Files without executable bit should not be discovered."""
    print("\n--- find_all_versions_on_path: ignores non-executables ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # Create a non-executable versioned file
        (tmpdir / "clangd-99").write_text("#!/bin/sh\necho '99.0.0'\n")
        # Don't set executable bit

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            results = dt.find_all_versions_on_path(["clangd"])
        finally:
            os.environ["PATH"] = old_path

        check("non-executable clangd-99 ignored", len(results) == 0, f"got {results}")


# ---------------------------------------------------------------------------
# discover_tools integration
# ---------------------------------------------------------------------------

def test_discover_tools_with_versioned():
    """Full discover_tools flow with versioned executables."""
    print("\n--- discover_tools: versioned executables ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["clangd", "clangd-18", "clangd-19"])
        create_fake_tools(tmpdir, ["gcc", "gcc-13", "gcc-14"])
        create_fake_tools(tmpdir, ["gdb"])

        languages = {
            "c_cpp": {
                "extensions": [".c"],
                "filetypes": ["c"],
                "languageId": "cpp",
                "tools": {
                    "lsp": [
                        {
                            "executables": ["clangd"],
                            "vscodeExtension": "llvm-vs-code-extensions.vscode-clangd",
                            "settings": {"clangd.path": "{path}"},
                        }
                    ],
                    "dap": [
                        {
                            "executables": ["gdb"],
                            "vscodeExtension": "ms-vscode.cpptools",
                            "settings": {"miDebuggerPath": "{path}"},
                        }
                    ],
                    "compiler": [
                        {
                            "executables": ["gcc", "g++", "cc", "c++"],
                            "vscodeExtension": "ms-vscode.cpptools",
                            "settings": {},
                        }
                    ],
                },
            }
        }

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            discovered, extensions = dt.discover_tools(languages, only=["c_cpp"])
        finally:
            os.environ["PATH"] = old_path

        check("c_cpp discovered", "c_cpp" in discovered)
        check("lsp role found", "lsp" in discovered.get("c_cpp", {}))
        check("dap role found", "dap" in discovered.get("c_cpp", {}))
        check("compiler role found", "compiler" in discovered.get("c_cpp", {}))

        # clangd should have 3 variants (unversioned + 18 + 19), sorted highest first
        lsp_tools = discovered["c_cpp"]["lsp"]
        check("3 clangd variants found", len(lsp_tools) == 3, f"got {len(lsp_tools)}")
        check("clangd (unversioned) is first", lsp_tools[0]["_exec"] == "clangd")
        check("clangd-19 is second (highest version)", lsp_tools[1]["_exec"] == "clangd-19")
        check("clangd-18 is third", lsp_tools[2]["_exec"] == "clangd-18")

        # gcc should have 3 variants (unversioned + 13 + 14)
        compiler_tools = discovered["c_cpp"]["compiler"]
        check("3 gcc variants found", len(compiler_tools) == 3, f"got {len(compiler_tools)}")
        check("gcc (unversioned) is first", compiler_tools[0]["_exec"] == "gcc")
        check("gcc-14 is second (highest)", compiler_tools[1]["_exec"] == "gcc-14")
        check("gcc-13 is third", compiler_tools[2]["_exec"] == "gcc-13")

        # gdb should have 1
        dap_tools = discovered["c_cpp"]["dap"]
        check("1 gdb found", len(dap_tools) == 1)
        check("gdb is first", dap_tools[0]["_exec"] == "gdb")

        # _version field should be set
        check("clangd-19 _version == (19,)", lsp_tools[1]["_version"] == (19,))
        check("clangd (unversioned) _version == None", lsp_tools[0]["_version"] is None)
        check("gcc-14 _version == (14,)", compiler_tools[1]["_version"] == (14,))


def test_discover_tools_no_duplicates_same_path():
    """If the same executable path is reachable via two registry entries, no duplicate."""
    print("\n--- discover_tools: no duplicate paths ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["ruff"])

        languages = {
            "python": {
                "extensions": [".py"],
                "filetypes": ["python"],
                "languageId": "python",
                "tools": {
                    "lsp": [
                        {
                            "executables": ["ruff", "ruff-lsp"],
                            "vscodeExtension": "charliermarsh.ruff",
                            "settings": {},
                        }
                    ],
                    "formatter": [
                        {
                            "executables": ["ruff"],
                            "vscodeExtension": "charliermarsh.ruff",
                            "settings": {},
                        }
                    ],
                },
            }
        }

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            discovered, _ = dt.discover_tools(languages, only=["python"])
        finally:
            os.environ["PATH"] = old_path

        lsp_tools = discovered["python"]["lsp"]
        check("only 1 ruff in lsp (no duplicate path)", len(lsp_tools) == 1, f"got {len(lsp_tools)}")


# ---------------------------------------------------------------------------
# Version extraction from --version output
# ---------------------------------------------------------------------------

def test_extract_version_from_output():
    print("\n--- extract_version_from_output ---")
    check(
        "gcc output -> 14.2.0",
        dt.extract_version_from_output("gcc (Debian 14.2.0-19) 14.2.0") == "14.2.0",
    )
    check(
        "node output -> 22.23.4",
        dt.extract_version_from_output("v22.23.4") == "22.23.4",
    )
    check(
        "python output -> 3.13.5",
        dt.extract_version_from_output("Python 3.13.5") == "3.13.5",
    )
    check(
        "clangd output -> 18.1.8",
        dt.extract_version_from_output("LLVM (http://llvm.org/):\n  clangd version 18.1.8") == "18.1.8",
    )
    check(
        "empty output -> ''",
        dt.extract_version_from_output("") == "",
    )
    check(
        "no version number -> ''",
        dt.extract_version_from_output("some text without version") == "",
    )
    check(
        "multi-line, version on second line -> 3.2.0",
        dt.extract_version_from_output("sqlfluff\n  Version 3.2.0\n") == "3.2.0",
    )


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def test_backward_compat_find_on_path():
    """find_on_path still works as before for simple lookups."""
    print("\n--- backward compat: find_on_path ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["mytool"])

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            result = dt.find_on_path(["mytool"])
            check("find_on_path finds mytool", result is not None and "mytool" in result)

            result_none = dt.find_on_path(["nonexistent"])
            check("find_on_path returns None for missing", result_none is None)

            result_multi = dt.find_on_path(["first_missing", "mytool"])
            check("find_on_path tries multiple names", result_multi is not None and "mytool" in result_multi)
        finally:
            os.environ["PATH"] = old_path


def test_backward_compat_no_versioned():
    """When only unversioned tools exist, behavior matches old script."""
    print("\n--- backward compat: no versioned tools ---")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        create_fake_tools(tmpdir, ["clangd", "gcc", "gdb"])

        languages = {
            "c_cpp": {
                "extensions": [".c"],
                "filetypes": ["c"],
                "languageId": "cpp",
                "tools": {
                    "lsp": [
                        {
                            "executables": ["clangd"],
                            "vscodeExtension": "llvm-vs-code-extensions.vscode-clangd",
                            "settings": {"clangd.path": "{path}"},
                        }
                    ],
                    "compiler": [
                        {
                            "executables": ["gcc", "g++"],
                            "vscodeExtension": "ms-vscode.cpptools",
                            "settings": {},
                        }
                    ],
                },
            }
        }

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(tmpdir)
        try:
            discovered, extensions = dt.discover_tools(languages, only=["c_cpp"])
        finally:
            os.environ["PATH"] = old_path

        lsp = discovered["c_cpp"]["lsp"]
        check("1 clangd (no versioned)", len(lsp) == 1)
        check("clangd _version is None", lsp[0]["_version"] is None)
        check("clangd _exec == 'clangd'", lsp[0]["_exec"] == "clangd")

        comp = discovered["c_cpp"]["compiler"]
        check("1 gcc (no versioned)", len(comp) == 1)
        check("gcc _exec == 'gcc'", comp[0]["_exec"] == "gcc")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  DEVTOOLS-BRIDGE — TEST SUITE")
    print("=" * 60)

    test_version_suffix_parsing()
    test_version_str()
    test_find_all_versions_basic()
    test_find_all_versions_dedup()
    test_find_all_versions_multi_dir_dedup()
    test_find_all_versions_no_matches()
    test_find_all_versions_dash_suffix()
    test_find_all_versions_direct_suffix()
    test_find_all_versions_multi_name()
    test_find_all_versions_preserves_full_path()
    test_find_all_versions_non_executable_ignored()
    test_discover_tools_with_versioned()
    test_discover_tools_no_duplicates_same_path()
    test_extract_version_from_output()
    test_backward_compat_find_on_path()
    test_backward_compat_no_versioned()

    print("\n" + "=" * 60)
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    return 1 if FAIL > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
