"""Hook PostToolUse : lint Ruff puis tests pytest après chaque modification d'un fichier Python.

Écrit en Python pour tourner à l'identique sur macOS et Windows.
Si le projet a un uv.lock, les outils passent par `uv run` (environnement du projet) ;
sinon, Ruff et pytest sont pris dans le PATH, et ignorés sans erreur s'ils manquent.
Les tests marqués `slow` (modèle Whisper) ne sont pas lancés.
Un échec renvoie le code 2 : Claude reçoit la sortie et corrige.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def tool_cmd(name: str, project: Path) -> list[str] | None:
    """Commande pour lancer un outil : via uv si le projet en a un, sinon PATH ou module."""
    uv = shutil.which("uv")
    if uv and (project / "uv.lock").is_file():
        return [uv, "run", "--quiet", name]
    if shutil.which(name):
        return [name]
    probe = run([sys.executable, "-m", name, "--version"], project)
    return [sys.executable, "-m", name] if probe.returncode == 0 else None


def main() -> int:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd()))
    errors: list[str] = []

    ruff = tool_cmd("ruff", project)
    if ruff:
        run([*ruff, "format", file_path], project)
        lint = run([*ruff, "check", "--fix", file_path], project)
        if lint.returncode != 0:
            errors.append(f"Ruff :\n{lint.stdout}{lint.stderr}")

    pytest = tool_cmd("pytest", project)
    if pytest and (project / "tests").is_dir():
        tests = run([*pytest, "-q", "-x", "--no-header", "-m", "not slow"], project)
        # Code 5 : aucun test collecté, ce n'est pas un échec.
        if tests.returncode not in (0, 5):
            errors.append(f"pytest :\n{tests.stdout[-4000:]}{tests.stderr[-2000:]}")

    if errors:
        print("\n\n".join(errors), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
