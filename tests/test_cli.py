import subprocess
import sys

from typer.testing import CliRunner

from podcleaner_clips.cli import app


def test_version_command_prints_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_unknown_command_is_a_usage_error_without_traceback():
    script = (
        "from podcleaner_clips.cli import main\n"
        "import sys; sys.argv = ['podcleaner-clips', 'nope']\n"
        "main()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 2
    assert "nope" in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr


def test_clips_error_exits_2_with_message():
    # Runs the real main() entry point in a subprocess, with a command
    # added for the test that raises ClipsError.
    script = (
        "from podcleaner_clips.cli import app, main\n"
        "from podcleaner_clips.errors import ClipsError\n"
        "@app.command('boom')\n"
        "def boom():\n"
        "    raise ClipsError('Fichier introuvable : x.mkv')\n"
        "import sys; sys.argv = ['podcleaner-clips', 'boom']\n"
        "main()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 2
    assert "Erreur : Fichier introuvable : x.mkv" in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
