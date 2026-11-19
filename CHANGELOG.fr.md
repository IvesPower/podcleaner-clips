# Journal des modifications

**Français** · [English](CHANGELOG.md)

Les changements notables de podcleaner-clips. Les versions suivent la [gestion sémantique de version](https://semver.org/lang/fr/).

## [1.0.0] - pas encore publiée

Première version publique. podcleaner-clips découpe dans un film les extraits notés pendant le visionnage (timecode de début, quelques mots de la réplique, timecode de fin) et les range en WAV et en MP4, prêts à être diffusés en direct pendant l'enregistrement d'un épisode.

### Points forts

- **Des notes prises comme elles viennent.** Une ligne par extrait, par exemple `42:30 vas-y, je t'attends, tête de bouclier 42:40`. `HH:MM:SS` et `MM:SS` sont acceptés, tout comme `6;25` et `25 min 30`. Une ligne peut contenir plusieurs fragments, séparés par `…`, `...` ou ` - `. L'outil ignore les autres lignes.
- **Toujours la VF.** L'outil choisit la piste VF, la VFF plutôt que la VFQ quand le film a les deux (réglable), et prévient quand aucune piste n'est marquée française. `--audio-track N` force une piste mal étiquetée.
- **Des coupes jamais au milieu d'une réplique.** L'outil retrouve chaque réplique dans les sous-titres français, puis dans le doublage avec Whisper (`large-v3-turbo`, seulement autour de chaque extrait, jamais le film entier). Chaque coupe tombe sur une limite de phrase, entre deux mots.
- **Claude centre l'extrait sur la réplique.** Vos timecodes sont lus comme une zone approximative et la réplique notée comme le moment qui compte. Claude garde juste le contexte nécessaire pour comprendre la blague et la réaction qui suit, et sa réponse est contrôlée. Il est joint par votre abonnement Claude (CLI Claude Code) ou par une clé d'API ; le modèle par défaut est `claude-sonnet-5-5`. Sans Claude, la coupe se fait sur la limite de phrase la plus proche de chaque timecode.
- **Prêt pour le direct.** Chaque extrait a des fondus de 0,7 s, avec votre son de transition avant et après. Après le dernier mot, la réplique a 0,5 s de pause avant que le fondu de fermeture et la transition commencent (`pad_after_s`). Le son du film est à -16 LUFS, le son de transition à -19 LUFS (`lufs` / `transition_lufs`, ou `--lufs` / `--transition-lufs`), jamais au-dessus de -1 dBTP. L'outil écrit un WAV 48 kHz 24 bits stéréo et un MP4 H.264 + AAC. Dans le MP4, la transition passe sur un écran noir ou sur votre propre vidéo de transition, et l'image apparaît depuis le noir et y retourne en même temps que le son.
- **Relances rapides.** Seuls les extraits ajoutés ou modifiés sont refaits. Les fichiers des extraits qui changent de place sont renommés ; ceux des extraits retirés sont listés, jamais supprimés. Une nouvelle vidéo de transition ne refait que les MP4. Les coupes et les avis de Claude sont gardés dans `clips.json`.
- **Installation simple.** Installation avec `uv tool install git+https://github.com/IvesPower/podcleaner-clips`. Commandes : `podcleaner-clips` ou `pclips`, puis `init`, `run`, `config`, `version`. `pclips init` pose quelques questions et écrit un fichier de configuration commenté.
- **macOS et Windows.** Chemins gérés avec `pathlib`, texte en UTF-8, CI sur les deux systèmes.

### Changements pour qui utilisait la version de développement 0.1.0

- La configuration, l'en-tête des notes et l'index utilisent maintenant des clés en anglais (`episodes_dir`, `file:`, `clips.json`…). Les anciens noms français (`dossier_episodes`, `fichier:`, `extraits.json`…) restent lus, avec un avis qui demande de les renommer.
- Le son de transition n'est plus mixé au niveau de l'extrait. Il a maintenant son propre volume (`transition_lufs`, -19 LUFS par défaut) : la prochaine relance refait chaque extrait une fois.
- Le fondu de fermeture ne commence plus sur le dernier mot : une pause (`pad_after_s`, maintenant 0,5 s) vient d'abord, puis le fondu. Quand la réplique suivante arrive plus tôt, le son du film s'arrête juste avant elle avec un fondu plus court en S, l'image continue et descend au noir jusqu'à la transition, et la transition attend quand même la fin de la pause.
- Le modèle Claude par défaut est maintenant `claude-sonnet-5-5` au lieu de `claude-haiku-5-5`, et ses coupes peuvent être plus serrées que vos timecodes.

### Prérequis

- macOS ou Windows, [uv](https://docs.astral.sh/uv/) (Python 3.11 ou 3.12), [ffmpeg](https://ffmpeg.org/) dans le `PATH`.
- Facultatif : un abonnement Claude avec [Claude Code](https://claude.com/claude-code), ou une `ANTHROPIC_API_KEY`.

### Pas dans cette version

- Pas de lecteur en direct.
- Pas d'effet de transition vidéo autre que le fondu au noir et la vidéo de transition.
- Pas de sous-titres dans les extraits.

[1.0.0]: https://github.com/IvesPower/podcleaner-clips/releases/tag/v1.0.0
