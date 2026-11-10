import subprocess
import sys
from pathlib import Path

from check_windows_compat import check

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_windows_compat.py"
SRC = Path(__file__).resolve().parent.parent / "src"


def write(root: Path, name: str, code: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


def test_flags_text_files_without_encoding(tmp_path):
    write(
        tmp_path,
        "pkg/io.py",
        "from pathlib import Path\n"
        "p = Path('x')\n"
        "open(p)\n"
        "open(p, 'w')\n"
        "p.open()\n"
        "p.read_text()\n"
        "p.write_text('a')\n",
    )
    problems = check(tmp_path)
    assert [line.split(": ", 1)[0] for line in problems] == [
        "pkg/io.py:3",
        "pkg/io.py:4",
        "pkg/io.py:5",
        "pkg/io.py:6",
        "pkg/io.py:7",
    ]
    assert all("encoding" in line for line in problems)


def test_binary_files_and_explicit_encoding_are_fine(tmp_path):
    write(
        tmp_path,
        "ok.py",
        "from pathlib import Path\n"
        "p = Path('x')\n"
        "open(p, 'rb')\n"
        "open(p, mode='wb')\n"
        "p.open('rb')\n"
        "open(p, encoding='utf-8')\n"
        "p.read_text(encoding='utf-8')\n"
        "p.write_text('a', encoding='utf-8')\n"
        "p.read_bytes()\n",
    )
    assert check(tmp_path) == []


def test_flags_hard_coded_paths(tmp_path):
    write(
        tmp_path,
        "paths.py",
        "A = '/Users/me/films'\n"
        "B = 'C:\\\\Films\\\\x.mkv'\n"
        "C = 'D:/Films'\n"
        "D = '/home/me'\n"
        "E = 'films/x.mkv'\n",
    )
    problems = check(tmp_path)
    assert [line.split(": ", 1)[0] for line in problems] == [
        "paths.py:1",
        "paths.py:2",
        "paths.py:3",
        "paths.py:4",
    ]
    assert all("hard-coded path" in line for line in problems)


def test_flags_shell_true(tmp_path):
    write(
        tmp_path,
        "run.py",
        "import subprocess\n"
        "subprocess.run('ls', shell=True)\n"
        "subprocess.run(['ls'], shell=False)\n"
        "subprocess.check_output(['ls'])\n",
    )
    assert check(tmp_path) == ["run.py:2: shell=True: pass a list of arguments instead"]


def test_project_sources_are_clean():
    assert check(SRC) == []


def test_command_line_exit_codes(tmp_path):
    write(tmp_path, "bad.py", "open('x')\n")
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True
    )
    assert bad.returncode == 1 and "bad.py:1" in bad.stdout
    good = subprocess.run([sys.executable, str(SCRIPT), str(SRC)], capture_output=True, text=True)
    assert good.returncode == 0, good.stdout
