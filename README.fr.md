# podcleaner-clips

**Français** · [English](README.md)

Un outil en ligne de commande qui découpe dans un film les extraits notés pendant le visionnage et les range, prêts à être diffusés en direct pendant l'enregistrement d'un épisode de podcast.

## Ce que fait l'outil

Pendant le visionnage, on écrit un fichier de notes par film, une ligne par extrait : le timecode de début, quelques mots de la réplique, le timecode de fin.

```markdown
# The Night Before
fichier: The Night Before (2015) Bluray-1080p.mkv

2:35 d'une fabuleuse soirée incroyable 2:51
27:15 ce bébé c'est une connerie 27:37
43:00 si je veux la sucer … Isaac va sucer 44:08
```

Ensuite, `podcleaner-clips run notes.md` :

- choisit la piste en version française (VF), celle de France (VFF) quand il y a aussi une version québécoise (VFQ) ; prévient si aucune piste n'est marquée française ;
- retrouve chaque réplique dans les sous-titres français quand le film en a, puis dans le doublage avec Whisper (seulement autour de chaque extrait, jamais le film entier) ;
- cale le début et la fin sur des limites de phrase à 15 s au plus de vos timecodes, sans couper un mot, avec tous les fragments notés à l'intérieur ;
- ajoute des fondus de 0,7 s et votre son de transition avant et après l'extrait, puis normalise à -16 LUFS / -1 dBTP ;
- écrit un WAV 48 kHz, un MP4 H.264 (écran noir pendant la transition) et un index `extraits.json` des coupes retenues ;
- aux passages suivants, ne refait que les extraits ajoutés ou modifiés, et renomme les fichiers des extraits déplacés.

```
The Night Before (2015)/
  audio/NB-08-ce-bebe-c-est-une-connerie.wav
  video/NB-08-ce-bebe-c-est-une-connerie.mp4
  extraits.json
```

## Installation

Il faut :

- macOS ou Windows ;
- [uv](https://docs.astral.sh/uv/) (il installe le bon Python, 3.11 ou 3.12) ;
- [ffmpeg](https://ffmpeg.org/) dans le `PATH` : `brew install ffmpeg` sur macOS, `winget install ffmpeg` sur Windows.

```bash
git clone https://github.com/IvesPower/podcleaner-clips.git
cd podcleaner-clips
uv sync
uv run podcleaner-clips version
```

Le premier passage qui repère des répliques télécharge le modèle Whisper (`large-v3-turbo`, plus de 1 Go). Sur un Mac Apple Silicon, il tourne avec MLX ; ailleurs, avec faster-whisper sur le processeur.

## Configuration

Chaque personne a son propre fichier de configuration. Créez-le, puis ouvrez-le :

```bash
uv run podcleaner-clips config init
```

Il est créé dans `~/Library/Application Support/podcleaner-clips/config.toml` sur macOS et dans `%LOCALAPPDATA%\podcleaner-clips\config.toml` sur Windows (`--config` ou la variable `PODCLEANER_CLIPS_CONFIG` permettent d'en utiliser un autre). Retirez le `#` devant au moins les deux lignes ci-dessous. Sur Windows, écrivez les chemins avec des `/` (`"C:/Podcast/Episodes"`) ou entre apostrophes droites (`'C:\Podcast\Episodes'`) : un `\` entre guillemets est une séquence d'échappement en TOML.

```toml
dossier_episodes = "~/Podcast/Episodes"           # où ranger les extraits, un dossier par film
son_transition = "~/Podcast/sons/transition.wav"  # joué avant et après chaque extrait
```

Facultatif : `dossier_films` (où chercher un film nommé dans les notes), `doublage_prefere = "VFQ"`, et les sections `[ajustement]`, `[son]` et `[claude]`, toutes commentées dans le fichier. Vérifiez ce qui est lu avec `uv run podcleaner-clips config show`.

## Le fichier de notes

- Une ligne par extrait : `début référence fin`. Timecodes en `HH:MM:SS` ou `MM:SS` (`45:12` = 45 min 12 s) ; `6;25` et `25 min 30` sont compris aussi.
- Les timecodes peuvent être décalés d'une dizaine de secondes et la référence ne compter que quelques mots, même mal orthographiés. Séparez plusieurs fragments d'une longue scène par `…`, `...` ou ` - `.
- Lignes d'en-tête, avant le premier extrait : `# Titre`, `fichier: <film>` (chemin absolu, ou relatif au fichier de notes ou à `dossier_films`), `abreviation: NB` (écrite par l'outil si elle manque).
- Toute autre ligne est ignorée : on peut garder d'autres notes dans le même fichier. L'ancienne forme `- 00:12:34 > 00:12:51 | réplique` est acceptée.

## Lancer

```bash
uv run podcleaner-clips run notes.md
```

| Option | Effet |
| --- | --- |
| `--dry-run` | Trouve les coupes et les affiche, sans rien écrire |
| `--film CHEMIN` | Utilise ce film au lieu de `fichier:` |
| `--no-transition` | Fondus seuls, sans son de transition ni écran noir |
| `--audio-only` / `--video-only` | Seulement les WAV / seulement les MP4 |
| `--no-adjust` | Coupe exactement aux timecodes notés (sans sous-titres, Whisper ni Claude) |
| `--audio-track N` | Utilise la piste audio N (à partir de 0) si les pistes sont mal étiquetées |
| `--config CHEMIN` | Utilise un autre fichier de configuration |

Le résumé affiche, pour chaque extrait, les timecodes notés et retenus, la durée et ce qui a été fait (`new`, `changed`, `unchanged`, `renamed`). Une ligne `⚠` signale un doute : réplique introuvable (les timecodes notés sont gardés) ou trouvée mais peu sûre. Écoutez ceux-là en premier. Les fichiers des extraits retirés des notes sont listés, jamais supprimés. Le code de sortie vaut 1 si un extrait a échoué (par exemple, s'il finit après le film).

## Claude, facultatif

Aucun compte n'est nécessaire. Si `ANTHROPIC_API_KEY` est définie, Claude propose l'abréviation du film et choisit les bornes de chaque extrait à partir de la transcription ; ses réponses sont contrôlées (à 15 s au plus de vos timecodes, tous les fragments inclus) et gardées dans `extraits.json`. Sans clé, ou si Claude est injoignable, l'abréviation reprend les initiales du titre et la coupe se fait sur la limite de phrase la plus proche de chaque timecode noté. Pour le désactiver : `actif = false` dans `[claude]`.

## Contribuer

Les contributions sont les bienvenues. Lisez [CONTRIBUTING.fr.md](CONTRIBUTING.fr.md) : chaque modification passe par une pull request relue par le mainteneur, et les commits suivent [Conventional Commits](https://www.conventionalcommits.org/). Le [cahier des charges](docs/spec.fr.md) et le [plan d'implémentation](docs/superpowers/plans/2026-11-06-podcleaner-clips-v1.fr.md) expliquent les choix faits.

```bash
uv run pytest            # tests rapides (sans Whisper ni réseau)
uv run pytest -m slow    # tests qui chargent un modèle Whisper
uv run ruff check
```

## Licence

[MIT](LICENSE)
