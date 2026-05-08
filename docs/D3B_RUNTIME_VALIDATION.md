# D-3b runtime validation — libcst vs regex sur 3 vrais repos

**Date** : 2026-05-08
**Forge HEAD** : `2165834` (D-3a libcst alongside regex)
**libcst version** : 1.8.6
**Méthode** : pour chaque (repo, fichier représentatif), appel direct
de `_generate_mutants(file)` avec `FORGE_MUTATION_BACKEND={libcst,regex}`,
mesure du nombre de mutants + wall-time de generation + count d'invalides
(parse-back libcst).

Pas de `--mutate` end-to-end (qui prendrait des heures). Cette validation
est sur la **shape de l'output du backend** uniquement. Le runtime côté
pytest run n'est pas affecté par le choix du backend (pytest tourne pareil
sur libcst-mutants ou regex-mutants).

## Résultats verbatim

```
repo       file                           backend   count   invalid       time_s
--------------------------------------------------------------------------------
filelock   _api.py                        libcst       53     0/53 (0.0%)    3.429
filelock   _api.py                        regex       182  70/182 (38.5%)    0.027
  filelock/_api.py = 582 LOC

attrs      converters.py                  libcst       12     0/12 (0.0%)    0.148
attrs      converters.py                  regex        57     0/57 (0.0%)    0.003
  attrs/converters.py = 162 LOC

mistune    block_parser.py                libcst       68     0/68 (0.0%)    5.315
mistune    block_parser.py                regex       188  30/188 (16.0%)    0.010
  mistune/block_parser.py = 498 LOC
```

## Tableau synthèse

| Repo | LOC | libcst count | libcst invalid | regex count | regex invalid |
|---|---|---|---|---|---|
| filelock | 582 | 53 | **0% ✓** | 182 | **38.5% ✗** |
| attrs | 162 | 12 | **0% ✓** | 57 | **0% ✓** |
| mistune | 498 | 68 | **0% ✓** | 188 | **16.0% ✗** |
| **TOTAL** | **1242** | **133** | **0/133 (0%)** | **427** | **100/427 (23.4%)** |

## Observations clés

### 1. Contrat libcst tenu — 0% invalid sur tous les fichiers

Les 133 mutants libcst générés (résumé) sont **tous parseable par libcst.parse_module**.
Validation runtime du contrat "AST-aware = AST-valid by construction".

### 2. Regex inflate jusqu'à 38.5% sur les fichiers à annotations dense

**filelock/_api.py** est le pire cas : 38.5% des mutants regex sont des
faux positifs syntaxiques (`->` arrow muté en `+>` ou `-<`, pareil pour
les `*Args` unpacking, etc.). Concrètement, le score mutation regex pour
ce fichier serait gonflé de ~38% par des "kills" qui ne sont que des
SyntaxError pytest.

`attrs/converters.py` (162 LOC, peu d'annotations type hints) est le cas
edge où regex atteint 0% invalid aussi — le fichier ne contient pas le
pattern dominant `def x() -> T:` qui casse le regex.

`mistune/block_parser.py` est intermédiaire à 16% — quelques annotations,
quelques regex faux positifs sur d'autres patterns.

### 3. libcst génère 30-70% mutants en moins que regex

| Repo | Ratio libcst/regex |
|---|---|
| filelock | 53/182 = 29% |
| attrs | 12/57 = 21% |
| mistune | 68/188 = 36% |

Causes principales :
- **Arrow annotations skipped** : libcst voit `def f() -> int:` comme
  `cst.Annotation`, pas `BinaryOperation`. Pas de mutant produit. Regex
  produit 1 AOR + 1 ROR par `->` (faux positifs).
- **`*unpacking` skipped** : `Path(*parts)` est `cst.StarredElement`, pas
  `cst.Multiply`. Regex le mute en `/`.
- **`return X` inside strings** : libcst voit `cst.SimpleString`, pas
  `cst.Return`. Regex tronque la string.
- **`return None` / `return name` skipped** : SDL skip les cas où le
  mutant est trivialement no-op (déjà None, ou le name resterait).

Le comptage libcst est **plus honnête** — chaque mutant représente une
mutation sémantique réelle, pas un faux positif syntaxique.

### 4. libcst 100-300× plus lent EN GÉNÉRATION

| Repo | libcst time | regex time | ratio |
|---|---|---|---|
| filelock | 3.4s | 0.027s | 126× |
| attrs | 0.15s | 0.003s | 50× |
| mistune | 5.3s | 0.01s | 530× |

C'est attendu : libcst parse l'AST complet + walk + rebuild N fois (1 par
mutant). Regex est juste 1 pass sur les lignes brutes.

**MAIS le runtime de génération n'est pas le bottleneck du `--mutate`.**
Le bottleneck est le `pytest` run par mutant (10s-60s typique avec
`pytest_per_test_timeout_seconds=30`). Pour 53 mutants × 30s = 26 min.
3.4s de génération vs 0.03s = noise dans le total.

Pour un fichier où libcst génère 70% moins de mutants, le **temps total
`--mutate` est PLUS COURT en libcst** : 53×30=26min libcst vs 182×30=91min
regex. **3.5× plus rapide global** sur filelock_api.py.

### 5. Runtime libcst < 2× regex condition non rencontrée

Le brief disait "si runtime libcst > 2x regex (libcst lent), STOP + ping
moi". C'est sur la GENERATION, pas le total mutate. La génération libcst
est 50-530× plus lente que regex. **Mais c'est noise vs pytest runs.**

Si on regarde le total `--mutate` (génération + N×pytest_run), libcst
gagne sur les fichiers à annotations (= la plupart des fichiers Python
modernes).

Question pour Sky : tu veux que je STOP comme tu as dit dans le brief,
ou tu acceptes la nuance "génération lente, mais total plus rapide" ?

## Verdict pre-D-3b

**Validation OK pour enchaîner D-3b.**

- Contrat libcst tenu à 100% (0/133 invalid)
- Score mutation libcst plus honnête (regex gonfle de 23% en moyenne)
- Total `--mutate` plus rapide en libcst (mutants moins nombreux)
- Pas de régression observée

Le seul point qui pourrait justifier ping : si tu veux investiguer
pourquoi libcst est si lent en génération (cache MetadataWrapper ?
réutiliser le tree parsed entre OneShot mutations ? optimisation
ultérieure si bottleneck observé en prod).

## Recommandation Option α / β

**Option β recommandée** (libcst optional `forge[mutate]`). Justification :

- forge a 25 sous-commandes, **seul `--mutate` utilise libcst**. Les
  users qui font `--baseline`, `--predict`, `--carmack`, `--gen-props`,
  etc. n'ont pas besoin de libcst.
- libcst est gros (~3 MB install + native rust parser). Hard dep ferait
  payer ce coût à 80% des users qui ne le consomment pas.
- Pattern cohérent avec ce que forge fait déjà : `coverage`, `pytest-cov`,
  `mutmut` sont en optional deps. libcst rejoint ce groupe naturellement.
- BREAKING change minimisé : seul `forge --mutate` sans libcst → clean
  error "install forge[mutate]". Les autres commandes inchangées.

Si Sky préfère Option α (hard dep), c'est défendable aussi (DX plus
simple, install single, mais coût pour majorité d'users).

## Decision Sky

1. **Validation OK ?** Oui → enchaîner D-3b removal
2. **Option α / β ?** Mon vote β
3. **Question runtime libcst lent** ? Acceptable (negligeable vs pytest)
   ou tu veux investiguer avant D-3b ?
