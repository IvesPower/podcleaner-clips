import sys
from pathlib import Path

import pytest

# Lets tests import the helper scripts (make_test_film) like a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from make_test_film import make_test_film  # noqa: E402


@pytest.fixture(scope="session")
def test_film(tmp_path_factory) -> Path:
    """12 s test film: VFF, VO and VFQ tracks, cover art, no subtitles."""
    return make_test_film(tmp_path_factory.mktemp("film") / "test film.mkv")
