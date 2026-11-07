# podcleaner-clips

**Français** · [English](README.md)

Un outil en ligne de commande qui découpe dans un film les extraits notés pendant le visionnage et les range, prêts à être diffusés en direct pendant l'enregistrement d'un épisode de podcast.

> **État : en développement.** Le cadrage est fixé, le code n'est pas encore écrit. Voir le [cahier des charges](docs/spec.fr.md) et le [plan d'implémentation](docs/superpowers/plans/2026-11-06-podcleaner-clips-v1.fr.md).

## Ce que fait l'outil

Pendant le visionnage, on écrit un fichier Markdown par film, avec les timecodes et la réplique de chaque extrait :

```markdown
# Le Dîner de cons
fichier: Le Diner de cons (1998).mkv
abreviation: DDC

## Extraits
- 00:12:34 > 00:12:51 | Il s'appelle Juste Leblanc
- 00:47:02 > 00:47:20 | Il a une bonne tête de vainqueur
```

Puis `podcleaner-clips run notes.md` :

- prend toujours la piste audio VF et prévient si aucune piste n'est marquée française ;
- transcrit quelques secondes autour de chaque extrait avec Whisper, retrouve la réplique et cale le début et la fin sur les limites de phrase (jusqu'à 4 s), sans jamais couper un mot ;
- ajoute des fondus de 0,7 s et un son de transition, puis normalise à -16 LUFS / -1 dBTP ;
- écrit un WAV 48 kHz, un MP4 H.264 (écran noir pendant la transition) et un index `extraits.json` ;
- aux exécutions suivantes, ne refait que les extraits ajoutés ou modifiés.

```
Le Diner de cons/
  audio/DDC-01-il-s-appelle-juste-leblanc.wav
  video/DDC-01-il-s-appelle-juste-leblanc.mp4
  extraits.json
```

Les lignes qui ne suivent pas le format d'un extrait sont ignorées : on peut garder ses autres notes dans le même fichier.

### Options

| Option | Effet |
| --- | --- |
| `--no-transition` | Fondus seulement, pas de son de transition |
| `--audio-only` | Extraits audio seulement |
| `--video-only` | Extraits vidéo seulement |
| `--no-adjust` | Coupe exactement aux timecodes notés, sans Whisper |
| `--dry-run` | Affiche les coupes proposées et les noms de fichiers sans rien écrire |
| `--audio-track N` | Impose une piste audio quand les pistes ne sont pas étiquetées |

## Sans compte

Tout le traitement se fait en local avec ffmpeg et Whisper. Si une `ANTHROPIC_API_KEY` est définie, Claude propose l'abréviation du film et tranche les coupes douteuses. Sans clé, l'outil prend les initiales du titre et la coupe la plus large.

## Prérequis

- macOS ou Windows
- Python 3.11 ou 3.12 et [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/) dans le `PATH` (`brew install ffmpeg` / `winget install ffmpeg`)

Les instructions d'installation arriveront avec la première version.

## Contribuer

Les contributions sont les bienvenues. Lire [CONTRIBUTING.fr.md](CONTRIBUTING.fr.md) : chaque modification passe par une pull request relue par le mainteneur, et les commits suivent [Conventional Commits](https://www.conventionalcommits.org/fr/).

## Licence

[MIT](LICENSE)
