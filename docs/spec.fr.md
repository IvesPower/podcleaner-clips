# Extraits de film automatisés : Podcleaner-clips
Idée de base

**Français** · [English](spec.md)

Nov 6, 2026 · @Julien

## Contexte et objectif

L'objectif est un outil en ligne de commande qui découpe dans un film les extraits notés pendant le visionnage et les range, prêts à être diffusés en direct pendant l'enregistrement de l'épisode. Nom de travail : podcleaner-clips.

L'outil tourne sur macOS et Windows et sera publié en open source, comme podcleaner-editor. Il reste utilisable sans compte ni clé d'API : Claude choisit l'abréviation du film et affine les coupes, mais l'outil a une solution de repli pour chaque cas.

## Fonctionnalités

| Fonctionnalité | Ce qu'elle fait | Outils open source | Apport de Claude |
| --- | --- | --- | --- |
| Lecture des notes | Lit le fichier .md rempli pendant le visionnage : timecodes de début et de fin, réplique de chaque extrait | Parseur Markdown | Aucun |
| Choix des pistes | Prend toujours la piste audio VF ; si aucune piste n'est marquée française, prend la première et le signale | ffprobe | Aucun |
| Ajustement des coupes | Transcrit une marge autour de chaque extrait, retrouve la réplique et cale le début et la fin sur les limites de phrase, sans couper un mot | faster-whisper ou mlx-whisper (timestamps par mot), rapidfuzz | Choisir la coupe quand la réplique est mal transcrite ou quand plusieurs fins sont possibles |
| Abréviation du film | Donne une abréviation courte et stable au film (ex. « DDC » pour Le Dîner de cons), gardée pour tous ses extraits | Aucun | Proposer l'abréviation ; sans clé d'API, l'outil prend les initiales du titre |
| Son des extraits | Fondu d'ouverture et de fermeture, son de transition au début et à la fin, normalisation à -16 LUFS et -1 dBTP | ffmpeg | Aucun |
| Vidéo des extraits | Même découpe que l'audio, écran noir pendant le son de transition | ffmpeg | Aucun |
| Index des extraits | Écrit un fichier JSON par film avec chaque extrait, sa réplique, sa durée et ses fichiers | Aucun | Aucun |

Options de la commande :

- `--no-transition` : pas de son de transition, seulement les fondus.
- `--audio-only` : ne produit que les extraits audio.
- `--video-only` : ne produit que les extraits vidéo.
- `--no-adjust` : coupe exactement aux timecodes notés, sans passer par Whisper.
- `--dry-run` : affiche les coupes proposées et les noms de fichiers sans rien écrire.

## Fichier de notes

Un fichier .md par film, écrit pendant le visionnage. Une ligne par extrait : timecode de début, timecode de fin, réplique. Les lignes qui ne suivent pas ce format sont ignorées, on peut donc garder ses autres notes dans le même fichier.

```markdown
# Le Dîner de cons
fichier: Le Diner de cons (1998).mkv
abreviation: DDC

## Extraits
- 00:12:34 > 00:12:51 | Il s'appelle Juste Leblanc
- 00:47:02 > 00:47:20 | Il a une bonne tête de vainqueur

## Notes libres
La scène du téléphone est trop longue pour un extrait.
```

La ligne `abreviation` est facultative. Si elle manque, l'outil la fait proposer par Claude puis l'écrit dans le fichier, pour qu'elle ne change plus. Le nom de chaque extrait reprend les premiers mots de la réplique : `DDC-01-il-s-appelle-juste-leblanc.wav`.

## Architecture

Le programme est une CLI Python qui fait tout le traitement en local avec ffmpeg et Whisper. Claude n'intervient que pour l'abréviation et les coupes douteuses, toujours en option.

1. Lecture du fichier de notes et de la configuration.
2. Analyse du film avec ffprobe : durée, pistes audio, langue de chaque piste.
3. Pour chaque extrait, extraction de l'audio VF avec une marge de quelques secondes de chaque côté.
4. Transcription de cette fenêtre avec timestamps par mot, recherche de la réplique, calage du début et de la fin.
5. Découpe finale, fondus, ajout de la transition, normalisation, puis export audio et vidéo.
6. Écriture de l'index JSON et d'un récapitulatif dans le terminal.

Les chemins ne sont jamais écrits en dur. Un fichier de configuration par personne indique le dossier des épisodes, le son de transition et le dossier des films. Julien et Franck gardent chacun leur rangement, sur Mac comme sur Windows.

Points de vigilance :

- **Temps de calcul.** On ne transcrit que la fenêtre autour de chaque extrait, quelques dizaines de secondes à chaque fois. Un film complet n'est jamais transcrit.
- **Musique et bruitages.** Whisper se trompe plus souvent sur une scène bruyante. Si la réplique n'est pas retrouvée, l'outil garde les timecodes notés et le signale.
- **Pistes mal étiquetées.** Certains .mkv n'indiquent pas la langue de leurs pistes. L'outil affiche alors les pistes trouvées et permet d'en choisir une avec une option.
- **Reproductibilité.** Les coupes retenues et les avis de Claude sont écrits dans l'index, pour pouvoir relancer à l'identique.

## Sorties produites

Tout est rangé dans `{dossier-episodes}/{nom-film}/`, avec un sous-dossier par type :

```
Le Diner de cons/
  audio/
    DDC-01-il-s-appelle-juste-leblanc.wav
    DDC-02-il-a-une-bonne-tete-de-vainqueur.wav
  video/
    DDC-01-il-s-appelle-juste-leblanc.mp4
    DDC-02-il-a-une-bonne-tete-de-vainqueur.mp4
  extraits.json
```

- **Audio** : WAV 48 kHz, normalisé à -16 LUFS et -1 dBTP, pour que tous les extraits sortent au même volume en direct.
- **Vidéo** : MP4 H.264 avec son AAC, même découpe et même son que l'audio.
- **Index** (`extraits.json`) : pour chaque extrait, le numéro, la réplique, les timecodes notés et retenus, la durée et les chemins des fichiers. C'est ce fichier que lira le futur lecteur en direct.

Une nouvelle exécution sur le même film ne réécrit que les extraits ajoutés ou modifiés dans le fichier de notes.

## Hors périmètre, décisions et questions ouvertes

La première version ne fait pas le lecteur en direct, ni les effets de transition vidéo, ni les sous-titres.

| Sujet | Décision |
| --- | --- |
| Formats d'entrée | .mkv le plus souvent, aussi .avi et .mp4 |
| Bornes des extraits | Timecodes de début et de fin notés, ajustés par Whisper autour de la réplique, jusqu'à 4 s de chaque côté : mieux vaut un peu de marge qu'une réplique coupée |
| Liste des extraits | Un fichier .md de notes par film |
| Nommage | `{abréviation}-{numéro}-{premiers-mots-de-la-réplique}.{format}` |
| Abréviation | Proposée par Claude, initiales du titre sans clé d'API, puis figée dans le fichier de notes |
| Langue | Toujours la piste VF, pour l'audio comme pour la vidéo |
| Fondus | 0,7 s à l'ouverture et à la fermeture |
| Son de transition | Commence juste avant l'extrait ; le fondu d'ouverture se fait pendant sa fin, et le son du film est à 100 % quand la transition est passée. Même chose à l'envers en fin d'extrait |
| Transition vidéo | Écran noir pendant le son de transition, effets à ajouter plus tard |
| Formats de sortie | WAV 48 kHz à -16 LUFS pour l'audio, MP4 H.264 pour la vidéo |
| Chemins | Fichier de configuration par personne, aucun chemin en dur |

Aucune question ouverte à ce stade : le cadrage est complet pour démarrer.

## Outils pour développer le projet

Le projet reprend l'environnement de podcleaner-editor dans Claude Code : Superpowers, feature-dev, python-development, skill-creator, les hooks Ruff et pytest, et les MCP GitHub et Context7. Le MCP Hugging Face n'est pas utile ici.

Skills à écrire pour le projet, versionnés dans `.claude/skills/` :

- **Test rapide** : découpe deux extraits d'un court fichier vidéo de test, un .mkv avec piste VF et VO, et vérifie noms, durées et niveaux.
- **Compatibilité Windows** : vérifie les chemins, la présence de ffmpeg et l'encodage des noms de fichiers accentués avant chaque version.

Un fichier `CLAUDE.md` à la racine reprend les décisions de ce document.
