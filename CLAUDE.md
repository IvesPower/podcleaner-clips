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

## Règles du dépôt

- `main` est protégée : on travaille sur une branche (`feat/…`, `fix/…`, `docs/…`, `chore/…`, `test/…`, `ci/…`) et tout arrive par une pull request, approuvée par le propriétaire (CODEOWNERS).
- Messages de commit au format Conventional Commits : `type(portée): description`.
- Chaque PR commence par une section `## TL;DR` : 1 à 3 phrases simples qui disent ce que change la PR et pourquoi, compréhensibles sans lire le code. Suivre `.github/pull_request_template.md` (TL;DR, Changements, Vérifications, Notes).
- Documentation en anglais (`*.md`) et en français (`*.fr.md`) : toute modification de l'une met l'autre à jour dans la même PR. Ce fichier-ci est en français uniquement.
- Identifiants du code en anglais ; messages affichés, clés du fichier de configuration et de l'index en français.

## Décisions du cahier des charges

| Sujet | Décision |
| --- | --- |
| Plateformes | macOS et Windows ; chemins via `pathlib`, jamais de chemin en dur ; texte en `encoding="utf-8"` |
| Sans compte | Aucune clé d'API requise : chaque appel à Claude a un repli |
| Formats d'entrée | .mkv le plus souvent, aussi .avi et .mp4 |
| Liste des extraits | Un fichier .md de notes par film ; une ligne par extrait `- HH:MM:SS > HH:MM:SS \| réplique` ; les autres lignes sont ignorées |
| Bornes des extraits | Timecodes notés, ajustés par Whisper autour de la réplique, jusqu'à 4 s de chaque côté, sans couper un mot : mieux vaut un peu de marge qu'une réplique coupée |
| Langue | Toujours la piste VF, pour l'audio comme pour la vidéo ; sans piste marquée française, la première, avec un avertissement |
| Abréviation | Proposée par Claude, initiales du titre sans clé d'API, puis figée dans le fichier de notes |
| Nommage | `{abréviation}-{numéro}-{premiers-mots-de-la-réplique}.{format}` |
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
| Dossier du film | Titre du `# ` des notes sans accents ni `<>:"/\|?*` |
| Slug | Minuscules, sans accents, mots entiers jusqu'à 40 caractères ; vide → `extrait` |
| Abréviation de repli | Sans l'article initial, initiales en majuscules, 2 à 6 caractères |
| Image pendant la transition | Noire tant que le son du film n'a pas commencé, pour rester synchrone |
| Canaux | Sortie stéréo (une VF 5.1 est réduite en stéréo) ; WAV 24 bits |
| Doute | Score < 50 : timecodes notés gardés ; 50–80 ou deux occurrences proches : avis de Claude, sinon occurrence la plus proche, signalée |
| Modèles | Whisper `large-v3-turbo` en `fr` ; Claude `claude-haiku-5-5` ; réglables |
| Extraits retirés | Fichiers non supprimés, listés comme orphelins |

## Points de vigilance

- **Temps de calcul** : on ne transcrit que la fenêtre autour de chaque extrait, jamais le film entier.
- **Musique et bruitages** : si la réplique n'est pas retrouvée, on garde les timecodes notés et on le signale.
- **Pistes mal étiquetées** : afficher les pistes trouvées et permettre d'en choisir une (`--audio-track N`).
- **Reproductibilité** : les coupes retenues et les avis de Claude sont écrits dans l'index.
- **Tests** : les tests rapides n'utilisent ni modèle Whisper ni réseau (ffmpeg est permis) ; les films de test sont générés dans `tmp_path`, jamais versionnés.
