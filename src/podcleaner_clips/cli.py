import sys

import typer

from podcleaner_clips import __version__
from podcleaner_clips.errors import ClipsError

app = typer.Typer(
    help="Découpe les extraits de film notés pendant le visionnage.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.callback()
def _root() -> None:
    """Garde les sous-commandes même quand il n'y en a qu'une."""


@app.command()
def version() -> None:
    """Affiche la version."""
    typer.echo(__version__)


def main() -> None:
    # Mode autonome de Click : il gère lui-même les erreurs d'usage (code 2) ;
    # ClipsError n'est pas une exception Click, elle remonte jusqu'ici.
    try:
        app()
    except ClipsError as exc:
        typer.echo(f"Erreur : {exc}", err=True)
        sys.exit(2)
