# Recherche de chantier par numéro et description — Design

**Date :** 2026-07-13
**Portée :** `app.py` uniquement.

## Problème

Le menu « Chantier » de l'app n'affiche que le `Title` de la liste SharePoint
**Projets** (la description du projet). La recherche intégrée du `st.selectbox`
ne filtre donc que sur la description. Les utilisateurs veulent aussi retrouver
un chantier par son **numéro de projet** (`NoProjet`, ex. `08914`).

## Données (liste Projets)

- `Title` — description du projet (ex. `#39 53 14 C27 - Construction du poste … Chabanel`).
- `NoProjet` — numéro de projet (ex. `08914`). Peut être vide sur certains items.
- `Compagnie`, `Entrepreneur`, `ResponsableSST` — déjà lus par `lire_projets_config()`.

## Solution

Rendre le **libellé affiché** des menus « Chantier » de la forme
`{NoProjet} · {Title}`. La recherche native de `st.selectbox` filtre sur le
texte affiché : taper `08914` ou `Chabanel` filtrera alors la liste.

### Changements dans `app.py`

1. **`lire_projets_config()`** — ajouter la clé `"no"` au dict de chaque
   chantier : `"no": f.get("NoProjet", "") or ""`.

2. **Helper local `libelle_chantier(nom: str) -> str`** — retourne
   `f"{no} · {nom}"` si un numéro existe dans `projets_cfg`, sinon `nom`
   (dégrade proprement quand `NoProjet` est vide ou le nom inconnu).

3. **Tri des options** — `projets` trié par `(no, nom)` (ordre naturel « par
   numéro de projet », puis description). Remplace le tri alphabétique par
   description.

4. **Onglet « Nouveau relevé »** — le `st.selectbox("Chantier", options, …)`
   reçoit `format_func=libelle_chantier`.

5. **Onglet « Mes relevés »** — le `st.selectbox("Filtrer par chantier",
   ["(tous)"] + projets, …)` reçoit
   `format_func=lambda n: "(tous)" if n == "(tous)" else libelle_chantier(n)`.

### Invariant clé (aucun impact en aval)

La **valeur** retournée par les deux menus reste le `Title` du chantier. Toutes
les clés en aval sont inchangées : favoris (`{Title: id}`), config
(`projets_cfg[Title]`), champ `Chantier` du relevé, filtre des relevés.
`format_func` n'affecte que l'affichage, pas la valeur sélectionnée.

## Vérification

- `py_compile app.py` → OK.
- Contrôle visuel dans l'app : le menu affiche `no · description`, la recherche
  filtre par numéro **et** par description, la sélection enregistre toujours le
  bon chantier (favori, config, relevé).

Pas de test unitaire : `app.py` exécute l'UI Streamlit dès l'import (page config,
`st.user`…), donc ses helpers ne sont pas testables en isolation — cohérent avec
la vérification des tâches PDF précédentes (py_compile + contrôle live).

## Hors-scope (YAGNI)

- Champ de recherche texte séparé.
- Recherche par `Compagnie` ou par entrepreneur.
- Mise en cache/pagination supplémentaire (déjà couvertes par `lire_projets_config`).
