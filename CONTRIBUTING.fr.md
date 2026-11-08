# Contribuer

**Français** · [English](CONTRIBUTING.md)

## Fonctionnement

- `main` est protégée : personne n'y pousse directement, et les force-push et la suppression sont bloqués.
- Chaque modification passe par une pull request. Une PR de contributeur n'est fusionnée qu'après l'approbation du mainteneur (voir [CODEOWNERS](.github/CODEOWNERS)).
- On travaille sur une branche nommée d'après son type : `feat/notes-parser`, `fix/track-selection`, `docs/readme`.

## Messages de commit

Les commits suivent [Conventional Commits](https://www.conventionalcommits.org/fr/) :

```
<type>(<portée facultative>): <description>
```

Types : `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`. Un changement incompatible ajoute `!` après le type (`feat!: …`) ou un pied de page `BREAKING CHANGE:`.

Exemples :

```
feat(notes): lire les timecodes avec millisecondes
fix(audio): garder les dialogues au downmix d'une piste 5.1
docs: traduire le cahier des charges en anglais
```

## Documentation

La documentation existe en anglais et en français. Les fichiers anglais n'ont pas de suffixe (`README.md`), les fichiers français finissent par `.fr.md` (`README.fr.md`). Quand on modifie l'un, on met l'autre à jour dans la même PR, ou on indique dans la PR que la traduction reste à faire.

## Description de la pull request

Chaque PR commence par un **TL;DR** : 1 à 3 phrases simples qui disent ce que change la PR et pourquoi, compréhensibles sans lire le code. Le [modèle de PR](.github/pull_request_template.md) se remplit automatiquement à l'ouverture d'une PR : TL;DR, changements, vérifications, notes.

## Avant d'ouvrir une PR

```bash
uv run ruff check
uv run pytest
```

Les deux doivent passer sur macOS et Windows ; la CI vérifie les deux.
