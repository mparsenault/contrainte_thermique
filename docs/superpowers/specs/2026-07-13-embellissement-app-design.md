# Embellissement de l'app Contrainte thermique — Design

**Date :** 2026-07-13
**Périmètre :** apparence uniquement (« épuré & pro », accent bleu ardoise). Aucune logique de calcul, aucun appel Graph, aucune donnée modifiée.

## Objectif

Rendre l'app Streamlit `app.py` plus soignée et professionnelle sans changer son comportement. Look épuré, un accent unique (bleu ardoise), neutres à légère teinte froide, support clair/sombre.

## Contraintes (non négociables)

- **Aucune modification** des fonctions de calcul (`corr_humidite`, `corr_soleil`, `calcul_tac`, `zone_de`) ni des appels Microsoft Graph / SharePoint.
- **Aucune donnée** de relevé, favori ou référence modifiée.
- Les **couleurs de zone** (vert / vert pâle / jaune / rouge) gardent leur sens sémantique — l'accent ne les remplace pas.
- **Zéro nouvelle dépendance** Python. `requirements.txt` inchangé.
- Streamlit reste épinglé (`streamlit==1.50.0`, `Authlib==1.3.2`).

## Palette

Accent bleu ardoise, neutres froids. Valeurs de référence :

| Rôle | Clair | Sombre |
|------|-------|--------|
| Accent (primaryColor) | `#34506b` | `#34506b` |
| Fond (background) | `#f4f6f8` | `#10151b` |
| Surface (secondaryBackground) | `#ffffff` | `#1a2129` |
| Texte | `#1c2530` | `#e6ebf1` |
| Gris / muted | `#64707e` | `#94a1b0` |
| Bordure | `#dde2e8` | `#303b47` |

Les couleurs de zone restent celles déjà utilisées via `st.success` / `st.warning` / `st.error` (composants natifs Streamlit) — non touchées.

## Composants du design

### 1. Thème `.streamlit/config.toml` (nouveau fichier)

Bloc `[theme]` :
- `primaryColor = "#34506b"`
- `backgroundColor`, `secondaryBackgroundColor`, `textColor` selon la palette (mode clair par défaut ; le mode sombre reste géré nativement par Streamlit selon la préférence du système/navigateur).
- `baseRadius` = coins arrondis doux (valeur type `"0.6rem"` ou l'option supportée par 1.50).
- `font` = police sans-serif propre parmi celles supportées nativement par Streamlit (pas de webfont externe).

Streamlit applique automatiquement ce thème à tous les widgets. Le fichier `secrets.toml` existant dans `.streamlit/` n'est pas touché.

**Dépendance :** aucune. **Interface :** fichier de config lu par Streamlit au démarrage.

### 2. CSS léger injecté dans `app.py`

Un seul bloc `st.markdown("<style>…</style>", unsafe_allow_html=True)`, appelé une fois après `st.set_page_config`, idéalement extrait dans une petite fonction `_injecter_style()` pour garder le corps du script lisible.

Portée du CSS (cosmétique uniquement, via classes Streamlit stables + `[data-testid]`) :
- **En-tête** : titre + sous-titre resserrés, marge haute réduite ; masquage discret du menu hamburger et du footer « Made with Streamlit » par défaut.
- **Cartes de relevés** (`st.container(border=True)` de l'onglet « Mes relevés ») : ombre douce, coins arrondis cohérents avec `baseRadius`, meilleur rythme vertical.
- **Onglets** : un peu plus d'air (padding).
- **Bloc TAC** : la valeur de `st.metric` rendue plus grande / plus lisible.

Le CSS doit rester **défensif** : cibler des sélecteurs cosmétiques, et ne jamais dépendre du fonctionnement (pas de masquage d'éléments interactifs, pas de repositionnement fragile). Si un sélecteur Streamlit ne matche pas, l'app reste pleinement fonctionnelle — seul l'effet visuel est absent.

**Dépendance :** `st.markdown`. **Interface :** fonction `_injecter_style()` sans effet de bord sur les données.

### 3. Petites retouches de mise en page dans `app.py`

- Sous-titre / en-tête : formulation soignée sous le titre principal.
- Alignement et espacement autour de la métrique TAC et du bandeau de zone (`st.divider`, colonnes) peaufinés.
- Légendes (`st.caption`) harmonisées.

Ces retouches réordonnent/ajustent des appels d'affichage existants ; elles n'ajoutent ni logique ni appel réseau.

## Ce qui NE change PAS

- Toute la section calcul TAC.
- Toute la section Microsoft Graph (lecture/écriture listes, favoris).
- Le flux d'authentification `st.login` / `st.logout`.
- La structure des données écrites dans SharePoint (`creer_releve`).
- `requirements.txt`, `sync_projets.py`, `tac_engine.py`.

## Vérification

Comme il s'agit d'apparence :
1. `streamlit run app.py` démarre sans erreur.
2. L'app se charge (écran de connexion visible), les onglets s'affichent, le thème bleu ardoise est appliqué, aucun `Traceback`.
3. Vérification visuelle rapide en clair et en sombre.

Aucun test unitaire n'est requis (pas de logique modifiée) ; on ne casse aucun test existant.

## Risques

- **Sélecteurs CSS Streamlit fragiles** : les classes internes peuvent changer entre versions. Mitigation : rester sur des `[data-testid]` documentés et garder le CSS purement cosmétique et optionnel.
- **Thème config.toml** : certaines clés (`baseRadius`, `font`) dépendent de la version. Mitigation : n'utiliser que les clés supportées par Streamlit 1.50 ; vérifier au lancement.
