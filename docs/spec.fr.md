# Extraits de film automatisés : Podcleaner-clips
Idée de base

**Français** · [English](spec.md)

Nov 6, 2026 · @Julien — révisé le 9 nov. 2026 d'après de vraies notes de visionnage

## Contexte et objectif

L'objectif est un outil en ligne de commande qui découpe dans un film les extraits notés pendant le visionnage et les range, prêts à être diffusés en direct pendant l'enregistrement de l'épisode. Nom de travail : podcleaner-clips.

L'outil tourne sur macOS et Windows et sera publié en open source, comme podcleaner-editor. Il reste utilisable sans compte ni clé d'API : Claude choisit l'abréviation du film et affine les coupes, mais l'outil a une solution de repli pour chaque cas.

Les notes sont prises vite, pendant le film : les timecodes sont approximatifs (une dizaine de secondes d'écart) et la réplique n'est qu'une référence de quelques mots, pas forcément exacte. L'outil doit retrouver la scène et la couper proprement malgré ça.

## Fonctionnalités

| Fonctionnalité | Ce qu'elle fait | Outils open source | Apport de Claude |
| --- | --- | --- | --- |
| Lecture des notes | Lit le fichier de notes rempli pendant le visionnage : pour chaque extrait, un timecode de début, une référence à la réplique et un timecode de fin | Expressions régulières | Aucun |
| Choix des pistes | Prend toujours une piste audio VF ; s'il y en a plusieurs (VFF, VFQ), la VFF par défaut (réglable) ; si aucune piste n'est marquée française, prend la première et le signale | ffprobe | Aucun |
| Repérage des références | Retrouve chaque référence dans la scène : d'abord dans les sous-titres français du film s'il en a, puis dans la transcription Whisper du doublage | ffmpeg (sous-titres), faster-whisper ou mlx-whisper (timestamps par mot), rapidfuzz | Choisir la bonne occurrence quand la référence est approximative ou répétée |
| Ajustement des coupes | Garde la scène notée, mais cale son début et sa fin sur des limites de phrase à ±15 s près, sans couper un mot, avec les références obligatoirement incluses | faster-whisper ou mlx-whisper | Choisir les bornes exactes de la scène pour qu'elle ait du sens |
| Abréviation du film | Donne une abréviation courte et stable au film (ex. « DDC » pour Le Dîner de cons), gardée pour tous ses extraits | Aucun | Proposer l'abréviation ; sans clé d'API, l'outil prend les initiales du titre |
| Son des extraits | Fondu d'ouverture et de fermeture, son de transition au début et à la fin, normalisation à -16 LUFS et -1 dBTP | ffmpeg | Aucun |
| Vidéo des extraits | Même découpe que l'audio, écran noir pendant le son de transition | ffmpeg | Aucun |
| Index des extraits | Écrit un fichier JSON par film avec chaque extrait, sa référence, sa durée et ses fichiers | Aucun | Aucun |

Options de la commande :

- `--film CHEMIN` : le fichier du film, si le fichier de notes ne l'indique pas.
- `--no-transition` : pas de son de transition, seulement les fondus.
- `--audio-only` : ne produit que les extraits audio.
- `--video-only` : ne produit que les extraits vidéo.
- `--no-adjust` : coupe exactement aux timecodes notés, sans sous-titres ni Whisper.
- `--dry-run` : affiche les coupes proposées et les noms de fichiers sans rien écrire.

## Fichier de notes

Un fichier texte ou Markdown par film, écrit pendant le visionnage. Une ligne par extrait, dans cet ordre : **timecode de début, référence, timecode de fin**.

```markdown
# Le Dîner de cons
fichier: Le Diner de cons (1998).mkv
abreviation: DDC

12:34 il s'appelle Juste Leblanc 12:51
47:02 une bonne tête … de vainqueur 47:20
1:02:10 tu sais pas ce que tu rates 1:02:40

La scène du téléphone est trop longue pour un extrait.
```

- **Timecodes** : `HH:MM:SS`, ou `MM:SS` sous une heure (`45:12` = 45 min 12 s). Les fautes de frappe courantes sont acceptées : `6;25` (point-virgule), `25 min 30`. Ils sont approximatifs : une dizaine de secondes d'écart est normale.
- **Référence** : quelques mots de la réplique, de mémoire, pas forcément exacts. Une scène longue peut avoir plusieurs fragments, séparés par `…`, `...` ou ` - ` ; chacun doit se trouver dans l'extrait.
- **En-tête facultatif** : `# Titre`, `fichier:` et `abreviation:`. Sans `fichier:`, le film est donné avec `--film`. Sans titre, l'outil le déduit du nom du fichier du film (`The Night Before (2015) Bluray-1080p.mkv` → `The Night Before (2015)`).
- **Autres lignes** : toute ligne qui ne commence pas et ne finit pas par un timecode est ignorée, on peut donc garder ses autres notes dans le même fichier. L'ancienne forme `- 00:12:34 > 00:12:51 | réplique` reste acceptée.

La ligne `abreviation` est facultative. Si elle manque, l'outil la fait proposer par Claude puis l'écrit dans le fichier, pour qu'elle ne change plus. Le nom de chaque extrait reprend les premiers mots de la référence : `DDC-01-il-s-appelle-juste-leblanc.wav`.

## Architecture

Le programme est une CLI Python qui fait tout le traitement en local avec ffmpeg et Whisper. Claude n'intervient que pour l'abréviation et le choix des bornes, toujours en option.

1. Lecture du fichier de notes et de la configuration.
2. Analyse du film avec ffprobe : durée, pistes audio et de sous-titres, langue de chaque piste.
3. Si le film a des sous-titres français en texte (hors sous-titres « forcés »), extraction une seule fois et recherche de chaque référence près des timecodes notés.
4. Pour chaque extrait, extraction de l'audio VF de la scène notée avec 15 s de marge de chaque côté, puis transcription avec timestamps par mot.
5. Repérage des références dans la transcription (aidé par les sous-titres), puis calage du début et de la fin sur des limites de phrase.
6. Découpe finale, fondus, ajout de la transition, normalisation, puis export audio et vidéo.
7. Écriture de l'index JSON et d'un récapitulatif dans le terminal.

Les chemins ne sont jamais écrits en dur. Un fichier de configuration par personne indique le dossier des épisodes, le son de transition et le dossier des films. Julien et Franck gardent chacun leur rangement, sur Mac comme sur Windows.

Points de vigilance :

- **Temps de calcul.** On ne transcrit que la scène notée et 15 s de chaque côté. Un film complet n'est jamais transcrit.
- **Sous-titres et doublage diffèrent.** Les sous-titres sont souvent traduits séparément du doublage : ils servent à situer la référence, mais les coupes se font sur les mots du doublage transcrits par Whisper.
- **Musique et bruitages.** Whisper se trompe plus souvent sur une scène bruyante. Si une référence n'est retrouvée ni dans les sous-titres ni dans la transcription, l'outil garde les timecodes notés (sans couper de mot) et le signale.
- **Pistes mal étiquetées.** Certains .mkv n'indiquent pas la langue de leurs pistes. L'outil affiche alors les pistes trouvées et permet d'en choisir une avec une option.
- **Reproductibilité.** Les coupes retenues et les avis de Claude sont écrits dans l'index, pour pouvoir relancer à l'identique.

## Sorties produites

Tout est rangé dans `{dossier-episodes}/{nom-film}/`, avec un sous-dossier par type :

```
Le Diner de cons/
  audio/
    DDC-01-il-s-appelle-juste-leblanc.wav
    DDC-02-une-bonne-tete-de-vainqueur.wav
  video/
    DDC-01-il-s-appelle-juste-leblanc.mp4
    DDC-02-une-bonne-tete-de-vainqueur.mp4
  extraits.json
```

- **Audio** : WAV 48 kHz, normalisé à -16 LUFS et -1 dBTP, pour que tous les extraits sortent au même volume en direct.
- **Vidéo** : MP4 H.264 avec son AAC, même découpe et même son que l'audio.
- **Index** (`extraits.json`) : pour chaque extrait, le numéro, la référence, les timecodes notés et retenus, la durée et les chemins des fichiers. C'est ce fichier que lira le futur lecteur en direct.

Une nouvelle exécution sur le même film ne réécrit que les extraits ajoutés ou modifiés dans le fichier de notes.

## Hors périmètre, décisions et questions ouvertes

La première version ne fait pas le lecteur en direct, ni les effets de transition vidéo, ni l'incrustation de sous-titres dans les extraits.

| Sujet | Décision |
| --- | --- |
| Formats d'entrée | .mkv le plus souvent, aussi .avi et .mp4 |
| Liste des extraits | Un fichier de notes par film ; une ligne par extrait : timecode de début, référence, timecode de fin |
| Format des timecodes | `HH:MM:SS` ou `MM:SS` sous une heure (`45:12`), décimales facultatives ; `;` et `25 min 30` tolérés |
| Référence | Quelques mots de la réplique, approximatifs ; plusieurs fragments séparés par `…`, `...` ou ` - ` |
| Bornes des extraits | L'extrait reprend la scène notée. Le début et la fin sont calés sur des limites de phrase à ±15 s des timecodes notés, sans couper un mot, et toutes les références sont incluses : mieux vaut un peu de marge qu'une réplique coupée. Références introuvables : timecodes notés gardés (sans couper de mot) et signalés |
| Repérage | Sous-titres français en texte s'il y en a (hors « forcés »), puis Whisper sur la scène ±15 s ; Whisper seul sinon |
| Rôle de Claude | Avec une clé, Claude choisit les bornes de chaque extrait à partir de la transcription ; sa réponse est contrôlée. Sans clé, règle simple : limite de phrase la plus proche de chaque timecode noté |
| Nommage | `{abréviation}-{numéro}-{premiers-mots-de-la-référence}.{format}` |
| Abréviation | Proposée par Claude, initiales du titre sans clé d'API, puis figée dans le fichier de notes |
| Langue | Toujours une piste VF, pour l'audio comme pour la vidéo ; VFF de préférence quand il y a aussi une VFQ (réglable) |
| Fondus | 0,7 s à l'ouverture et à la fermeture |
| Son de transition | Commence juste avant l'extrait ; le fondu d'ouverture se fait pendant sa fin, et le son du film est à 100 % quand la transition est passée. Même chose à l'envers en fin d'extrait |
| Transition vidéo | Écran noir pendant le son de transition, effets à ajouter plus tard |
| Formats de sortie | WAV 48 kHz à -16 LUFS pour l'audio, MP4 H.264 pour la vidéo |
| Chemins | Fichier de configuration par personne, aucun chemin en dur |

Aucune question ouverte à ce stade : le cadrage est complet pour démarrer.

## Outils pour développer le projet

Le projet reprend l'environnement de podcleaner-editor dans Claude Code : Superpowers, feature-dev, python-development, skill-creator, les hooks Ruff et pytest, et les MCP GitHub et Context7. Le MCP Hugging Face n'est pas utile ici. graphify fournit à Claude un graphe du code pour réduire le contexte de chaque session.

Skills à écrire pour le projet, versionnés dans `.claude/skills/` :

- **Test rapide** : découpe deux extraits d'un court fichier vidéo de test, un .mkv avec piste VF et VO, et vérifie noms, durées et niveaux.
- **Compatibilité Windows** : vérifie les chemins, la présence de ffmpeg et l'encodage des noms de fichiers accentués avant chaque version.

Un fichier `CLAUDE.md` à la racine reprend les décisions de ce document.
