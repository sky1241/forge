# Cycle 3 — Plan de bataille

Faire passer forge de **75% cleane (outil indie)** à **90% cleane (produit
PyPI 1.0 prêt)**. Chunks indépendants, validables un par un avec tests
before/after pour prouver chaque amélioration.

## Métriques baseline (2026-05-08, commit `c6b866b`)

```
LOC forge.py        : 3155
Test count          : 97
Test suite duration : 12.5s
Coverage forge.py   : 0% mesurable (tests importlib-load → coverage tool blind)
```

**Régressions à éviter** : les 97 tests doivent passer après chaque chunk.
Le runtime du test suite ne doit pas exploser (>30s = warning).

---

## CHUNK 0 — Coverage instrumenté
**Avant tout le reste.** Sans coverage mesurable, on peut pas prouver les
chunks suivants.

### Diagnostic
Les tests font `importlib.util.spec_from_file_location("forge_root", ...)
exec_module(...)`. Coverage.py ne reconnaît pas ce module dynamique comme
"forge". Résultat : 0% de coverage rapporté même quand 80% du code est
exercé.

### Fix
Soit :
- (a) Installer forge comme package éditable via `pip install -e .` dans la
  CI (déjà fait via pyproject.toml entry point) — vérifier que `import
  forge` standard marche
- (b) Configurer `[tool.coverage.run] source_pkgs = ["forge"]` ou
  `data_file` pour pointer le fichier directement
- (c) Migrer les tests vers `import forge` standard et retirer le
  spec_from_file_location

### Tests before/after
```bash
# AVANT : pytest --cov=forge tests/  → "Module forge was never imported"
# APRÈS : pytest --cov=forge tests/  → table coverage par fonction
```

### Commit attendu
`fix(test): coverage forge.py mesurable via import standard`

### Effort
**~30 min**. Sans risque — pas de modif fonctionnelle, juste plumbing.

---

## CHUNK 1 — Tests des sous-commandes secondaires
**À faire avant tout refactor.** Sinon on peut casser une sous-commande
sans le voir.

### État actuel
| Sous-commande | Test dédié ? |
|---|---|
| `forge` (default) | ✅ via dogfood |
| `--baseline` | ✅ |
| `--locate` | ✅ TestFaultLocate* (3 tests) |
| `--bisect` | ✅ TestBisectSurvivors |
| `--mutate` | ✅ TestMutationTimeoutHonest (3 tests) |
| `--gen-props` | ✅ TestGenProps* (4 tests) |
| `--predict` | ✅ TestPredictMinLocClamp |
| `--carmack` | ⚠️ via TestPolishUX (cosmétique) — pas test fonctionnel |
| `--anomaly` | ❌ aucun |
| `--snapshot` | ❌ aucun |
| `--snapshot-check` | ❌ aucun |
| `--full-cycle` | ❌ aucun |
| `--minimize` | ❌ aucun |
| `--flaky` / `--flaky-dtw` | ❌ aucun |
| `--add` / `--close` | ✅ via test BUG+ → BUG- |
| `--init` | ⚠️ implicite |
| `--watch` | ❌ pas testable easily (loop infini) |

### Tests à ajouter
- `test_carmack_returns_score_per_file` (vrai test fonctionnel, pas juste UI)
- `test_anomaly_zscore_flags_outlier` (créer 4 fichiers où 1 est clairement outlier)
- `test_snapshot_capture_and_check_roundtrip` (capture echo X, modify command, check fail)
- `test_full_cycle_runs_all_steps_without_crash`
- `test_minimize_reduces_failing_input` (input file → ddmin)
- `test_flaky_classifies_consistent_failures`
- `test_flaky_dtw_runs_n_times`
- `test_init_creates_bugs_md_template`

### Tests before/after
```bash
# AVANT
$ pytest tests/ --collect-only -q | wc -l
# 97
$ pytest --cov=forge tests/ -q | grep "TOTAL"
# (à mesurer après chunk 0)

# APRÈS
$ pytest tests/ --collect-only -q | wc -l
# 105+ (8+ nouveaux tests fonctionnels)
$ pytest --cov=forge tests/ -q | grep "TOTAL"
# +15-20% coverage attendu sur les sous-commandes secondaires
```

### Commit attendu
`test: cover anomaly + snapshot + full-cycle + minimize + flaky (8 tests)`

### Effort
**~2-3h**. Sans risque modif code (juste tests).

---

## CHUNK 2 — `.forge/config.json` pour tuer les magic numbers

### Magic numbers actuels (les vrais)
```python
MUTATION_THRESHOLD = 80           # forge.py:66
MIN_PREDICT_LOC = 10              # in predict_defects
CRITICAL_LOAD = 12.0              # fleet-bot only, ignore
LOAD_HIGH_THRESHOLD = 8.0         # fleet-bot only, ignore
LOAD_RECOVERED_THRESHOLD = 4.0    # fleet-bot only, ignore
# Inline magic numbers in forge.py:
timeout=30                        # pytest plugin (run_tests:496)
timeout=600                       # fault_locate, run_tests subprocess
timeout=120                       # bisect per-iteration
weeks=8                           # default predict horizon
horizon=14.0                      # KM survival horizon (predict_carmack:2238)
```

### Fix
Helper `_load_forge_config(root)` qui lit `.forge/config.json` si présent
et retourne un dict avec valeurs par défaut. Le user peut écrire :
```json
{
  "mutation_threshold": 70,
  "predict_min_loc": 5,
  "predict_horizon_weeks": 12,
  "carmack_km_horizon_days": 30,
  "test_runner_timeout_seconds": 900
}
```

Tous les sites qui utilisaient les magic numbers passent par
`_load_forge_config()`. Compat backward : sans config.json, mêmes défauts.

### Tests before/after
```python
# AVANT
def test_mutation_threshold_hardcoded():
    assert forge.MUTATION_THRESHOLD == 80  # locked

# APRÈS
def test_mutation_threshold_overridable_via_config(tmp_path):
    (tmp_path / ".forge").mkdir()
    (tmp_path / ".forge" / "config.json").write_text('{"mutation_threshold": 70}')
    cfg = forge._load_forge_config(tmp_path)
    assert cfg["mutation_threshold"] == 70

def test_default_config_unchanged_when_no_file(tmp_path):
    cfg = forge._load_forge_config(tmp_path)
    assert cfg["mutation_threshold"] == 80  # default still 80
```

### Commit attendu
`feat: .forge/config.json overrides hardcoded thresholds`

### Effort
**~1.5h**. Sans risque (defaults inchangés).

---

## CHUNK 3 — argparse propre

### Avant
```python
def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(HELP_TEXT)
    if "--full-cycle" in args:
        full_cycle(root)
    if "--carmack" in args:
        idx = args.index("--carmack")
        weeks = ...
        # 25 if-blocks répétés
```

### Problèmes
- Pas de validation des flags (`--bisct test_x` silencieusement ignoré)
- Help text écrit à la main, peut diverger du code
- Pas de type checking sur les args (genre `--weeks N` accepte `--weeks abc`)
- Comportement pas défini si plusieurs flags incompatibles

### Fix
```python
def build_parser():
    p = argparse.ArgumentParser(prog="forge", description="...")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("baseline", ...)
    sub.add_parser("init", ...)
    carmack = sub.add_parser("carmack", ...)
    carmack.add_argument("--weeks", type=int, default=8)
    # ... etc
    return p

def main():
    args = build_parser().parse_args()
    if args.cmd == "carmack":
        predict_carmack(root, args.weeks)
    # etc
```

**ATTENTION** : breaking change subtle. L'API actuelle est `forge --carmack
--weeks 8`. Avec argparse subparsers strictes, ce serait `forge carmack
--weeks 8` (sans tiret). Soit on garde flags-only mode (argparse top-level
flags mutuellement exclusifs), soit subparser style. Je propose
**flags-only** pour 0 breaking change.

### Tests before/after
```python
# AVANT
def test_unknown_flag_silently_ignored():
    # forge --frobulate ne fait rien, exit 0 (mauvais)
    pass

# APRÈS
def test_unknown_flag_errors_out(capsys):
    with pytest.raises(SystemExit):
        forge.build_parser().parse_args(["--frobulate"])
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err

def test_invalid_weeks_type_errors():
    with pytest.raises(SystemExit):
        forge.build_parser().parse_args(["--carmack", "--weeks", "abc"])

def test_help_auto_generated_and_complete():
    parser = forge.build_parser()
    h = parser.format_help()
    for sub in ("--carmack", "--predict", "--mutate", "--bisect"):
        assert sub in h
```

### Risque
**Moyen**. La migration peut casser des invocations subtiles. Faut tester
chaque sous-commande après. Critère de rollback : si un test cycle 1/2/2.5
existant casse, revert.

### Commit attendu
`refactor: argparse for CLI (validates flags, types, auto-help)`

### Effort
**~3h**. Risqué — faut faire avec soin.

---

## CHUNK 4 — Split forge.py en modules

### Cible
```
forge/
├── __init__.py        # re-exports for backward-compat (`import forge` works)
├── cli.py             # main() + argparse
├── run.py             # run_tests, baseline, find_tests, _parse_pytest_*
├── analytics.py       # predict_defects, predict_carmack, anomaly_detect
├── locate.py          # fault_locate (Ochiai SBFL)
├── bisect.py          # bisect_test
├── mutate.py          # run_mutation, _generate_mutants
├── gen_props.py       # gen_props + _is_destructive_function
├── flaky.py           # detect_flaky, flaky_dtw
├── snapshot.py        # snapshot_capture, snapshot_check
├── bugs.py            # add_bug, close_bug, init_repo
└── _algos.py          # private: _haar_wavelet, _kalman, _kaplan_meier, _louvain
```

### Compat
Les tests existants font :
```python
spec = importlib.util.spec_from_file_location("forge_root", REPO_ROOT / "forge.py")
forge = importlib.util.module_from_spec(spec)
```

Après split, `forge.py` ne sera plus là — devient `forge/__init__.py`.
**Adapter les tests** pour `import forge` standard. Les API publiques
restent stables : `forge.predict_carmack`, `forge.run_tests`, etc.
(re-exportées dans `__init__.py`).

### Tests before/after
```bash
# AVANT
$ wc -l forge.py
# 3155
$ python -c "import forge; print(forge.predict_carmack)"
# Module-level function

# APRÈS
$ wc -l forge/*.py
# ~3155 lignes total mais split en 12 fichiers
$ python -c "import forge; print(forge.predict_carmack)"
# Pareil — re-exported from forge.analytics

# Tests existants doivent passer SANS modification
$ pytest tests/ -q
# 97+ passed
```

### Risque
**ÉLEVÉ**. Breaking change pour les imports. Faut migrer les tests aussi.
Critère de rollback : si on ne tient pas le `import forge` backward-compat,
revert.

### Commit attendu
`refactor: split forge.py monolith into forge/ package (12 modules)`

### Effort
**~4h**. Le plus risqué.

---

## Ordre d'exécution

1. **Chunk 0** (coverage) → metric baseline mesurable
2. **Chunk 1** (tests subcommands) → safety net avant tout refactor
3. **Chunk 2** (config.json) → tue les magic numbers, no breaking change
4. **Chunk 3** (argparse) → validation des flags
5. **Chunk 4** (split modules) → architecture pro

Chunks 0, 1, 2 = **safe, parallélisables**.
Chunks 3 = **moyennement risqué**.
Chunk 4 = **risqué, à faire en dernier quand tout le reste est blindé**.

## Métriques cibles fin de cycle 3

```
LOC forge/__init__.py + modules : ~3300 (légère hausse, normal après split)
Test count                      : 105-115 tests
Test suite duration             : <20s
Coverage forge                  : ≥80%
Magic numbers résiduels         : 0 (tous via .forge/config.json)
```

## Critères de succès cycle 3

- ✅ Tous les tests cycle 1/2/2.5 passent SANS modif fonctionnelle
- ✅ Coverage forge.py mesuré et ≥80%
- ✅ Toutes les sous-commandes ont au moins 1 test fonctionnel dédié
- ✅ `forge --frobulate` produit une erreur claire (validation argparse)
- ✅ `.forge/config.json` overrides les seuils (test régression)
- ✅ `import forge` continue à marcher après split (backward-compat)
- ✅ Chaque chunk a son commit séparé avec metrics avant/après

## Critères de rollback

À chaque chunk, si :
- Un test existant casse sans raison fonctionnelle → revert le chunk
- Le coverage régresse → revert
- Le runtime suite explose (>30s) → revert

Format des commits :
```
chunk N: <feat/fix/refactor>: <one-line>

Metrics before:
  - <X1>: <V1>
  - <X2>: <V2>

Metrics after:
  - <X1>: <V1'>
  - <X2>: <V2'>

Tests added:
  - <list>

Tests changed (if any):
  - <list>
```

## Estimation totale

**~10-12h** étalées sur plusieurs sessions. Chaque chunk peut être fait
indépendamment et pushé séparément. Aucune obligation de tout enchaîner.
