# podcleaner-clips

**Français** · [English](README.md)

Un outil en ligne de commande qui découpe dans un film les extraits notés pendant le visionnage et les range, prêts à être diffusés en direct pendant l'enregistrement d'un épisode de podcast.

## Ce que fait l'outil

Pendant le visionnage, on écrit un fichier de notes par film, une ligne par extrait : le timecode de début, quelques mots de la réplique, le timecode de fin.

```markdown
# Avengers
file: Avengers (2012) Bluray-1080p.mkv

5:20 monsieur, veuillez poser votre lance 5:30
7:00 la fourmi n'est pas en conflit avec la botte 7:10
21:45 on m'a dit qu'on avait gagné la guerre … on ne m'a pas dit ce qu'on avait perdu 21:58
```

Le fichier de notes complet de cet exemple est dans [`examples/avengers.md`](examples/avengers.md).

Ensuite, `pclips run notes.md` :

- choisit la piste en version française (VF), celle de France (VFF) quand il y a aussi une version québécoise (VFQ) ; prévient si aucune piste n'est marquée française ;
- retrouve chaque réplique dans les sous-titres français quand le film en a, puis dans le doublage avec Whisper (seulement autour de chaque extrait, jamais le film entier) ;
- cale le début et la fin sur des limites de phrase à 15 s au plus de vos timecodes, sans couper un mot, avec tous les fragments notés à l'intérieur ;
- ajoute des fondus de 0,7 s et votre son de transition avant et après l'extrait, puis normalise à -16 LUFS / -1 dBTP ;
- écrit un WAV 48 kHz, un MP4 H.264 (écran noir pendant la transition) et un index `clips.json` des coupes retenues ;
- aux passages suivants, ne refait que les extraits ajoutés ou modifiés, et renomme les fichiers des extraits déplacés.

```
Avengers/
  audio/AV-03-on-m-a-dit-qu-on-avait-gagne-la-guerre.wav
  video/AV-03-on-m-a-dit-qu-on-avait-gagne-la-guerre.mp4
  clips.json
```

## Installation

Il faut :

- macOS ou Windows ;
- [uv](https://docs.astral.sh/uv/) (il installe le bon Python, 3.11 ou 3.12) ;
- [ffmpeg](https://ffmpeg.org/) dans le `PATH` : `brew install ffmpeg` sur macOS, `winget install ffmpeg` sur Windows.

```bash
uv tool install git+https://github.com/IvesPower/podcleaner-clips
pclips --version
```

Cela installe deux noms pour la même commande, utilisables depuis n'importe quel dossier : `podcleaner-clips` et sa forme courte `pclips`. Si la commande est introuvable, lancez `uv tool update-shell` et ouvrez un nouveau terminal (il ajoute le dossier des outils de uv, `~/.local/bin`, au `PATH`). Mise à jour : `uv tool upgrade podcleaner-clips`.

| Commande | Rôle |
| --- | --- |
| `pclips init` | Crée votre fichier de configuration |
| `pclips run notes.md` | Découpe les extraits notés pour un film |
| `pclips config` | Affiche la configuration telle qu'elle est lue (`--path` : seulement l'emplacement du fichier) |
| `pclips --version` | Affiche la version |

`pclips` seul, `init` et `run` commencent par le nom de l'outil dessiné en pixels. Il n'apparaît jamais quand la sortie va dans un fichier ou un autre programme ; pour le retirer : `pclips --no-banner …` ou `PODCLEANER_CLIPS_NO_BANNER=1`.

Le premier passage qui repère des répliques télécharge le modèle Whisper (`large-v3-turbo`, plus de 1 Go). Sur un Mac Apple Silicon, il tourne avec MLX ; ailleurs, avec faster-whisper sur le processeur.

## Configuration

Chaque personne a son propre fichier de configuration. Créez-le en répondant à quelques questions :

```bash
pclips init
```

Il demande le dossier où ranger les extraits (obligatoire ; il propose de le créer), le dossier de vos films, le son de transition, le doublage préféré (VFF ou VFQ) et s'il faut utiliser Claude, en disant si Claude Code ou une clé d'API a été trouvé. Les chemins peuvent être collés ou glissés dans le terminal. Relancez `pclips init` pour changer vos réponses : les valeurs actuelles sont proposées par défaut, et le fichier n'est remplacé qu'après confirmation.

Le fichier est écrit dans `~/Library/Application Support/podcleaner-clips/config.toml` sur macOS et dans `%LOCALAPPDATA%\podcleaner-clips\config.toml` sur Windows (`--config` ou la variable `PODCLEANER_CLIPS_CONFIG` permettent d'en utiliser un autre ; `pclips config --path` affiche l'emplacement). Les autres réglages (`[adjust]`, `[audio]`…) sont dans le fichier, commentés : retirez le `#` pour en changer un. Vérifiez ce qui est lu avec `pclips config`. Hors terminal, ou avec `pclips init --no-input`, le fichier commenté est écrit sans questions.

Les fichiers écrits pour la version 0.1.0, avec les noms en français (`dossier_episodes`, `fichier:`, `abreviation:`, `extraits.json`…), sont encore lus : l'outil liste les noms à changer et remplace `extraits.json` par `clips.json` au passage suivant, sans refaire les extraits.

## Le fichier de notes

- Une ligne par extrait : `début référence fin`. Timecodes en `HH:MM:SS` ou `MM:SS` (`45:12` = 45 min 12 s) ; `6;25` et `25 min 30` sont compris aussi.
- Les timecodes peuvent être décalés d'une dizaine de secondes et la référence ne compter que quelques mots, même mal orthographiés. Séparez plusieurs fragments d'une longue scène par `…`, `...` ou ` - `.
- Lignes d'en-tête, avant le premier extrait : `# Titre`, `file: <film>` (chemin absolu, ou relatif au fichier de notes ou à `films_dir`), `abbreviation: AV` (écrite par l'outil si elle manque).
- Toute autre ligne est ignorée : on peut garder d'autres notes dans le même fichier. L'ancienne forme `- 00:12:34 > 00:12:51 | réplique` est acceptée.

## Lancer

```bash
pclips run notes.md
```

| Option | Effet |
| --- | --- |
| `--dry-run` | Trouve les coupes et les affiche, sans rien écrire |
| `--film CHEMIN` | Utilise ce film au lieu de `file:` |
| `--no-transition` | Fondus seuls, sans son de transition ni écran noir |
| `--audio-only` / `--video-only` | Seulement les WAV / seulement les MP4 |
| `--no-adjust` | Coupe exactement aux timecodes notés (sans sous-titres, Whisper ni Claude) |
| `--audio-track N` | Utilise la piste audio N (à partir de 0) si les pistes sont mal étiquetées |
| `--config CHEMIN` | Utilise un autre fichier de configuration |

Le résumé affiche, pour chaque extrait, les timecodes notés et retenus, la durée et ce qui a été fait (`new`, `changed`, `unchanged`, `renamed`). Une ligne `⚠` signale un doute : réplique introuvable (les timecodes notés sont gardés) ou trouvée mais peu sûre. Écoutez ceux-là en premier. Les fichiers des extraits retirés des notes sont listés, jamais supprimés. Le code de sortie vaut 1 si un extrait a échoué (par exemple, s'il finit après le film).

## Claude, facultatif

Aucun compte n'est nécessaire. Quand Claude est disponible, il propose l'abréviation du film et choisit les bornes de chaque extrait à partir de la transcription ; ses réponses sont contrôlées (à 15 s au plus de vos timecodes, tous les fragments inclus) et gardées dans `clips.json`. Sans Claude, ou s'il est injoignable, l'abréviation reprend les initiales du titre et la coupe se fait sur la limite de phrase la plus proche de chaque timecode noté.

L'outil joint Claude de l'une de ces deux façons, au choix avec `backend` dans `[claude]` :

- **Votre abonnement Claude** (Pro ou Max), par la ligne de commande [Claude Code](https://claude.com/claude-code) : installez-la, puis lancez une fois `claude auth login`. C'est ce qui est essayé en premier.
- **Une clé d'API** : définissez `ANTHROPIC_API_KEY` (payée à l'usage sur l'API d'Anthropic).

`backend = "auto"` (par défaut) passe par l'abonnement si Claude Code est installé et connecté, sinon par la clé d'API s'il y en a une, sinon sans Claude. `"cli"` et `"api"` imposent l'un des deux, `"off"` ne demande jamais rien à Claude. Les premières lignes de chaque passage disent qui répond.

## Contribuer

Les contributions sont les bienvenues. Lisez [CONTRIBUTING.fr.md](CONTRIBUTING.fr.md) : chaque modification passe par une pull request relue par le mainteneur, et les commits suivent [Conventional Commits](https://www.conventionalcommits.org/). Le [cahier des charges](docs/spec.fr.md) et le [plan d'implémentation](docs/superpowers/plans/2026-11-06-podcleaner-clips-v1.fr.md) expliquent les choix faits.

```bash
git clone https://github.com/IvesPower/podcleaner-clips.git
cd podcleaner-clips
uv sync                  # le projet et ses outils
uv run pclips            # la commande, depuis ce clone
uv run pytest            # tests rapides (sans Whisper ni réseau)
uv run pytest -m slow    # tests qui chargent un modèle Whisper
uv run ruff check
```

## Licence

[MIT](LICENSE)
