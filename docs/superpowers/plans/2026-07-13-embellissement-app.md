# Embellissement app Contrainte thermique — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre l'app Streamlit `app.py` plus soignée (look épuré & pro, accent bleu ardoise) sans toucher à la logique.

**Architecture :** Trois leviers cosmétiques indépendants — (1) un thème `.streamlit/config.toml` que Streamlit applique à tous les widgets, (2) un bloc CSS injecté une fois via une fonction `_injecter_style()`, (3) de petites retouches de mise en page dans `app.py`. Aucune fonction de calcul ni appel Microsoft Graph n'est modifié.

**Tech Stack :** Python, Streamlit 1.50.0 (épinglé), TOML pour le thème.

## Global Constraints

- **Aucune modification** des fonctions `corr_humidite`, `corr_soleil`, `calcul_tac`, `zone_de`, ni des fonctions Graph (`graph_token`, `resoudre_liste`, `lire_liste`, `creer_releve`, `lire_favoris`, `ajouter_favori`, `retirer_favori`).
- **Aucune donnée** modifiée ; structure du dict passé à `creer_releve` inchangée.
- **Couleurs de zone** (vert / vert pâle / jaune / rouge) inchangées — rendues par `st.success` / `st.warning` / `st.error`.
- **Zéro nouvelle dépendance** ; `requirements.txt` inchangé. Streamlit reste `1.50.0`, Authlib `1.3.2`.
- Ne pas toucher `.streamlit/secrets.toml`, `sync_projets.py`, `tac_engine.py`.
- Accent : `#34506b`. Neutres clairs : fond `#f4f6f8`, surface `#ffffff`, texte `#1c2530`, muted `#64707e`, bordure `#dde2e8`.
- Commandes Python via l'environnement virtuel : `.venv/bin/streamlit`, `.venv/bin/python`.

---

## Smoke check réutilisable

Toutes les tâches utilisent le même contrôle de non-régression (l'écran de connexion s'affiche **avant** tout appel réseau Graph, donc le boot ne dépend pas de SharePoint) :

```bash
# Démarre l'app en tâche de fond, attend, vérifie qu'elle répond en HTTP 200 sans traceback.
.venv/bin/streamlit run app.py --server.headless true --server.port 8599 > /tmp/st_smoke.log 2>&1 &
ST_PID=$!
sleep 6
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8599/
grep -i -E "traceback|error" /tmp/st_smoke.log || echo "no errors in log"
kill $ST_PID
```

Attendu : code `200`, et « no errors in log » (aucun `Traceback`). Les avertissements Streamlit inoffensifs sont tolérés, mais un avertissement `invalid config option` sur une clé de thème doit être corrigé (retirer/renommer la clé fautive).

---

### Task 1 : Thème `.streamlit/config.toml`

**Files:**
- Create: `.streamlit/config.toml`

**Interfaces:**
- Consumes: rien.
- Produces: un thème lu automatiquement par Streamlit au démarrage. Aucune fonction Python.

- [ ] **Step 1 : Créer le fichier de thème**

Créer `.streamlit/config.toml` avec exactement :

```toml
[theme]
primaryColor = "#34506b"
backgroundColor = "#f4f6f8"
secondaryBackgroundColor = "#ffffff"
textColor = "#1c2530"
font = "sans-serif"
baseRadius = "0.6rem"
```

- [ ] **Step 2 : Lancer le smoke check et confirmer l'absence d'avertissement de config**

Exécuter le bloc « Smoke check réutilisable » ci-dessus.
Attendu : `200` + « no errors in log ». **Vérifier en plus** que `/tmp/st_smoke.log` ne contient pas `invalid config option`. Si une clé (`baseRadius` ou `font`) déclenche cet avertissement sur cette version, la retirer du fichier et relancer.

- [ ] **Step 3 : Vérification visuelle**

Ouvrir http://localhost:8599/ dans le navigateur : l'écran de connexion doit apparaître avec le fond clair `#f4f6f8` et le bouton « Se connecter » en bleu ardoise. Basculer le thème système clair/sombre pour confirmer que le sombre reste lisible.

- [ ] **Step 4 : Commit**

```bash
git add .streamlit/config.toml
git commit -m "feat: thème bleu ardoise (config.toml)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2 : Fonction `_injecter_style()` (CSS cosmétique)

**Files:**
- Modify: `app.py` — ajouter la fonction après le bloc `st.set_page_config(...)` (actuellement ligne 179) et l'appeler juste après.

**Interfaces:**
- Consumes: `st` (déjà importé), thème de la Task 1.
- Produces: `_injecter_style() -> None` — injecte un `<style>` une seule fois, sans effet de bord sur les données. Idempotent (peut être rappelé sans dommage).

- [ ] **Step 1 : Ajouter la fonction et l'appel**

Dans `app.py`, juste après la ligne `st.set_page_config(page_title="Contrainte thermique", page_icon="🌡️", layout="centered")`, insérer :

```python
def _injecter_style() -> None:
    """Style cosmétique léger. Purement visuel : si un sélecteur Streamlit
    ne matche pas (changement de version), l'app reste pleinement fonctionnelle."""
    st.markdown(
        """
        <style>
          /* En-tête : masquer le menu et le footer par défaut, resserrer le haut */
          #MainMenu {visibility: hidden;}
          footer {visibility: hidden;}
          [data-testid="stHeader"] {background: transparent;}
          .block-container {padding-top: 2.6rem; padding-bottom: 3rem; max-width: 820px;}

          /* Onglets un peu plus aérés */
          [data-baseweb="tab-list"] {gap: 6px;}
          button[data-baseweb="tab"] {padding-top: 8px; padding-bottom: 8px;}

          /* Cartes de relevés (st.container(border=True)) : ombre douce */
          [data-testid="stVerticalBlockBorderWrapper"] {
              border-radius: 0.7rem;
              box-shadow: 0 1px 2px rgba(28,37,48,.04), 0 6px 20px rgba(28,37,48,.05);
          }

          /* Bloc TAC : valeur plus grande et lisible */
          [data-testid="stMetricValue"] {
              font-size: 2rem;
              font-variant-numeric: tabular-nums;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


_injecter_style()
```

- [ ] **Step 2 : Smoke check**

Exécuter le bloc « Smoke check réutilisable ».
Attendu : `200` + « no errors in log ».

- [ ] **Step 3 : Vérification visuelle**

Sur http://localhost:8599/ : le menu hamburger et le footer « Made with Streamlit » ne doivent plus être visibles ; le haut de page est resserré. (La mise en valeur des cartes et du TAC sera visible après connexion, à confirmer manuellement si un compte est disponible.)

- [ ] **Step 4 : Commit**

```bash
git add app.py
git commit -m "feat: CSS cosmétique léger (_injecter_style)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3 : Retouches d'en-tête et de mise en page

**Files:**
- Modify: `app.py` — bloc de connexion (lignes ~181-185), titre principal (ligne ~196), sous-titre et légendes.

**Interfaces:**
- Consumes: `st`, `_injecter_style` (Task 2).
- Produces: aucun nouveau symbole ; ajustements d'affichage uniquement.

- [ ] **Step 1 : Soigner l'écran de connexion**

Remplacer le bloc actuel :

```python
if not st.user.is_logged_in:
    st.title("Contrainte thermique")
    st.write("Connecte-toi avec ton compte ELEM pour saisir un relevé.")
    st.button("Se connecter", on_click=st.login, args=("microsoft",))
    st.stop()
```

par :

```python
if not st.user.is_logged_in:
    st.title("🌡️ Contrainte thermique")
    st.caption("Suivi de la contrainte thermique (chaleur) sur les chantiers ELEM.")
    st.write("Connectez-vous avec votre compte ELEM pour saisir un relevé.")
    st.button("Se connecter", on_click=st.login, args=("microsoft",), type="primary")
    st.stop()
```

- [ ] **Step 2 : Ajouter un sous-titre sous le titre principal**

Juste après la ligne `st.title("🌡️ Contrainte thermique — chaleur")` (ligne ~196), ajouter :

```python
st.caption("Calcul de la TAC en direct · saisie envoyée dans SharePoint pour génération du PDF officiel.")
```

- [ ] **Step 3 : Smoke check**

Exécuter le bloc « Smoke check réutilisable ».
Attendu : `200` + « no errors in log ». L'écran de connexion doit afficher le titre avec l'icône, le sous-titre en légende, et un bouton « Se connecter » en bleu ardoise (primaire).

- [ ] **Step 4 : Commit**

```bash
git add app.py
git commit -m "feat: en-tête et libellés soignés (connexion + sous-titre)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage :**
- Thème config.toml (accent, neutres, radius, typo) → Task 1. ✓
- CSS léger (en-tête, cartes, onglets, TAC) → Task 2. ✓
- Retouches de mise en page (en-tête, sous-titre, libellés) → Task 3. ✓
- Contraintes « aucune logique / aucune dépendance » → Global Constraints + aucune tâche ne touche les fonctions de calcul/Graph. ✓
- Vérification (boot sans erreur, visuel clair/sombre) → Smoke check partagé + steps visuels. ✓

**Placeholder scan :** aucun TBD/TODO ; tout le CSS, le TOML et le code sont fournis en entier.

**Type consistency :** un seul symbole introduit, `_injecter_style()`, défini et appelé en Task 2, référencé en Interfaces de Task 3. Cohérent.

**Note d'exécution :** les tâches touchant `app.py` (2 et 3) sont séquentielles (même fichier) ; la Task 1 est indépendante.
