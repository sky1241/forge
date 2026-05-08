# D-3 pre-scan libcst — rapport

**Date** : 2026-05-08
**Tool** : `tools/d3_libcst_prescan.py` (one-shot, hors package)
**libcst version** : 1.8.6

## Méthode

Pour chaque fichier sample :
1. Run `forge._generate_mutants(file)` (regex-based, statu quo)
2. Pour chaque `mut_source` généré, tenter `libcst.parse_module(mut_source)`
3. Compter valid (parse OK) vs invalid (`ParserSyntaxError`)
4. Catégoriser les invalides par pattern

Aucune modif de `forge.py` ni `tests/`. Le tool tools/ peut rester ou être
supprimé après pre-scan.

## Résultats globaux

| Fichier | Total mutants | Valid | Invalid | % invalid |
|---|---|---|---|---|
| `tests/test_forge_destructive_skip.py` | 60 | 56 | 4 | 6.7% |
| `tests/test_typing.py` | 20 | 18 | 2 | 10.0% |
| `forge.py` | 1605 | 1440 | 165 | 10.3% |
| `tests/test_forge_real_algos.py` | 1209 | 1124 | 85 | 7.0% |
| **TOTAL** | **2894** | **2638** | **256** | **8.8%** |

**Bracket** : MIGRATE-CAREFUL (5-20%) selon ton seuil défini dans le brief.

## Distribution des invalides par opérateur

```
148 AOR (Arithmetic Operator Replacement, e.g. + → -)
 72 ROR (Relational Operator Replacement, e.g. == → !=)
 36 SDL (Statement Deletion / "return None")
```

AOR + ROR = 220/256 = **86%** des invalides. Pattern dominant clair.

## Top 3 patterns d'invalides — exemples verbatim

### Pattern 1 — `->` arrow muté en `+>` ou `-<` (148 + 72 = 220 mutants)

Le regex `(?<!=)\+(?!=)` (AOR) matche le `-` dans `->` (return type annotation).
Pareil pour ROR sur `>`. Résultat : signatures de fonctions cassées.

Exemples (forge.py + test_typing.py) :
```
orig:  def _safe_path(filepath: str | Path) -> str:
mut:   def _safe_path(filepath: str | Path) +> str:    [AOR — invalid syntax]
mut:   def _safe_path(filepath: str | Path) -< str:    [ROR — invalid syntax]

orig:  def _load_forge_config(root: Path) -> dict[str, Any]:
mut:   def _load_forge_config(root: Path) +> dict[str, Any]:
```

**Implication** : depuis cycle 4 C-A (annotations sur 64 fonctions), CHAQUE
fonction annotée fait 2 mutants invalides supplémentaires (1 AOR + 1 ROR sur
le `->`). Le ratio invalid a probablement augmenté de ~5% pré-cycle 4 à 10%
post-cycle 4 à cause de ça.

### Pattern 2 — `*` unpacking muté en `/` (cas isolé mais éclairant)

```
orig:  return str(Path(*parts[-3:]))
mut:   return str(Path(/parts[-3:]))                   [AOR — invalid syntax]
```

Le `*` ici est argument unpacking, pas multiplication. Regex aveugle au
contexte AST → mutant invalide.

### Pattern 3 — `return X` dans une string littérale (36 mutants SDL)

Le SDL pattern `return (.+)` → `return None` matche dans le contenu de
strings utilisées comme test fixtures. Comme `\n` est dans la string,
`return None` tronque sans guillemet final.

Exemples (tests/test_forge_real_algos.py) :
```
orig:  "def hello(s):\n    return s.upper()\n", encoding="utf-8"
mut:   "def hello(s):\n    return None
                                       ^^^ unterminated string

orig:  src = "def add(a, b): return a + b"
mut:   src = "def add(a, b): return None
                                          ^^^ unterminated string
```

**Implication** : ce pattern produit du DOUBLE bruit — non seulement le
mutant n'est pas significatif (la string-littérale ne représente pas du
code exécuté), mais en plus il casse le parser. Faux positifs de mauvaise
qualité.

## Analyse de l'impact actuel

**Aujourd'hui (regex-based)** :
- Ces 256 mutants invalides sont quand même testés contre pytest
- pytest les rejette tous immédiatement (SyntaxError au compile)
- Forge les compte comme `killed` (returncode != 0 est suffisant)
- Le score mutation est gonflé artificiellement (~9% de "kills" sont des
  invalides syntaxe, pas de vrais kills sémantiques)

**Avec libcst (D-3 cible)** :
- Le mutator opère sur l'AST → impossible de produire ces 256 mutants
- Score plus honnête (vrais sémantique kills uniquement)
- Test runtime ~9% plus rapide (256 mutants en moins par fichier mutate)
- Mais : libcst ne couvrira pas certains mutants regex valides (ex:
  modifications inside string literals qui auraient PU être intentionnelles
  pour fuzzing — peu probable mais possible).

## Recommandation

**MIGRATE-CAREFUL** — D-3 en 2 sous-commits :

### D-3a (~2h) — libcst alongside regex

- Ajouter libcst comme dep optionnelle (`[project.optional-dependencies] dev`)
- `_generate_mutants` détecte si libcst est dispo :
  - Si oui → utilise libcst (default, plus propre)
  - Si non → fallback regex (legacy, comportement actuel inchangé)
- Tests régression : nouveau `test_libcst_mutator_no_invalid_mutants` qui
  vérifie que le mode libcst génère 0 mutants invalid sur un sample
- Body honnête : "regex available as fallback. libcst default when installed.
  Pre-scan showed 8.8% regex mutants are invalid syntax (256/2894)."

### D-3b (~1h, après runtime validation) — regex removal

Avant ce commit, valider `--mutate` runtime sur 2-3 vrais repos
(filelock, attrs, mistune) avec libcst pour confirmer comportement
correct. Si OK, retirer le code regex et la fallback.

### Pourquoi pas D-3 directe (single commit)

À 8.8%, on est dans le bracket MIGRATE-CAREFUL. Direct migration single
commit serait OK techniquement, mais :
- Pas de fallback en cas de bug subtil libcst découvert post-push
- Tu m'as dit "ping moi" si je trouve >5 patterns invalides → 256 c'est
  >>5. Discussion attendue.

### Pourquoi pas STOP-DIALOGUE

Le ratio ne dépasse pas 20%. Pas de "trou de qualité majeur" — c'est
juste le pattern AOR/ROR sur `->` qui domine, et c'est exactement ce
que libcst règle naturellement.

## Données brutes

Pour audit reproductible :
```
$ .venv/bin/python tools/d3_libcst_prescan.py
```

Output complet capturé : voir l'output verbatim de cette commande dans
le commit body de "docs: D-3 pre-scan libcst report".

## Décision attendue de Sky

1. Confirmer recommandation MIGRATE-CAREFUL (D-3a + D-3b)
2. Sinon dialoguer pour D-3 directe ou autre
3. Le tool `tools/d3_libcst_prescan.py` reste ou est supprimé post-décision
