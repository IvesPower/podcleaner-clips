# Podcleaner-clips v1 : plan d'implémentation

**Français** · [English](2026-11-06-podcleaner-clips-v1.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une CLI `podcleaner-clips run notes.md` qui lit le fichier de notes d'un film (timecodes approximatifs et références partielles), retrouve chaque scène notée grâce aux sous-titres et à Whisper, cale ses bornes sur des limites de phrase, puis écrit les extraits audio (WAV) et vidéo (MP4) avec fondus, son de transition et normalisation, plus l'index `extraits.json`.

**Architecture :** paquet Python `src/podcleaner_clips/`. ffmpeg/ffprobe, Whisper et Claude restent en bordure, derrière des fonctions étroites ; tout ce qui décide (lecture des notes, choix de piste, repérage des références, calage des coupes, gabarit temporel des extraits, empreintes) est fait de fonctions pures testables sans média. Un extrait est rendu une seule fois en WAV normalisé ; le MP4 réutilise ce WAV comme bande son.

**Tech Stack :** Python 3.11–3.12, uv, Typer, platformdirs, rapidfuzz, numpy, mlx-whisper (macOS arm64) / faster-whisper (ailleurs), anthropic, ffmpeg/ffprobe (PATH), pytest, Ruff.

**Spec :** `docs/spec.fr.md` (original) · `docs/spec.md` (traduction anglaise). Projet frère pour les conventions : `../podcleaner-editor/docs/superpowers/plans/2026-11-05-m1-fondations-analyse.md`.

## Global Constraints

- Tourne sur macOS et Windows ; chemins via `pathlib`, aucun chemin en dur, fichiers texte lus et écrits en `encoding="utf-8"`.
- Aucun compte ni clé d'API requis : sans `ANTHROPIC_API_KEY`, chaque appel à Claude a un repli (initiales du titre, règle simple pour les bornes).
- Entrées : `.mkv`, `.avi`, `.mp4`.
- Toujours une piste audio VF, VFF de préférence quand il y a aussi une VFQ (réglable) ; si aucune piste n'est marquée française, la première, avec un avertissement.
- Notes réelles : une ligne d'extrait = timecode de début, référence, timecode de fin. Timecodes approximatifs (~10 s d'écart) ; référence = quelques mots, pas forcément exacts, éventuellement plusieurs fragments.
- L'extrait reprend la scène notée : début et fin calés sur des limites de phrase à ±15 s des timecodes notés, jamais au milieu d'un mot, toutes les références trouvées incluses ; mieux vaut de la marge qu'une réplique coupée.
- Repérage : sous-titres français en texte s'il y en a (hors « forcés »), puis Whisper ; les coupes se font toujours sur les mots du doublage transcrits par Whisper.
- Timecodes acceptés : `HH:MM:SS` ou `MM:SS` (`45:12` = 45 min 12 s), décimales facultatives ; `6;25` et `25 min 30` tolérés.
- Un film complet n'est jamais transcrit : seulement la scène notée ±15 s.
- Fondus : 0,7 s à l'ouverture et à la fermeture.
- Audio : WAV 48 kHz, -16 LUFS intégré, -1 dBTP.
- Vidéo : MP4 H.264 + AAC, même découpe et même son que l'audio ; écran noir pendant le son de transition.
- Nommage : `{abréviation}-{numéro sur 2 chiffres}-{premiers-mots-de-la-référence}.{wav|mp4}`.
- Sortie : `{dossier_episodes}/{nom-film}/audio/`, `…/video/`, `…/extraits.json`.
- Une nouvelle exécution ne réécrit que les extraits ajoutés ou modifiés.
- Hors périmètre v1 : lecteur en direct, effets de transition vidéo, incrustation de sous-titres.
- Code et sorties en anglais : identifiants, commentaires, docstrings, messages affichés, erreurs, aide de la CLI ; les messages cités en français dans les tâches ci-dessous sont à écrire en anglais. Restent en français : les clés du fichier de configuration et de l'index.
- Tests rapides (`pytest -m "not slow"`) sans modèle Whisper ni réseau ; ils peuvent appeler ffmpeg. Les tests qui chargent Whisper sont marqués `slow`.
- `main` est protégée : chaque tâche se fait sur une branche (`feat/…`, `fix/…`, `docs/…`, `chore/…`) et arrive par une pull request. Commits au format Conventional Commits, titre en anglais puis en français (`type: English / français`) ; les messages de commit indiqués dans les tâches ci-dessous ne donnent que la partie française, à compléter. Titre et description de PR : anglais puis français (voir `CONTRIBUTING.fr.md`).
- Documentation en anglais (`*.md`) et en français (`*.fr.md`) : toute modification de l'une met l'autre à jour dans la même PR. `CLAUDE.md` est en français.

## Décisions prises par ce plan (la spec ne les fixe pas)

| Sujet | Décision |
| --- | --- |
| Paquet / commande | `podcleaner_clips` / `podcleaner-clips` (`run`, `config init`, `config show`, `version`) |
| Configuration | TOML dans `platformdirs.user_config_dir("podcleaner-clips")/config.toml`, remplaçable par `--config` ou `PODCLEANER_CLIPS_CONFIG` |
| Titre du film | `# ` du fichier de notes ; sinon nom du fichier du film jusqu'à l'année entre parenthèses incluse (`The Night Before (2015) Bluray-1080p.mkv` → `The Night Before (2015)`), sinon son nom sans extension |
| Dossier du film | Titre sans accents ni `<>:"/\|?*`, au plus 60 caractères (`Le Dîner de cons` → `Le Diner de cons`), pour éviter les soucis NFC/NFD entre Mac et Windows |
| Slug | Tiré de la référence : minuscules, sans accents, apostrophes et ponctuation → `-`, mots entiers jusqu'à 40 caractères ; vide → `extrait` |
| Abréviation de repli | On retire l'article initial (le, la, les, l', un, une, des, the, a, an), initiales des mots restants en majuscules, 2 à 6 caractères (`Le Dîner de cons` → `DDC`) |
| Numéro | Ordre de la ligne dans le fichier de notes, à partir de 1 |
| Fragments | La référence est découpée sur `…`, `...` et ` - ` ; fragments de moins de 2 mots ignorés pour la recherche |
| Recherche floue | Par fragment, après normalisation (minuscules, sans accents ni ponctuation) : on compare le fragment à une fenêtre de texte **au moins aussi longue que lui** (mots consécutifs de la transcription, ou sous-titres consécutifs concaténés) avec `rapidfuzz.fuzz.partial_ratio` ; trouvé si score ≥ 70, sûr si ≥ 85. Sans cette condition de longueur, un sous-titre court (« Désolé ! ») obtenait 85 contre une longue référence. Mesuré sur le film d'essai : 5 fragments sur 10 retrouvés dans les sous-titres, sans faux positif ; les autres diffèrent trop du doublage et reposent sur Whisper |
| Sous-titres | Piste de sous-titres en texte (`subrip`, `ass`, `ssa`, `mov_text`, `webvtt`) en français, hors titres contenant « forcé » / « forced » ; « complet » / « full » / « SDH » de préférence. Extraite une fois par exécution au format SRT. Un sous-titre trouvé fixe une ancre : on cherche ensuite le fragment dans la transcription à ±5 s de cette ancre |
| Choix des bornes sans Claude | Début : début de phrase le plus proche de `noted_start` dans `[noted_start − 15, premier fragment]` ; fin : fin de phrase la plus proche de `noted_end` dans `[dernier fragment, noted_end + 15]`. Début de phrase = premier mot, mot suivant `.`, `!`, `?`, `…`, ou suivant une pause ≥ 0,6 s. Aucune limite de phrase : limite de mot la plus proche, signalée |
| Rôle de Claude sur les coupes | Avec une clé et l'ajustement actif, Claude choisit les bornes de **chaque** extrait (mots de début et de fin) à partir de la transcription, des fragments trouvés et de la proposition heuristique. Réponse contrôlée : début dans `noted_start ± 15`, fin dans `noted_end ± 15`, tous les fragments trouvés inclus ; sinon la proposition heuristique est gardée |
| Doute | Fragment introuvable (score < 70) ou trouvé mais pas sûr (< 85), ou deux occurrences à moins de 5 points : signalé dans le récapitulatif et l'index. Aucun fragment trouvé : timecodes notés, élargis à des limites de mots |
| Doublage | `doublage_prefere = "VFF"` (ou `"VFQ"`). VFQ reconnue si le titre de piste contient `VFQ`, `Québec`, `Quebec` ou `Canad`, ou si la langue est `fr-CA` ; VFF si `VFF`, `France` ou `VF` seul |
| Canaux | Sortie stéréo ; une VF 5.1 est réduite en stéréo par le downmix ffmpeg avec la voix centrale conservée |
| Position de la transition | Le son du film commence `transition − 0,7 s` après le début, monte en 0,7 s ; la transition de fin démarre au début du fondu de fermeture. Même fichier son pour l'entrée et la sortie |
| Image pendant la transition | Noir tant que le son du film n'a pas commencé (et après qu'il s'arrête), pour que l'image reste synchrone avec le son |
| Profondeur WAV | 24 bits |
| Modèles | Whisper `large-v3-turbo` (mlx : `mlx-community/whisper-large-v3-turbo`), langue `fr` ; Claude `claude-haiku-5-5` ; les deux réglables dans la configuration |
| Extraits retirés des notes | Leurs fichiers ne sont pas supprimés, seulement listés comme « orphelins » dans le récapitulatif |

## Review Focus

1. **Fichier de notes réel** (d'après de vraies notes) : lignes `TC référence TC` sans puce, `6;25`, `25 min 30 :`, `1:17;08`, BOM UTF-8, fins de ligne Windows, aucun en-tête, début ≥ fin. Les lignes conformes doivent être lues ; une ligne avec début ≥ fin est une erreur signalée pour cet extrait sans arrêter les autres. Tests dans la tâche 3.
2. **Référence approximative et timing décalé** : référence de 3 mots mal orthographiée, timecodes décalés de 10 s, deux fragments séparés par `…` sur une scène d'une minute. La scène doit être retrouvée et contenir tous les fragments. Tests dans la tâche 6.
3. **VF en 5.1 avec VFF et VFQ** (cas du film d'essai) : la VFF est choisie, l'extrait sort en stéréo, voix audible, au bon niveau. Tests dans les tâches 5 et 8.
4. **Vidéo anamorphique, 23,976 i/s, HEVC 10 bits, pochette `mjpeg` en piste vidéo** : le noir et l'image du film se concatènent sans erreur ffmpeg et sortent en yuv420p ; la pochette est ignorée. Tests dans les tâches 5 et 9.
5. **Relance après modification** : modifier une référence ne refait que cet extrait ; changer le son de transition refait tout ; supprimer un fichier de sortie le refait ; insérer une ligne renomme les fichiers décalés au lieu de les recalculer. Tests dans la tâche 10.

---

## Fichiers

```
pyproject.toml, uv.lock, CLAUDE.md
.gitignore, LICENSE, README(.fr).md, CONTRIBUTING(.fr).md, .github/CODEOWNERS   (déjà présents)
.github/workflows/ci.yml
.claude/hooks/python_checks.py           (modifié : passe par uv run)
.claude/skills/test-rapide/SKILL.md
.claude/skills/compat-windows/SKILL.md
scripts/make_test_film.py                film de test (VFF + VFQ + VO, sous-titres FR), utilisé par les tests et le skill
scripts/check_windows_compat.py
src/podcleaner_clips/__init__.py         __version__
src/podcleaner_clips/cli.py              app Typer : version, config, run
src/podcleaner_clips/errors.py           ClipsError (message utilisateur, code 2)
src/podcleaner_clips/naming.py           timecodes, slug, abréviation de repli, noms de fichiers
src/podcleaner_clips/notes.py            lecture du fichier de notes, fragments, écriture de l'abréviation
src/podcleaner_clips/config.py           Settings + chargement TOML
src/podcleaner_clips/media.py            ffmpeg présent, ffprobe, choix des pistes, décodage de fenêtre, extraction des sous-titres
src/podcleaner_clips/subtitles.py        lecture SRT et repérage des fragments dans les sous-titres (pur)
src/podcleaner_clips/adjust.py           Word, repérage des fragments, calage des bornes (pur)
src/podcleaner_clips/transcribe.py       transcription d'une fenêtre (mlx / faster-whisper)
src/podcleaner_clips/claude.py           abréviation et choix des bornes, avec replis
src/podcleaner_clips/render_audio.py     gabarit temporel, mixage, loudnorm
src/podcleaner_clips/render_video.py     noir + image du film + bande son
src/podcleaner_clips/index.py            extraits.json, empreintes, plan de rendu
src/podcleaner_clips/pipeline.py         run de bout en bout + récapitulatif
tests/conftest.py                        fixtures : film de test, son de transition
tests/test_<module>.py                   un fichier par module
```

---

### Task 1 : socle du dépôt et CLI minimale

**Files :**
- Create : `pyproject.toml`, `CLAUDE.md`, `.github/workflows/ci.yml`, `src/podcleaner_clips/__init__.py`, `src/podcleaner_clips/cli.py`, `src/podcleaner_clips/errors.py`, `tests/test_cli.py`
- Modify : `.claude/hooks/python_checks.py`, `.gitignore` (déjà dans le dépôt, à compléter si besoin)

**Interfaces :**
- Produces : `podcleaner_clips.__version__ = "0.1.0"` ; `podcleaner_clips.cli.app: typer.Typer` ; `class ClipsError(Exception)` dont le message est affiché tel quel (`Erreur : …` sur stderr), code de sortie 2, sans trace Python.

- [ ] **Step 1 :** `brew install uv` (Python système = 3.9), branche `chore/project-setup`, `uv init --package --python 3.12` (sans écraser README, LICENSE ni `.gitignore`, déjà présents). `pyproject.toml` : `requires-python = ">=3.11,<3.13"`, script `podcleaner-clips = "podcleaner_clips.cli:main"`, dépendances `typer`, `platformdirs`, `rapidfuzz`, `numpy`, `anthropic`, `mlx-whisper ; sys_platform == 'darwin' and platform_machine == 'arm64'`, `faster-whisper ; sys_platform != 'darwin' or platform_machine != 'arm64'` ; groupe dev `pytest`, `ruff`. Ruff `line-length = 100`, règles `E,F,I,UP,B`. pytest : `markers = ["slow: charge un modèle Whisper"]`, `addopts = "-m 'not slow'"`.
- [ ] **Step 2 :** `.gitignore` existe déjà : vérifier que `tests/` ne génère aucun fichier média versionné (les films de test sont créés dans `tmp_path`).
- [ ] **Step 3 : tests qui échouent**

```python
def test_version_command_prints_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0 and "0.1.0" in result.output

def test_clips_error_exits_2_with_message():
    # commande de test qui lève ClipsError("Fichier introuvable : x.mkv")
    # → exit_code == 2, "Erreur : Fichier introuvable : x.mkv" dans la sortie, pas de "Traceback"
```

- [ ] **Step 4 :** `uv run pytest` → FAIL (module absent).
- [ ] **Step 5 :** implémenter `cli.py` (`app`, commande `version`, `main()` qui appelle `app` et transforme `ClipsError` en message + code 2) et `errors.py`.
- [ ] **Step 6 :** `uv run pytest` → PASS.
- [ ] **Step 7 :** hook : si `uv.lock` existe à la racine, préfixer ruff et pytest par `uv run` et lancer `pytest -q -x -m "not slow"` ; sinon comportement actuel. Vérifier en éditant un `.py` : le hook passe.
- [ ] **Step 8 :** `CLAUDE.md` : décisions de la spec et de la table « Décisions prises par ce plan », points de vigilance, commandes (`uv run pytest`, `uv run pytest -m slow`, `uv run ruff check`). CI : matrice `macos-latest` / `windows-latest` × Python 3.11 / 3.12, `astral-sh/setup-uv`, `FedericoCarboni/setup-ffmpeg`, puis `uv run ruff check` et `uv run pytest`.
- [ ] **Step 9 :** commit `chore: socle du projet, CLI minimale, CI`.

---

### Task 2 : timecodes et noms

**Files :** Create `src/podcleaner_clips/naming.py`, `tests/test_naming.py`

**Interfaces :**
- Produces :
  - `parse_tc(text: str) -> float` : accepte `H:MM:SS`, `HH:MM:SS` et `MM:SS` (minutes sur 1 à 3 chiffres : `45:12` = 2712 s), avec `.` ou `,` et 1 à 3 décimales ; tolère `;` à la place de `:` (`6;25`, `1:17;08`) et `25 min 30` / `25 min` ; `ValueError` sinon.
  - `format_tc(seconds: float) -> str` → `HH:MM:SS.mmm`.
  - `strip_accents(text: str) -> str`
  - `slugify(text: str, max_len: int = 40) -> str`
  - `fallback_abbreviation(title: str) -> str`
  - `film_folder_name(title: str) -> str`
  - `clip_basename(abbr: str, number: int, line: str) -> str` → sans extension (`line` = la référence notée).

- [ ] **Step 1 : tests qui échouent**

```python
def test_parse_tc_variants():
    assert parse_tc("00:12:34") == 754.0
    assert parse_tc("0:12:34.5") == 754.5
    assert parse_tc("00:12:34,250") == 754.25
    assert parse_tc("45:12") == 2712.0   # MM:SS sous une heure
    with pytest.raises(ValueError): parse_tc("45:60")

def test_format_tc():
    assert format_tc(754.25) == "00:12:34.250"

def test_slugify_spec_examples():
    assert slugify("Il s'appelle Juste Leblanc") == "il-s-appelle-juste-leblanc"
    assert slugify("Il a une bonne tête de vainqueur") == "il-a-une-bonne-tete-de-vainqueur"
    assert slugify("Ça, c'est l'été !") == "ca-c-est-l-ete"
    assert slugify("Œuf : « oui » / non ?") == "oeuf-oui-non"
    assert slugify("!!!") == "extrait"

def test_slugify_cuts_on_word_boundary():
    s = slugify("un deux trois quatre cinq six sept huit neuf dix onze")
    assert len(s) <= 40 and not s.endswith("-") and s.split("-")[-1] in "un deux trois quatre cinq six sept huit neuf dix onze".split()

def test_fallback_abbreviation():
    assert fallback_abbreviation("Le Dîner de cons") == "DDC"
    assert fallback_abbreviation("L'Auberge espagnole") == "AE"
    assert fallback_abbreviation("Alien") == "AL"   # un seul mot : deux premières lettres

def test_film_folder_name_is_windows_safe():
    assert film_folder_name("Le Dîner de cons") == "Le Diner de cons"
    assert film_folder_name('Mission: Impossible?') == "Mission Impossible"

def test_clip_basename():
    assert clip_basename("DDC", 1, "Il s'appelle Juste Leblanc") == "DDC-01-il-s-appelle-juste-leblanc"
```

- [ ] **Step 2 :** lancer → FAIL. **Step 3 :** implémenter (`unicodedata.normalize("NFKD")` + table pour `œ/æ`). **Step 4 :** lancer → PASS.
- [ ] **Step 5 :** commit `feat: timecodes, slugs et abréviation de repli`.

---

### Task 3 : fichier de notes

**Files :** Create `src/podcleaner_clips/notes.py`, `tests/test_notes.py`

**Interfaces :**
- Consumes : `parse_tc` (tâche 2).
- Produces :
  - `@dataclass(frozen=True) class ClipNote: number: int; start: float; end: float; reference: str; fragments: list[str]; source_line: int` (`reference` = texte tel que noté ; `fragments` = morceaux à rechercher ; `source_line` = numéro de ligne, pour les messages).
  - `@dataclass(frozen=True) class Notes: title: str | None; film_file: str | None; abbreviation: str | None; clips: list[ClipNote]; errors: list[str]`
  - `read_notes(path: Path) -> Notes`
  - `split_fragments(reference: str) -> list[str]`
  - `write_abbreviation(path: Path, abbr: str) -> None`

Règles :
- Une ligne d'extrait **commence et finit par un timecode** : `TC référence TC`. `TC` = tout ce qu'accepte `parse_tc` ; un `:` ou `-` collé après le premier timecode (`25 min 30 : …`) est retiré de la référence. L'ancienne forme `- TC > TC | référence` (puce `-` ou `*`) reste acceptée.
- Le premier timecode se repère en essayant `parse_tc` sur le plus long préfixe plausible (jusqu'à 3 jetons : `25 min 30`), le dernier sur le plus long suffixe plausible ; la référence est ce qui reste au milieu, espaces rognés. Référence vide → erreur pour cette ligne.
- Toute autre ligne est ignorée. `# Titre`, `fichier:` et `abreviation:` (accepter aussi `abréviation:`) sont facultatifs et lus n'importe où avant la première ligne d'extrait.
- Début ≥ fin → message dans `errors` (`Ligne 7 : le début 00:12:51 n'est pas avant la fin 00:12:34`), extrait non retenu, numérotation inchangée pour les autres.
- `split_fragments` : découpe sur `…`, `...` et ` - ` (tiret entouré d'espaces, pas celui de `peut-être`), rogne, garde l'ordre ; si un seul morceau, renvoie `[reference]`.

- [ ] **Step 1 : tests qui échouent** (fixture : notes au format réel, contenu neutre)

```python
REAL = """\
2:35 d'une soirée incroyable 2:51
6;25 si tu n'es pas d'accord tu es quoi ? 6:40
25 min 30 : ça va te remettre les idées en place 25:40
43:00 si je veux … il va comprendre ce soir 44:08
1:16:55 l'histoire se répète - encore une fois 1:17;08
Notes libres : la scène du taxi est trop longue.
"""

def test_reads_real_world_lines(tmp_path):
    n = read_notes(write(tmp_path, REAL))
    assert n.title is None and n.film_file is None
    assert [(c.number, c.start, c.end) for c in n.clips] == [
        (1, 155.0, 171.0), (2, 385.0, 400.0), (3, 1530.0, 1540.0), (4, 2580.0, 2648.0), (5, 4615.0, 4628.0)]
    assert n.clips[2].reference == "ça va te remettre les idées en place"   # « : » retiré
    assert n.clips[3].fragments == ["si je veux", "il va comprendre ce soir"]
    assert n.clips[4].fragments == ["l'histoire se répète", "encore une fois"]

def test_reads_legacy_format_with_header(tmp_path): ...  # exemple « Dîner de cons » avec # titre, fichier:, abreviation: et lignes « - TC > TC | réplique »
def test_split_fragments_keeps_hyphenated_words(): ...    # "peut-être pas" → ["peut-être pas"] ; "a ... b" → ["a", "b"]
def test_ignores_lines_without_both_timecodes(tmp_path): ...  # "2:35 sans fin", "rien 2:51", "Notes libres : …" ignorées
def test_bom_and_crlf(tmp_path): ...                      # "﻿2:35 a b 2:51\r\n" → 1 extrait
def test_start_after_end_is_reported_not_fatal(tmp_path): ...  # 2 lignes, la 1re inversée → clips == [numéro 2], errors mentionne "Ligne"
def test_empty_reference_is_an_error(tmp_path): ...       # "2:35 2:51" → erreur pour la ligne
def test_write_abbreviation_inserts_header_and_keeps_rest(tmp_path):
    # sans ligne abreviation → ajoutée après "fichier:" ou "# titre", sinon en première ligne ;
    # le reste du fichier identique octet pour octet ; fins de ligne CRLF conservées ; valeur remplacée si la ligne existe
```

- [ ] **Step 2 :** lancer → FAIL. **Step 3 :** implémenter (lecture `encoding="utf-8-sig"`, `newline=""` pour garder les fins de ligne à l'écriture). **Step 4 :** lancer → PASS.
- [ ] **Step 5 :** commit `feat: lecture du fichier de notes`.

---

### Task 4 : configuration par personne

**Files :** Create `src/podcleaner_clips/config.py`, `tests/test_config.py` ; Modify `cli.py` (commandes `config init`, `config show`)

**Interfaces :**
- Produces : `@dataclass(frozen=True) class Settings` ; `default_config_path() -> Path` ; `load_settings(path: Path | None = None) -> Settings` ; `write_template(path: Path) -> None`.

| Clé TOML | Champ | Défaut |
| --- | --- | --- |
| `dossier_episodes` | `episodes_dir: Path` | obligatoire |
| `dossier_films` | `films_dir: Path \| None` | aucun |
| `son_transition` | `transition_sound: Path \| None` | aucun (obligatoire sauf `--no-transition`) |
| `doublage_prefere` | `preferred_dub: str` | `"VFF"` (ou `"VFQ"`) |
| `[ajustement] tolerance_s` | `tolerance_s` | 15.0 (écart admis entre timecode noté et borne retenue ; marge transcrite de chaque côté) |
| `[ajustement] sous_titres` | `use_subtitles` | true |
| `[ajustement] score_trouve` / `score_sur` | `score_found`, `score_sure` | 70 / 85 |
| `[ajustement] pause_phrase_s` | `sentence_gap_s` | 0.6 |
| `[ajustement] marge_avant_s` / `marge_apres_s` | `pad_before_s`, `pad_after_s` | 0.10 / 0.25 |
| `[ajustement] modele_whisper` | `whisper_model` | `large-v3-turbo` |
| `[son] fondu_s` | `fade_s` | 0.7 |
| `[son] lufs` / `true_peak` | `lufs`, `true_peak` | -16.0 / -1.0 |
| `[claude] actif` / `modele` | `claude_enabled`, `claude_model` | true / `claude-haiku-5-5` |

Résolution du chemin : argument > `PODCLEANER_CLIPS_CONFIG` > `default_config_path()`. `~` développé. Fichier absent → `ClipsError` qui donne le chemin attendu et la commande `podcleaner-clips config init`.

- [ ] **Step 1 : tests qui échouent** : `test_defaults_applied`, `test_env_var_overrides_default_path` (monkeypatch), `test_missing_file_message_mentions_config_init`, `test_unknown_key_is_an_error` (faute de frappe → `ClipsError` qui nomme la clé), `test_preferred_dub_must_be_vff_or_vfq`, `test_paths_with_accents_and_tilde`, `test_template_roundtrips` (`write_template` puis `load_settings` après avoir rempli `dossier_episodes`).
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter avec `tomllib`. Modèle de fichier commenté en anglais. **Step 4 :** PASS.
- [ ] **Step 5 :** commit `feat: configuration par personne`.

---

### Task 5 : analyse du film, choix des pistes, sous-titres

**Files :** Create `src/podcleaner_clips/media.py`, `scripts/make_test_film.py`, `tests/conftest.py`, `tests/test_media.py`

**Interfaces :**
- Produces :
  - `require_ffmpeg() -> None` : `ClipsError("ffmpeg est introuvable. Installez-le (macOS : brew install ffmpeg ; Windows : winget install ffmpeg) puis relancez.")` si `ffmpeg` ou `ffprobe` manque.
  - `@dataclass(frozen=True) class AudioTrack: index: int` (rang parmi les pistes audio, pour `-map 0:a:N`) `; language: str | None; title: str | None; channels: int`
  - `@dataclass(frozen=True) class SubtitleTrack: index: int` (rang parmi les pistes de sous-titres, pour `-map 0:s:N`) `; language: str | None; title: str | None; codec: str`
  - `@dataclass(frozen=True) class VideoInfo: width: int; height: int; fps: str` (fraction ffprobe, ex. `24000/1001`) `; sar: str`
  - `@dataclass(frozen=True) class MediaInfo: duration: float; audio: list[AudioTrack]; subtitles: list[SubtitleTrack]; video: VideoInfo | None` (première vidéo hors `attached_pic`)
  - `probe(path: Path) -> MediaInfo`
  - `choose_audio_track(tracks: list[AudioTrack], forced: int | None, preferred_dub: str = "VFF") -> tuple[AudioTrack, str | None]` : la piste et un avertissement en français, ou `None`.
  - `choose_subtitle_track(tracks: list[SubtitleTrack]) -> SubtitleTrack | None`
  - `extract_subtitles(path: Path, track: SubtitleTrack) -> str` : texte SRT via `ffmpeg -map 0:s:N -f srt -`.
  - `decode_window(path: Path, track: int, start: float, duration: float) -> np.ndarray` : mono 16 kHz float32 via `ffmpeg -ss … -t … -map 0:a:N -ac 1 -ar 16000 -f f32le -`.
  - `scripts/make_test_film.py` : `make_test_film(out: Path, duration: float = 12.0, *, vf_channels: int = 2, video: str = "h264", subtitles: str | None = None) -> Path` (`video` : `"h264"` ou `"hevc10_anamorphic"`, ce dernier ajouté en tâche 9 ; `subtitles` : contenu SRT ajouté en piste `fre` « Complets ») ; .mkv avec mire, piste 0 VFF (`fre`, sinus 660 Hz, titre « Français VFF »), piste 1 VO (`eng`, sinus 440 Hz), piste 2 VFQ (`fre`, sinus 880 Hz, titre « Français VFQ »), pochette `mjpeg` en `attached_pic`. Exécutable en script : `python scripts/make_test_film.py out.mkv`.

Règles de `choose_audio_track` : `forced` hors bornes → `ClipsError` qui liste les pistes ; sinon, parmi les pistes françaises (langue `fre`/`fra`/`fr`/`fr-CA`, ou titre contenant `VF`, `Français`, `French`), la première qui correspond à `preferred_dub` (voir « Doublage » dans les décisions), sinon la première française ; aucune française → la première, avec l'avertissement `Aucune piste marquée française : piste 0 prise. Pistes : 0 eng « … » 6 canaux, 1 ? … Choisissez avec --audio-track N.`

- [ ] **Step 1 : tests qui échouent**

```python
def test_prefers_vff_when_vff_and_vfq_exist(): ...  # [fre "Français VFF", eng, fre "Français VFQ"] → index 0 ; preferred_dub="VFQ" → index 2
def test_detects_vfq_from_language_tag(): ...       # [fre "Français", fr-CA ""] + "VFQ" → index 1
def test_prefers_french_by_title_when_untagged(): ... # [None "English", None "VFF 5.1"] → index 1
def test_falls_back_to_first_with_warning(): ...    # [None, None] → index 0, avertissement contient "--audio-track"
def test_forced_out_of_range_lists_tracks(): ...
def test_chooses_full_french_text_subtitles(): ...  # [fre "Forcés" subrip, fre "Complets" subrip, eng subrip, fre "" hdmv_pgs_subtitle] → la piste « Complets »
def test_no_usable_subtitles(): ...                 # que des sous-titres image ou anglais → None
def test_probe_test_film(test_film):                # fixture conftest
    info = probe(test_film)
    assert abs(info.duration - 12.0) < 0.1 and [t.language for t in info.audio] == ["fre", "eng", "fre"]
    assert info.video is not None and info.video.width == 320       # la pochette n'est pas prise pour la vidéo
def test_extract_subtitles_roundtrip(tmp_path): ... # make_test_film(subtitles=SRT) → extract_subtitles contient le texte d'origine
def test_decode_window_length(test_film):
    assert len(decode_window(test_film, 0, 2.0, 3.0)) == pytest.approx(48000, abs=160)
def test_paths_with_spaces_and_accents(tmp_path): ... # film dans "Films été/Le Dîner (1998).mkv"
def test_missing_ffmpeg_message(monkeypatch): ...   # shutil.which → None ; message contient "brew install ffmpeg"
```

- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter (`ffprobe -v error -print_format json -show_format -show_streams`). **Step 4 :** PASS.
- [ ] **Step 5 :** commit `feat: analyse du film, choix de la VF et des sous-titres`.

---

### Task 5b : repérage dans les sous-titres (logique pure)

**Files :** Create `src/podcleaner_clips/subtitles.py`, `tests/test_subtitles.py`

**Interfaces :**
- Consumes : `Settings` (tâche 4).
- Produces :
  - `@dataclass(frozen=True) class Cue: start: float; end: float; text: str` (texte sans balises `<i>`, `{\an8}`, sauts de ligne remplacés par des espaces).
  - `parse_srt(text: str) -> list[Cue]` : tolère BOM, CRLF, numéros manquants, blocs vides.
  - `normalize(text: str) -> str` : minuscules, sans accents, ponctuation et apostrophes → espace, espaces réduits. Partagé avec la tâche 6.
  - `@dataclass(frozen=True) class Anchor: fragment: str; start: float; end: float; score: float`
  - `find_anchors(cues: list[Cue], fragments: list[str], noted_start: float, noted_end: float, s: Settings) -> list[Anchor]` : pour chaque fragment, le meilleur sous-titre de départ (les sous-titres suivants sont concaténés jusqu'à atteindre la longueur du fragment, pour un fragment à cheval) dans `[noted_start − tolerance_s, noted_end + tolerance_s]`, avec `rapidfuzz.fuzz.partial_ratio` sur les textes normalisés ; gardé si score ≥ `score_found`. À score égal (± 5), le plus proche du milieu de la plage notée.

- [ ] **Step 1 : tests qui échouent**

```python
def test_parse_srt_strips_tags_and_joins_lines(): ...  # "<i>Salut</i>\nça va ?" → "Salut ça va ?"
def test_parse_srt_tolerates_bom_crlf_and_gaps(): ...
def test_anchor_found_despite_approximate_reference(): ...  # sous-titre « Ce bébé, c'est une connerie. » ; fragment « ce bebe cest une connerie » → score ≥ 85
def test_anchor_limited_to_tolerance_window(): ...     # même texte à 40 s de la plage notée → ignoré
def test_anchor_spanning_two_cues(): ...               # fragment coupé entre deux sous-titres consécutifs → trouvé, start du 1er, end du 2e
def test_repeated_line_prefers_closest_to_notes(): ...
def test_short_cue_does_not_match_long_fragment(): ... # « Désolé ! » contre « un juif a encore crucifié le messie » → pas d'ancre sur « Désolé ! »
```

- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS.
- [ ] **Step 5 :** commit `feat: repérage des références dans les sous-titres`.

---

### Task 6 : calage des bornes (logique pure)

**Files :** Create `src/podcleaner_clips/adjust.py`, `tests/test_adjust.py`

**Interfaces :**
- Consumes : `Settings` (tâche 4), `normalize`, `Anchor` (tâche 5b).
- Produces :
  - `@dataclass(frozen=True) class Word: text: str; start: float; end: float` (temps absolus dans le film).
  - `@dataclass(frozen=True) class Match: fragment: str; first: int; last: int; score: float` (indices dans la liste de mots).
  - `find_fragments(words: list[Word], fragments: list[str], anchors: list[Anchor], noted_start: float, noted_end: float, s: Settings) -> list[Match | None]` : un résultat par fragment, `None` si introuvable.
  - `sentence_starts(words: list[Word], s: Settings) -> list[int]` et `sentence_ends(words: list[Word], s: Settings) -> list[int]` : indices des mots qui commencent / finissent une phrase.
  - `@dataclass(frozen=True) class Cut: start: float; end: float; method: str` (`"notes"`, `"whisper"`, `"claude"`) `; score: float | None; doubt: str | None` (raison en français, `None` si sûr).
  - `@dataclass(frozen=True) class Decision: cut: Cut; matches: list[Match | None]; first_word: int | None; last_word: int | None`
  - `adjust_cut(words: list[Word], fragments: list[str], anchors: list[Anchor], noted_start: float, noted_end: float, s: Settings) -> Decision` (`words` couvre `[noted_start − tolerance_s, noted_end + tolerance_s]`).
  - `cut_from_words(words: list[Word], first: int, last: int, s: Settings) -> Cut` : bornes depuis deux indices de mots, avec marges ; réutilisé par la tâche 7.
  - `bounds_ok(words: list[Word], first: int, last: int, matches: list[Match | None], noted_start: float, noted_end: float, s: Settings) -> bool` : début dans `noted_start ± tolerance_s`, fin dans `noted_end ± tolerance_s`, tous les fragments trouvés inclus, `first ≤ last`. Réutilisé par la tâche 7.

Algorithme :
- `find_fragments` : pour chaque fragment, fenêtres de `n−1` à `n+2` mots de la transcription (`n` = mots du fragment), au moins aussi longues que le fragment en caractères, score `fuzz.partial_ratio` sur les textes normalisés. S'il y a une ancre pour ce fragment, on ne cherche qu'à ±5 s de l'ancre ; sinon dans toute la fenêtre. Trouvé si score ≥ `score_found` ; parmi les ex æquo (± 5 points), le plus proche de l'ancre, sinon du milieu de la plage notée.
- `adjust_cut` :
  - Aucun fragment trouvé : `Cut` sur les timecodes notés, chacun déplacé vers l'extérieur jusqu'à une limite de mot, méthode `"notes"`, `doubt = "référence introuvable"`.
  - Début : parmi `sentence_starts` dont le mot commence dans `[noted_start − tolerance_s, noted_start + tolerance_s]` et au plus tard au premier mot du premier fragment trouvé, celui le plus proche de `noted_start`. Aucun : début du mot le plus proche de `noted_start` (sans dépasser le premier fragment), `doubt = "pas de début de phrase près du timecode noté"`.
  - Fin symétrique avec `sentence_ends`, `noted_end` et le dernier mot du dernier fragment trouvé.
  - Marges : `cut_from_words` applique `− pad_before_s` / `+ pad_after_s` sans entrer dans le mot voisin.
  - Fragment introuvable alors que d'autres le sont, ou score < `score_sure` : `doubt` le dit (« fragment introuvable : … », « référence peu sûre : … »). Méthode `"whisper"`.

- [ ] **Step 1 : tests qui échouent** (listes de `Word` écrites à la main, une scène d'environ 60 s)

```python
def test_scene_kept_with_short_reference(): ...
    # notes 27:15 > 27:37, référence « ce bébé c'est une connerie » vers 27:20 → l'extrait garde ~22 s,
    # début = début de phrase le plus proche de 27:15, fin = fin de phrase la plus proche de 27:37
def test_notes_10s_late_still_snap_to_sentences(): ...   # vraies phrases 10 s avant les notes → bornes sur ces phrases, fragment inclus
def test_two_fragments_both_included(): ...              # « si je veux … il va comprendre ce soir » sur 68 s → les deux dans l'extrait
def test_end_extended_to_include_late_fragment(): ...    # fragment qui finit 4 s après noted_end → fin après lui
def test_misspelled_reference_found(): ...               # « tu as été plus solide qu'un rock » vs transcription « plus solide qu'un roc » → trouvé
def test_anchor_restricts_search(): ...                  # fragment présent deux fois ; l'ancre désigne le 2e → match sur le 2e
def test_never_cuts_a_word(): ...                        # bornes toujours sur des débuts / fins de mots, marges sans chevaucher les voisins
def test_unfound_reference_keeps_notes_on_word_bounds(): ... # → méthode "notes", doubt "référence introuvable"
def test_partially_found_reference_is_flagged(): ...     # 1 fragment sur 2 trouvé → méthode "whisper", doubt cite le fragment manquant
def test_bounds_ok_rejects_cut_missing_a_fragment(): ...
```

- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS.
- [ ] **Step 5 :** commit `feat: calage des bornes sur la scène notée`.

---

### Task 7 : transcription et avis de Claude

**Files :** Create `src/podcleaner_clips/transcribe.py`, `src/podcleaner_clips/claude.py`, `tests/test_transcribe.py`, `tests/test_claude.py`

Charger le skill `claude-api` avant d'écrire `claude.py`.

**Interfaces :**
- Consumes : `decode_window` (tâche 5), `Word`, `Decision`, `cut_from_words`, `bounds_ok` (tâche 6), `fallback_abbreviation` (tâche 2), `Settings`.
- Produces :
  - `class Transcriber(Protocol): def words(self, audio: np.ndarray, offset: float) -> list[Word]`
  - `make_transcriber(model: str) -> Transcriber` : mlx-whisper sur macOS arm64, faster-whisper (`compute_type="int8"`) ailleurs ; `language="fr"`, `word_timestamps=True` ; modèle chargé une seule fois par exécution, au premier appel. `offset` est ajouté aux temps pour obtenir des temps absolus.
  - `@dataclass(frozen=True) class ClaudeAdvice: kind: str; answer: str; reason: str; model: str` (écrit tel quel dans l'index).
  - `class ClaudeClient` : `available: bool` (clé présente et `claude_enabled`) ; `propose_abbreviation(title: str, film_file: str | None) -> tuple[str, ClaudeAdvice | None]` ; `choose_bounds(words: list[Word], reference: str, decision: Decision, noted_start: float, noted_end: float, s: Settings) -> tuple[Cut, ClaudeAdvice | None]`.

Règles :
- Abréviation : réponse attendue `^[A-Z0-9]{2,6}$` ; indisponible, erreur réseau ou réponse invalide → `fallback_abbreviation(title)` et `None`.
- Bornes : appelé pour **chaque** extrait quand Claude est disponible et l'ajustement actif. Envoi des mots numérotés avec leurs temps, de la référence telle que notée, des timecodes notés (en précisant qu'ils sont approximatifs, ±15 s, et que l'extrait doit reprendre la scène notée), des fragments trouvés et de la proposition heuristique. Réponse structurée (tool use) `{premier_mot: int, dernier_mot: int, raison: str}` ; acceptée seulement si `bounds_ok`, puis convertie par `cut_from_words` avec `method="claude"` ; sinon coupe de `decision`. Indisponible → coupe de `decision`, `doubt` conservé.
- Une erreur de l'API n'arrête jamais l'exécution : un avertissement, puis le repli.

- [ ] **Step 1 : tests qui échouent** (`test_claude.py` avec un faux client Anthropic injecté, sans réseau)

```python
def test_abbreviation_without_key_uses_initials(monkeypatch): ...  # ANTHROPIC_API_KEY absent → ("DDC", None)
def test_abbreviation_invalid_answer_falls_back(): ...           # faux client répond "Le dîner" → "DDC"
def test_abbreviation_valid_answer(): ...                         # "DDC" → ("DDC", advice.kind == "abreviation")
def test_choose_bounds_applies_claude_choice(): ...               # indices valides → Cut.method == "claude"
def test_choose_bounds_rejects_out_of_bounds(): ...               # indice 999 → coupe d'origine
def test_choose_bounds_rejects_cut_missing_a_fragment(): ...      # bornes qui excluent un fragment trouvé → coupe d'origine
def test_api_error_falls_back_with_warning(): ...                 # faux client lève anthropic.APIError
```

Et `test_transcribe.py` (marqué `slow`, ignoré sans `say` sous macOS) : générer `say -v Thomas "Bonjour. Il s'appelle Juste Leblanc."`, transcrire, vérifier que `find_fragments(words, ["juste leblanc"], [], 0, 5, s)[0].score >= 85` et que les temps sont croissants.
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** `uv run pytest` puis `uv run pytest -m slow tests/test_transcribe.py` → PASS.
- [ ] **Step 5 :** commit `feat: transcription par fenêtre et avis de Claude`.

---

### Task 8 : rendu audio

**Files :** Create `src/podcleaner_clips/render_audio.py`, `tests/test_render_audio.py`

**Interfaces :**
- Consumes : `Settings`, `AudioTrack`.
- Produces :
  - `@dataclass(frozen=True) class ClipLayout: film_start: float; film_end: float; fade_s: float; transition_s: float | None` avec propriétés `clip_s`, `film_offset` (`max(0, transition_s − fade_s)`, 0 sans transition), `outro_offset` (`film_offset + clip_s − fade_s`), `total_s` (`max(film_offset + clip_s, outro_offset + transition_s)`, ou `clip_s`).
  - `audio_filter(layout: ClipLayout, with_transition: bool) -> str` : chaîne `-filter_complex`.
  - `render_audio(film: Path, track: AudioTrack, layout: ClipLayout, transition: Path | None, out_wav: Path, s: Settings) -> None`
  - `measure_loudness(path: Path) -> tuple[float, float]` (LUFS intégré, true peak dBTP) via `ebur128=peak=true`.

Chaîne : film `-ss film_start -t clip_s -map 0:a:N`, `aresample=48000`, `aformat=channel_layouts=stereo` (downmix ffmpeg), `afade=in:d=fade_s`, `afade=out:st=clip_s−fade_s:d=fade_s`, `adelay=film_offset` ; transition jouée deux fois (`asplit`), à 0 et à `outro_offset` ; `amix=normalize=0` ; `apad` + `atrim` à `total_s`. Puis normalisation `loudnorm` en deux passes (mesure en JSON, puis `linear=true` avec les valeurs mesurées, `I=lufs:TP=true_peak:LRA=11`), sortie `-ar 48000 -c:a pcm_s24le`. Écrire d'abord dans un fichier temporaire du même dossier, puis renommer, pour ne jamais laisser un WAV à moitié écrit.

- [ ] **Step 1 : tests qui échouent**

```python
def test_layout_with_transition():
    l = ClipLayout(100.0, 110.0, fade_s=0.7, transition_s=2.0)
    assert (l.film_offset, l.outro_offset, l.total_s) == pytest.approx((1.3, 10.6, 12.6))
def test_layout_without_transition():
    assert ClipLayout(100.0, 110.0, 0.7, None).total_s == pytest.approx(10.0)
def test_layout_transition_shorter_than_fade(): ...   # transition 0.4 → film_offset 0, total ≥ clip_s
def test_render_duration_and_loudness(test_film, transition_wav, tmp_path):
    render_audio(..., ClipLayout(2.0, 8.0, 0.7, 1.5), ...)
    # durée ffprobe ≈ 7.6 s ± 0.05 ; 48000 Hz ; 2 canaux ; LUFS ∈ [-17, -15] ; true peak ≤ -0.9
def test_render_no_transition_fades_edges(...): ...  # 50 premières ms bien plus faibles que le milieu (≥ 20 dB d'écart)
def test_vf_51_is_downmixed_to_stereo(tmp_path): ... # make_test_film(vf_channels=6) → sortie 2 canaux, LUFS ∈ [-17, -15]
```

- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS.
- [ ] **Step 5 :** commit `feat: rendu audio avec fondus, transition et normalisation`.

---

### Task 9 : rendu vidéo

**Files :** Create `src/podcleaner_clips/render_video.py`, `tests/test_render_video.py`

**Interfaces :**
- Consumes : `ClipLayout`, `VideoInfo`, le WAV de la tâche 8.
- Produces : `render_video(film: Path, video: VideoInfo, layout: ClipLayout, audio_wav: Path, out_mp4: Path) -> None`.

Chaîne : `color=black` (taille et cadence du film) pendant `film_offset`, image du film `-ss film_start -t clip_s`, noir pendant `total_s − film_offset − clip_s` ; chaque segment passe par `scale=W:H,setsar=1,fps=<fps>,format=yuv420p` avant `concat=n=3:v=1:a=0` (W×H = taille d'affichage, SAR appliqué) ; segments de durée nulle omis. Son : le WAV de la tâche 8 en AAC 192 kb/s. `libx264 -crf 18 -preset medium -movflags +faststart`. Écriture via fichier temporaire puis renommage.

- [ ] **Step 1 : tests qui échouent**

```python
def test_video_matches_audio_duration(test_film, transition_wav, tmp_path): ...
    # durée vidéo et audio du MP4 = layout.total_s ± 0.1 ; codecs h264 / aac ; pix_fmt yuv420p
def test_black_during_intro(...): ...        # image à t=0.2 s : luminance moyenne (signalstats YAVG) < 20 ; à film_offset + 1 s : > 20
def test_anamorphic_hevc_10bit_23976(tmp_path): ... # make_test_film(video="hevc10_anamorphic") → rendu sans erreur, yuv420p, SAR 1:1
def test_no_transition_has_no_black(...): ... # transition_s=None → aucune image noire en tête
```

- [ ] **Step 2 :** FAIL (ajouter `video="hevc10_anamorphic"` à `make_test_film` : `libx265 -pix_fmt yuv420p10le`, `setsar=4/3`, 24000/1001). **Step 3 :** implémenter. **Step 4 :** PASS.
- [ ] **Step 5 :** commit `feat: rendu vidéo avec écran noir pendant la transition`.

---

### Task 10 : index et relance incrémentale

**Files :** Create `src/podcleaner_clips/index.py`, `tests/test_index.py`

**Interfaces :**
- Consumes : `ClipNote`, `Cut`, `ClaudeAdvice`, `AudioTrack`.
- Produces :
  - `fingerprint(note: ClipNote, *, adjust: bool, transition: bool, track: int, transition_sha: str | None, render: dict) -> str` : sha256 d'un JSON trié ; le numéro de l'extrait n'en fait pas partie.
  - `file_sha256(path: Path) -> str`
  - `@dataclass class ClipEntry` (une entrée de `extraits[]`) et `@dataclass class FilmIndex` ; `load_index(path: Path) -> FilmIndex | None` ; `save_index(index: FilmIndex, path: Path) -> None` (écriture atomique, `ensure_ascii=False`, indentation 2).
  - `@dataclass(frozen=True) class Action: number: int; kind: str` (`"nouveau"`, `"modifie"`, `"inchange"`, `"renomme"`, `"manquant"`) `; reuse: ClipEntry | None; rename_from: dict[str, Path]`
  - `plan_actions(notes: list[ClipNote], fingerprints: dict[int, str], previous: FilmIndex | None, out_dir: Path, wanted: set[str]) -> tuple[list[Action], list[Path]]` : `wanted` ⊂ `{"audio", "video"}` ; le second élément liste les fichiers orphelins.

Schéma `extraits.json` :

```json
{
  "version": 1,
  "film": {"titre": "...", "abreviation": "DDC", "fichier": "...", "piste_audio": {"index": 1, "langue": "fre", "titre": "VF"}},
  "avis_claude": [{"type": "abreviation", "reponse": "DDC", "raison": "...", "modele": "claude-haiku-5-5"}],
  "extraits": [{
    "numero": 1, "reference": "...", "fragments_trouves": ["..."], "empreinte": "…",
    "notes": {"debut": "00:12:34.000", "fin": "00:12:51.000"},
    "retenu": {"debut": "00:12:33.420", "fin": "00:12:51.880", "methode": "whisper", "score": 96.2, "doute": null},
    "avis_claude": null,
    "duree_s": 21.06,
    "fichiers": {"audio": "audio/DDC-01-il-s-appelle-juste-leblanc.wav", "video": "video/DDC-01-il-s-appelle-juste-leblanc.mp4"}
  }]
}
```

Chemins relatifs au dossier du film, toujours avec `/`. `inchange` = même empreinte et tous les fichiers voulus présents : la coupe retenue est reprise telle quelle, sans Whisper ni Claude (reproductibilité). Même empreinte sous un autre numéro → `renomme`. Même empreinte mais un fichier voulu absent → `manquant` (rendu de ce fichier seulement, avec la coupe retenue).

- [ ] **Step 1 : tests qui échouent**

```python
def test_first_run_all_new(): ...
def test_unchanged_when_same_fingerprint_and_files_exist(tmp_path): ...
def test_changed_line_only_that_clip(): ...
def test_transition_sha_change_invalidates_all(): ...
def test_deleted_output_file_is_missing_kind(tmp_path): ...
def test_inserted_line_renames_shifted_clips(tmp_path): ... # nouvelle ligne en 1 → ancien 01 devient "renomme" vers 02
def test_removed_line_reported_as_orphan(tmp_path): ...
def test_index_roundtrip_utf8(tmp_path): ...              # référence accentuée relue à l'identique, fichier lisible en UTF-8
```

- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS.
- [ ] **Step 5 :** commit `feat: index extraits.json et relance incrémentale`.

---

### Task 11 : pipeline et commande `run`

**Files :** Create `src/podcleaner_clips/pipeline.py`, `tests/test_pipeline.py` ; Modify `cli.py`

**Interfaces :**
- Consumes : tout ce qui précède.
- Produces :
  - `@dataclass(frozen=True) class RunOptions: notes: Path; film: Path | None = None; transition: bool = True; audio: bool = True; video: bool = True; adjust: bool = True; dry_run: bool = False; audio_track: int | None = None; config: Path | None = None`
  - `run(opts: RunOptions, *, transcriber: Transcriber | None = None, claude: ClaudeClient | None = None, echo: Callable[[str], None] = typer.echo) -> FilmIndex | None` (injections pour les tests).
  - CLI : `podcleaner-clips run NOTES [--film CHEMIN] [--no-transition] [--audio-only | --video-only] [--no-adjust] [--dry-run] [--audio-track N] [--config CHEMIN]`.

Déroulé : `require_ffmpeg` → `load_settings` → `read_notes` (erreurs de lignes affichées) → film : `--film`, sinon `fichier:` (absolu, sinon relatif au dossier des notes, sinon à `dossier_films`) ; aucun → `ClipsError` qui liste les endroits cherchés et cite `--film` → titre : `# ` des notes, sinon déduit du nom du film (voir « Titre du film ») → `probe` + `choose_audio_track(…, preferred_dub)` → si `use_subtitles` et `choose_subtitle_track` trouve une piste : `extract_subtitles` une fois, `parse_srt` → abréviation (notes, sinon Claude/repli puis `write_abbreviation` hors `--dry-run`) → `plan_actions` → pour chaque extrait à faire : `find_anchors`, fenêtre `[début − tolerance_s, fin + tolerance_s]` bornée à `[0, durée]`, `transcriber.words`, `adjust_cut`, puis `choose_bounds` si Claude est disponible ; puis rendus ; renommages → `save_index` → récapitulatif.

Règles :
- `--audio-only` et `--video-only` ensemble → `ClipsError`. `--video-only` rend quand même le WAV dans un fichier temporaire, supprimé après.
- `--no-adjust` : ni sous-titres, ni Whisper, ni Claude pour les coupes, méthode `"notes"`.
- Extrait dont la fin dépasse la durée du film → erreur pour cet extrait, les autres continuent ; code de sortie 1 si au moins un extrait a échoué, 0 sinon.
- Pas de son de transition configuré sans `--no-transition` → `ClipsError` qui cite `son_transition` et `--no-transition`.
- `--dry-run` : transcription et calage faits, rien écrit (ni fichier, ni dossier, ni abréviation dans les notes, ni index).
- Récapitulatif : une ligne par extrait `01  DDC-01-il-s-appelle-juste-leblanc  00:12:34.000 > 00:12:51.000  →  00:12:33.420 > 00:12:51.880  21,1 s  nouveau`, suivie de `⚠ <doute>` si besoin ; puis avertissements (piste, orphelins) et le chemin du dossier.

- [ ] **Step 1 : tests qui échouent** (film de test, faux `Transcriber` qui renvoie des mots fixes, `ClaudeClient` indisponible)

```python
def test_end_to_end_no_adjust(tmp_path, test_film, transition_wav): ...
    # 2 extraits → audio/XX-01-….wav, audio/XX-02-….wav, video/….mp4, extraits.json ; abréviation écrite dans les notes
def test_dry_run_writes_nothing(tmp_path, ...): ...         # aucun nouveau fichier ni dossier ; notes identiques ; noms affichés
def test_audio_only_and_video_only(...): ...
def test_audio_and_video_only_together_is_error(...): ...
def test_second_run_is_all_unchanged(...): ...              # aucun ffmpeg de rendu lancé (compter via monkeypatch), récap « inchangé »
def test_clip_past_film_end_fails_alone(...): ...           # code 1, l'autre extrait rendu
def test_film_resolved_from_films_dir(...): ...
def test_film_option_and_title_from_film_name(...): ...  # notes sans en-tête + --film « X (2015) Bluray.mkv » → dossier « X (2015) »
def test_subtitles_used_when_present(...): ...          # film de test avec sous-titres FR → ancres transmises à adjust_cut (espion)
def test_fake_transcriber_cut_written_to_index(...): ...    # méthode "whisper", timecodes retenus ≠ notés
```

- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter. **Step 4 :** PASS.
- [ ] **Step 5 :** essai manuel sur un vrai film (dossier `samples/`, hors dépôt) : `uv run podcleaner-clips run samples/notes.md --dry-run`, puis sans `--dry-run` ; écouter deux extraits.
- [ ] **Step 6 :** commit `feat: commande run de bout en bout`.

---

### Task 12 : skills du projet, README et vérification Windows

**Files :** Create `.claude/skills/test-rapide/SKILL.md`, `.claude/skills/compat-windows/SKILL.md`, `scripts/check_windows_compat.py`, `tests/test_check_windows_compat.py` ; Modify `README.md`, `README.fr.md`

**Interfaces :**
- Consumes : `scripts/make_test_film.py`, la CLI.
- Produces : `check(root: Path) -> list[str]` dans `scripts/check_windows_compat.py` (une ligne par problème : `fichier:ligne : message`), code de sortie 1 si la liste n'est pas vide.

- [ ] **Step 1 : test qui échoue** : `check` repère dans un dossier de test `open(p)` et `p.read_text()` sans `encoding=`, un chemin écrit en dur (`"/Users/"`, `"C:\\"`), `subprocess` avec `shell=True` ; et ne signale rien sur `src/` du projet.
- [ ] **Step 2 :** FAIL. **Step 3 :** implémenter (module `ast`). **Step 4 :** PASS.
- [ ] **Step 5 :** skill **test-rapide** (écrit avec `skill-creator`) : générer un film de 20 s avec `make_test_film.py` (VF + VO), un fichier de notes de deux extraits au format réel (`TC référence TC`), une config temporaire, lancer `run --no-adjust` puis `run`, et vérifier noms, durées (`ffprobe`), niveaux (-16 ± 1 LUFS, ≤ -1 dBTP) et piste VF (sinus 660 Hz dominant). Skill **compat-windows** : lancer `check_windows_compat.py`, `require_ffmpeg`, puis un `run --no-adjust` dans un dossier `Été à l'écran/` ; à faire avant chaque version.
- [ ] **Step 6 :** README en anglais et en français (`README.md`, `README.fr.md`) : installation (uv, ffmpeg sur macOS et Windows), `config init`, format du fichier de notes, options, sorties, Claude optionnel.
- [ ] **Step 7 :** `uv run ruff check && uv run pytest`, puis lancer le skill test-rapide → tout passe.
- [ ] **Step 8 :** commit `docs: skills test rapide et compatibilité Windows, README`.

---

## Ordre et parallélisme

1 → 2 → 3 → 4 → 5, puis 5b (ne dépend que de 4) et 8 (dépend de 5) peuvent avancer en parallèle ; 6 après 5b ; 7 après 5 et 6 ; 9 après 8 ; 10 après 3, 6 et 7 ; 11 après tout ; 12 en dernier.

## Données de test

- Générées par `scripts/make_test_film.py` pour les tests automatiques (aucun film dans le dépôt).
- Un vrai film et un vrai fichier de notes dans `samples/` (ignoré par git) pour l'essai manuel de la tâche 11. Déjà disponible : `samples/the-night-before.md`, 16 extraits notés par le mainteneur sur *The Night Before* (2015), film avec VFF et VFQ en 5.1, VO, sous-titres français en texte et pochette `mjpeg` (chemin du film en tête du fichier).
