"""Find code that works on macOS but breaks on Windows.

Flags, in every .py file under a folder:
- text files opened, read or written without `encoding=` (Windows defaults to cp1252);
- hard-coded absolute paths (`/Users/…`, `/home/…`, `/Volumes/…`, `C:\\…`);
- `shell=True` (quoting differs between cmd.exe and sh).

Usage: python scripts/check_windows_compat.py [folder]   (default: src)
Exit code 1 when something is found.
"""

import ast
import re
import sys
from pathlib import Path

_HARD_CODED = re.compile(r"^(/Users/|/home/|/Volumes/|[A-Za-z]:[\\/])")
_ENCODING = 'text file without encoding=: add encoding="utf-8"'
_PATH = "hard-coded path: take it from the configuration or build it with pathlib"
_SHELL = "shell=True: pass a list of arguments instead"


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_binary(mode: ast.expr | None) -> bool:
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def _call_problem(call: ast.Call) -> str | None:
    shell = _keyword(call, "shell")
    if isinstance(shell, ast.Constant) and shell.value is True:
        return _SHELL
    if _keyword(call, "encoding") is not None:
        return None
    func = call.func
    if isinstance(func, ast.Name) and func.id == "open":  # open(path, mode)
        mode = call.args[1] if len(call.args) > 1 else _keyword(call, "mode")
        return None if _is_binary(mode) else _ENCODING
    if isinstance(func, ast.Attribute):
        if func.attr == "open":  # Path.open(mode)
            mode = call.args[0] if call.args else _keyword(call, "mode")
            return None if _is_binary(mode) else _ENCODING
        if func.attr in ("read_text", "write_text"):
            return _ENCODING
    return None


def check(root: Path) -> list[str]:
    """One `file:line: message` per problem, files relative to `root`, in path order."""
    root = Path(root)
    problems: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                problem = _call_problem(node)
                if problem:
                    found.append((node.lineno, problem))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _HARD_CODED.match(node.value)
            ):
                found.append((node.lineno, _PATH))
        rel = path.relative_to(root).as_posix()
        problems += [f"{rel}:{line}: {message}" for line, message in sorted(found)]
    return problems


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src")
    problems = check(root)
    for problem in problems:
        print(problem)
    print(f"{len(problems)} problem(s) found in {root}." if problems else f"{root}: nothing found.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
