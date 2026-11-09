import sys
from pathlib import Path
from typing import Annotated

import typer

from podcleaner_clips import __version__, config
from podcleaner_clips.errors import ClipsError

app = typer.Typer(
    help="Découpe les extraits de film notés pendant le visionnage.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.callback()
def _root() -> None:
    """Garde les sous-commandes même quand il n'y en a qu'une."""


config_app = typer.Typer(help="Crée ou affiche le fichier de configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help=f"Fichier de configuration (sinon {config.CONFIG_ENV_VAR}, puis l'emplacement usuel).",
    ),
]


@app.command()
def version() -> None:
    """Affiche la version."""
    typer.echo(__version__)


@config_app.command("init")
def config_init(config_path: ConfigOption = None) -> None:
    """Crée un fichier de configuration commenté, à compléter."""
    path = config.resolve_config_path(config_path)
    config.write_template(path)
    typer.echo(f"Fichier de configuration créé : {path}")
    typer.echo("Ouvrez-le et indiquez au moins dossier_episodes et son_transition.")


@config_app.command("show")
def config_show(config_path: ConfigOption = None) -> None:
    """Affiche la configuration lue, valeurs par défaut comprises."""
    path = config.resolve_config_path(config_path)
    settings = config.load_settings(path)
    typer.echo(f"Fichier : {path}")
    for key, value in config.describe(settings):
        typer.echo(f"{key} = {value}")


def main() -> None:
    # Mode autonome de Click : il gère lui-même les erreurs d'usage (code 2) ;
    # ClipsError n'est pas une exception Click, elle remonte jusqu'ici.
    try:
        app()
    except ClipsError as exc:
        typer.echo(f"Erreur : {exc}", err=True)
        sys.exit(2)
