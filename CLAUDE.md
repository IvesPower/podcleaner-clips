# podcleaner-clips

CLI Python qui découpe dans un film les extraits notés pendant le visionnage et les range, prêts à être diffusés en direct pendant l'enregistrement d'un épisode.

- Cahier des charges : `docs/spec.fr.md` (original, fait foi) · `docs/spec.md` (anglais)
- Plan d'implémentation : `docs/superpowers/plans/2026-11-06-podcleaner-clips-v1.fr.md` (et `.md` en anglais)

## Commandes

```bash
uv sync                    # installer
uv run pytest              # tests rapides (sans Whisper ni réseau)
uv run pytest -m slow      # tests qui chargent un modèle Whisper
uv run ruff check          # lint
uv run ruff format         # formatage
uv run podcleaner-clips    # la CLI
```

Le hook `.claude/hooks/python_checks.py` lance Ruff et les tests rapides après chaque modification d'un `.py`.

Skills du projet : `test-rapide` (test de bout en bout sur un film généré, avant une PR qui touche le pipeline ou le rendu) et `compat-windows` (avant chaque version).

## Règles du dépôt

- `main` est protégée : on travaille sur une branche (`feat/…`, `fix/…`, `docs/…`, `chore/…`, `test/…`, `ci/…`) et tout arrive par une pull request, approuvée par le propriétaire (CODEOWNERS).
- Messages de commit au format Conventional Commits, **en anglais puis en français** :
  - titre : `type(portée): English summary / résumé en français` (ex. `feat(notes): read the notes file / lecture du fichier de notes`) ;
  - corps facultatif : un paragraphe en anglais, une ligne vide, le même en français.
- Titre de PR : même format que le titre de commit (`type: English / français`).
- Description de PR : **tout en anglais d'abord, puis tout en français**, séparés par `---`. Chaque version commence par son `## TL;DR` : 1 à 3 phrases simples qui disent ce que change la PR et pourquoi, compréhensibles sans lire le code. Suivre `.github/pull_request_template.md`.
- Documentation en anglais (`*.md`) et en français (`*.fr.md`) : toute modification de l'une met l'autre à jour dans la même PR. Ce fichier-ci est en français uniquement.
- Code et sorties en anglais : identifiants, commentaires, docstrings, messages affichés, erreurs, aide de la CLI. Restent en français : les clés du fichier de configuration et de l'index.

## Décisions du cahier des charges

| Sujet | Décision |
| --- | --- |
| Plateformes | macOS et Windows ; chemins via `pathlib`, jamais de chemin en dur ; texte en `encoding="utf-8"` |
| Sans compte | Aucune clé d'API requise : chaque appel à Claude a un repli |
| Formats d'entrée | .mkv le plus souvent, aussi .avi et .mp4 |
| Liste des extraits | Un fichier de notes par film ; une ligne par extrait : `TC référence TC` (ex. `27:15 ce bébé c'est une connerie 27:37`) ; `HH:MM:SS` ou `MM:SS`, `6;25` et `25 min 30` tolérés ; ancienne forme `- TC > TC \| réplique` acceptée ; les autres lignes sont ignorées |
| Bornes des extraits | Timecodes approximatifs (~10 s) et référence partielle (quelques mots, plusieurs fragments possibles séparés par `…`, `...` ou ` - `). L'extrait reprend la scène notée : début et fin calés sur des limites de phrase à ±15 s des timecodes notés, sans couper un mot, toutes les références trouvées incluses |
| Langue | Toujours une piste VF, VFF de préférence quand il y a aussi une VFQ (réglable) ; sans piste marquée française, la première, avec un avertissement |
| Repérage | Sous-titres français en texte s'il y en a (hors « forcés »), puis Whisper ; coupes toujours sur les mots du doublage transcrits par Whisper |
| Abréviation | Proposée par Claude, initiales du titre sans clé d'API, puis figée dans le fichier de notes |
| Nommage | `{abréviation}-{numéro}-{premiers-mots-de-la-référence}.{format}` |
| Fondus | 0,7 s à l'ouverture et à la fermeture |
| Son de transition | Commence juste avant l'extrait ; le fondu d'ouverture se fait pendant sa fin ; même chose à l'envers en fin d'extrait |
| Transition vidéo | Écran noir pendant le son de transition |
| Sorties | `{dossier_episodes}/{nom-film}/audio/` (WAV 48 kHz, -16 LUFS, -1 dBTP), `…/video/` (MP4 H.264 + AAC), `…/extraits.json` |
| Relance | Ne réécrit que les extraits ajoutés ou modifiés |
| Chemins | Fichier de configuration par personne, aucun chemin en dur |
| Hors périmètre v1 | Lecteur en direct, effets de transition vidéo, sous-titres |

## Décisions prises par le plan

| Sujet | Décision |
| --- | --- |
| Paquet / commande | `podcleaner_clips` / `podcleaner-clips` (`run`, `config init`, `config show`, `version`) |
| Configuration | TOML dans `platformdirs.user_config_dir("podcleaner-clips")/config.toml`, remplaçable par `--config` ou `PODCLEANER_CLIPS_CONFIG` |
| Titre et dossier du film | Titre : `# ` des notes, sinon nom du fichier du film jusqu'à l'année (`The Night Before (2015)`) ; dossier : titre sans accents ni `<>:"/\|?*`, ≤ 60 caractères. Film : `--film` ou `fichier:` |
| Slug | Minuscules, sans accents, mots entiers jusqu'à 40 caractères ; vide → `extrait` |
| Abréviation de repli | Sans l'article initial, initiales en majuscules, 2 à 6 caractères |
| Image pendant la transition | Noire tant que le son du film n'a pas commencé, pour rester synchrone |
| Canaux | Sortie stéréo (une VF 5.1 est réduite en stéréo) ; WAV 24 bits |
| Doute | Fragment introuvable (score < 70) ou peu sûr (< 85) : signalé ; aucun fragment trouvé : timecodes notés gardés (calés sur des mots), signalés |
| Rôle de Claude | Avec une clé, Claude choisit les bornes de chaque extrait à partir de la transcription ; réponse contrôlée (bornes à ±15 s des notes, fragments inclus) ; sans clé, limite de phrase la plus proche de chaque timecode noté |
| Modèles | Whisper `large-v3-turbo` en `fr` ; Claude `claude-haiku-5-5` ; réglables |
| Extraits retirés | Fichiers non supprimés, listés comme orphelins |

## Points de vigilance

- **Temps de calcul** : on ne transcrit que la fenêtre autour de chaque extrait, jamais le film entier.
- **Musique et bruitages** : si la réplique n'est pas retrouvée, on garde les timecodes notés et on le signale.
- **Pistes mal étiquetées** : afficher les pistes trouvées et permettre d'en choisir une (`--audio-track N`).
- **Reproductibilité** : les coupes retenues et les avis de Claude sont écrits dans l'index.
- **Tests** : les tests rapides n'utilisent ni modèle Whisper ni réseau (ffmpeg est permis) ; les films de test sont générés dans `tmp_path`, jamais versionnés.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
