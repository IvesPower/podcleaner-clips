# Contribuer

**Français** · [English](CONTRIBUTING.md)

## Fonctionnement

- `main` est protégée : personne n'y pousse directement, et les force-push et la suppression sont bloqués.
- Chaque modification passe par une pull request. Une PR de contributeur n'est fusionnée qu'après l'approbation du mainteneur (voir [CODEOWNERS](.github/CODEOWNERS)).
- On travaille sur une branche nommée d'après son type : `feat/notes-parser`, `fix/track-selection`, `docs/readme`.

## Messages de commit

Les commits suivent [Conventional Commits](https://www.conventionalcommits.org/fr/), écrits **en anglais puis en français**, pour que tout le monde puisse lire l'historique :

```
<type>(<portée facultative>): <English summary> / <résumé en français>
```

Un corps facultatif contient un paragraphe en anglais, une ligne vide, puis le même paragraphe en français.

Types : `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`. Un changement incompatible ajoute `!` après le type (`feat!: …`) ou un pied de page `BREAKING CHANGE:`.

Exemples :

```
feat(notes): read timecodes with milliseconds / lire les timecodes avec millisecondes
fix(audio): keep the dialogue when downmixing a 5.1 track / garder les dialogues au downmix d'une piste 5.1
docs: translate the specification / traduire le cahier des charges
```

## Titre et description de la pull request

- Le **titre** suit le même format qu'un titre de commit : `type: English / français`.
- La **description** est écrite entièrement en anglais d'abord, puis entièrement en français, séparées par `---`.
- Chaque langue commence par un **TL;DR** : 1 à 3 phrases simples qui disent ce que change la PR et pourquoi, compréhensibles sans lire le code.

Le [modèle de PR](.github/pull_request_template.md) se remplit automatiquement à l'ouverture d'une PR.

## Documentation

La documentation existe en anglais et en français. Les fichiers anglais n'ont pas de suffixe (`README.md`), les fichiers français finissent par `.fr.md` (`README.fr.md`). Quand on modifie l'un, on met l'autre à jour dans la même PR, ou on indique dans la PR que la traduction reste à faire.

## Travailler avec Claude Code (graphify)

Le dépôt contient une configuration [graphify](https://github.com/Graphify-Labs/graphify) pour Claude Code : un graphe de connaissances du code que Claude interroge au lieu de relire les fichiers, ce qui réduit le contexte de chaque session. Le code est analysé en local avec tree-sitter ; rien n'est envoyé sur le réseau.

```bash
uv tool install graphifyy    # une fois par machine (le paquet s'écrit avec deux y)
graphify update .            # construire ou rafraîchir le graphe dans graphify-out/ (non versionné)
graphify hook install        # facultatif : reconstruire le graphe après chaque commit et changement de branche
```

Les hooks Claude Code de `.claude/settings.json` appellent `graphify` : s'il n'est pas installé, Claude Code affiche une erreur de hook non bloquante et fonctionne normalement.

## Avant d'ouvrir une PR

```bash
uv run ruff check
uv run pytest
```

Les deux doivent passer sur macOS et Windows ; la CI vérifie les deux.
