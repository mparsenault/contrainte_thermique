# PDF du relevé à l'enregistrement + config par chantier — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Générer le PDF officiel du relevé au moment de l'enregistrement (moteur IRSST `tac_engine`), le déposer dans SharePoint, et configurer Entrepreneur/Responsable SST par chantier.

**Architecture:** Un nouveau module pur `pdf_releve.py` construit le PDF (reportlab) à partir du dict de `tac_engine.calculer()`. `app.py` bascule son calcul et son affichage sur `tac_engine`, ajoute un panneau de configuration par chantier (écrit dans la liste Projets), et, à l'enregistrement, crée le relevé → génère le PDF → le téléverse dans la bibliothèque « Documents » → met à jour `LienPDF` + `Statut`.

**Tech Stack:** Python 3.9, Streamlit 1.50, Microsoft Graph (requests), reportlab, pytest.

## Global Constraints

- Aucun secret en dur — Graph via `st.secrets["graph"]` (déjà en place). Ne pas committer `.streamlit/secrets.toml`.
- `Authlib==1.3.2` épinglé (ne pas toucher — casse `st.login` au-delà).
- L'app Graph **ne peut pas** créer de listes/colonnes (403) mais peut lire/écrire éléments et téléverser des fichiers. Les colonnes `Entrepreneur` et `ResponsableSST` de la liste Projets sont créées **manuellement** (voir Task 4, prérequis).
- Site cible : `SITE_ID = "elemgroup.sharepoint.com,04f6c13a-680e-4b41-a859-a54a57c2560c,c9267413-b94f-4272-8dde-9e516f5ac910"` (déjà défini dans `app.py`).
- Le moteur `tac_engine.calculer()` est la **seule** source de vérité (TAC, zone, hydratation, pause, recommandations).
- Noms de zone du moteur : `res["zone"]` ∈ {`Verte`, `Vert pale`, `Jaune`, `Rouge`} ; `res["code_zone"]` ∈ {`V`, `VP`, `J1`, `J2`, `J3`, `R`}.
- Mapping entrées app → `calculer` : Ensoleillement `["Soleil direct","Nuageux ou ombre","Intérieur"]`→1/2/3 ; Intensité `["Léger","Moyen","Lourd"]`→1/2/3 ; Source `["Sur place","Service météo"]`→1/2.

---

### Task 1 : Dépendance reportlab

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `reportlab` importable dans l'environnement.

- [ ] **Step 1 : Ajouter la dépendance**

Ajouter à la fin de `requirements.txt` :

```
# Génération du PDF officiel des relevés (Python pur, aucune dépendance système).
reportlab==4.2.5
```

- [ ] **Step 2 : Installer**

Run : `.venv/bin/pip install reportlab==4.2.5`
Expected : `Successfully installed reportlab-4.2.5` (ou déjà satisfait).

- [ ] **Step 3 : Vérifier l'import**

Run : `.venv/bin/python -c "import reportlab; print(reportlab.Version)"`
Expected : affiche `4.2.5`.

- [ ] **Step 4 : Commit**

```bash
git add requirements.txt
git commit -m "build: ajoute reportlab pour la génération du PDF des relevés"
```

---

### Task 2 : Module `pdf_releve.py` (construction du PDF)

**Files:**
- Create: `pdf_releve.py`
- Test: `tests/test_pdf_releve.py`

**Interfaces:**
- Consumes: `tac_engine.calculer()` (dict `res`) et `tac_engine.recommandations(res)`.
- Produces:
  - `initiales(nom: str) -> str` — initiales majuscules des mots (ex. "Marie-Pier Arsenault" → "MPA").
  - `construire_pdf(res: dict, entete: dict) -> bytes` — PDF en mémoire. `entete` a les clés : `entrepreneur, chantier, responsable, date, heure, lieu, initiales`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Create `tests/test_pdf_releve.py` :

```python
import tac_engine
import pdf_releve


def test_initiales():
    assert pdf_releve.initiales("Marie-Pier Arsenault") == "MPA"
    assert pdf_releve.initiales("Jean Tremblay") == "JT"
    assert pdf_releve.initiales("") == ""
    assert pdf_releve.initiales(None) == ""


def _res_exemple():
    return tac_engine.calculer(29, 47, ensoleillement=1, charge=3,
                               combinaison_coton=False, source=1)


def _entete_exemple():
    return {
        "entrepreneur": "Ondel",
        "chantier": "Poste Atwater",
        "responsable": "Marie-Pier Arsenault",
        "date": "2026-07-13",
        "heure": "14:22",
        "lieu": "Aire de coulage Est",
        "initiales": "MPA",
    }


def test_construire_pdf_retourne_des_octets_pdf():
    data = pdf_releve.construire_pdf(_res_exemple(), _entete_exemple())
    assert isinstance(data, (bytes, bytearray))
    assert bytes(data[:5]) == b"%PDF-"
    assert b"%%EOF" in bytes(data[-1024:])
    assert len(data) > 1000


def test_construire_pdf_gere_entete_vide():
    # entrepreneur/responsable non configurés : ne doit pas planter
    entete = _entete_exemple()
    entete["entrepreneur"] = ""
    entete["responsable"] = ""
    entete["initiales"] = ""
    data = pdf_releve.construire_pdf(_res_exemple(), entete)
    assert bytes(data[:5]) == b"%PDF-"
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `.venv/bin/python -m pytest tests/test_pdf_releve.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'pdf_releve'`.

- [ ] **Step 3 : Écrire l'implémentation**

Create `pdf_releve.py` :

```python
"""
Construction du PDF officiel d'un relevé de contrainte thermique (chaleur).
S'appuie sur le dict retourné par tac_engine.calculer(). Aucune écriture disque :
construire_pdf(...) renvoie les octets du PDF.
"""
from __future__ import annotations
import io
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer)

import tac_engine

# Couleur du bandeau selon le code de zone du moteur.
_COULEUR_ZONE = {
    "V":  colors.HexColor("#22c55e"),
    "VP": colors.HexColor("#86efac"),
    "J1": colors.HexColor("#f59e0b"),
    "J2": colors.HexColor("#f59e0b"),
    "J3": colors.HexColor("#f59e0b"),
    "R":  colors.HexColor("#ef4444"),
}
_FONCE = colors.HexColor("#1f2937")
_GRIS = colors.HexColor("#6b7280")
_LIGNE = colors.HexColor("#e5e7eb")


def initiales(nom: str) -> str:
    mots = re.findall(r"[A-Za-zÀ-ÿ]+", nom or "")
    return "".join(m[0] for m in mots).upper()


def _texte_pause(pause) -> str:
    if pause is None:
        return "ARRÊT — rendre les conditions sécuritaires"
    if pause == 0:
        return "travail continu, aucune pause imposée"
    return f"pause {pause} min / heure"


def construire_pdf(res: dict, entete: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Rapport contrainte thermique")
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=styles["Normal"], fontSize=9, leading=13)
    titre = ParagraphStyle("t", parent=styles["Normal"], fontSize=15,
                           textColor=colors.white, fontName="Helvetica-Bold")
    sous = ParagraphStyle("s", parent=styles["Normal"], fontSize=8,
                          textColor=colors.HexColor("#cbd5e1"))
    label = ParagraphStyle("l", parent=styles["Normal"], fontSize=8,
                           textColor=_GRIS, spaceAfter=2)

    story = []

    # Bandeau de titre
    bandeau_titre = Table(
        [[Paragraph("Contrainte thermique — Chaleur", titre)],
         [Paragraph("Outil IRSST (TAC) · Gestion des températures extrêmes", sous)]],
        colWidths=[doc.width])
    bandeau_titre.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _FONCE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    story.append(bandeau_titre)
    story.append(Spacer(1, 8))

    # En-tête (identité)
    lignes_entete = [
        ("Entrepreneur", entete.get("entrepreneur", "")),
        ("Chantier / Projet", entete.get("chantier", "")),
        ("Responsable SST", entete.get("responsable", "")),
        ("Date / Heure", f"{entete.get('date', '')}  {entete.get('heure', '')}"),
        ("Lieu de mesure", entete.get("lieu", "")),
        ("Initiales", entete.get("initiales", "")),
    ]
    t_entete = Table([[Paragraph(k, label), Paragraph(str(v), normal)]
                      for k, v in lignes_entete],
                     colWidths=[doc.width * 0.32, doc.width * 0.68])
    t_entete.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(t_entete)
    story.append(Spacer(1, 10))

    # Bloc TAC + bandeau zone
    couleur = _COULEUR_ZONE.get(res["code_zone"], _GRIS)
    tac_txt = f"{res['tac']:.1f} °C".replace(".", ",")
    zone_txt = f"ZONE {res['zone'].upper()}"
    detail_zone = (f"Hydratation : 1 verre / {res['hydratation_min']} min  ·  "
                   f"Alternance : {_texte_pause(res['pause_min_par_heure'])}")
    bloc = Table([[
        Paragraph(f"<font size=8 color='#6b7280'>TAC</font><br/>"
                  f"<font size=20><b>{tac_txt}</b></font>", normal),
        Paragraph(f"<font size=13 color='white'><b>{zone_txt}</b></font><br/>"
                  f"<font size=8 color='white'>{detail_zone}</font>", normal),
    ]], colWidths=[doc.width * 0.30, doc.width * 0.70])
    bloc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (1, 0), (1, 0), couleur),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(bloc)
    story.append(Spacer(1, 12))

    # Intrants
    i = res["intrants"]
    story.append(Paragraph("INTRANTS", label))
    donnees_intrants = [
        ("Température à l'ombre", f"{i['temp_ombre']} °C"),
        ("Humidité relative", f"{i['humidite']} %"),
        ("Condition d'exposition", i["ensoleillement"]),
        ("Charge de travail", i["charge"]),
        ("Combinaison coton", "Oui" if i["combinaison_coton"] else "Non"),
        ("Source des données", i["source"]),
    ]
    t_intr = Table([[Paragraph(k, normal), Paragraph(str(v), normal)]
                    for k, v in donnees_intrants],
                   colWidths=[doc.width * 0.55, doc.width * 0.45])
    t_intr.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, -1), 0.5, _LIGNE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(t_intr)
    story.append(Spacer(1, 12))

    # Recommandations
    story.append(Paragraph("RECOMMANDATIONS DU JOUR", label))
    for r in tac_engine.recommandations(res):
        story.append(Paragraph(f"• {r}", normal))
        story.append(Spacer(1, 2))

    doc.build(story)
    return buf.getvalue()
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `.venv/bin/python -m pytest tests/test_pdf_releve.py -v`
Expected : 4 tests PASS.

- [ ] **Step 5 : Commit**

```bash
git add pdf_releve.py tests/test_pdf_releve.py
git commit -m "feat: module pdf_releve — construit le PDF officiel du relevé (reportlab)"
```

---

### Task 3 : Basculer app.py sur tac_engine (calcul + affichage)

**Files:**
- Modify: `app.py` (imports ; suppression du calcul simplifié ; bloc de calcul/affichage ; onglet « Mes relevés »)

**Interfaces:**
- Consumes: `tac_engine.calculer(...)`, `pdf_releve.initiales(...)`.
- Produces: variable `res` (dict `tac_engine`) disponible dans l'onglet de saisie pour Task 5.

- [ ] **Step 1 : Ajouter les imports**

Dans `app.py`, remplacer le bloc d'import :

```python
import datetime as dt
import msal
import requests
import streamlit as st
```

par :

```python
import datetime as dt
import msal
import requests
import streamlit as st

import tac_engine
import pdf_releve
```

- [ ] **Step 2 : Supprimer le calcul simplifié**

Supprimer intégralement de `app.py` le bloc `SEUILS_CNESST = {...}` (commentaire inclus) et la section « Calcul de la TAC » (`_HUM`, `corr_humidite`, `corr_soleil`, `calcul_tac`, `zone_de`) — soit, dans la version actuelle, les lignes du commentaire « # Seuils TAC -> zone… » jusqu'à la fin de `zone_de`. Repère de début :

```python
# Seuils TAC -> zone. ILLUSTRATIFS. À REMPLACER par la table officielle CNESST,
```

Repère de fin (dernière ligne à supprimer) :

```python
    return "Zone rouge"
```

- [ ] **Step 3 : Ajouter le mapping des entrées (après la définition de `SOURCES`)**

Juste après la ligne `SOURCES = ["Sur place", "Service météo"]`, ajouter :

```python

def _codes_entrees(ensoleillement: str, intensite: str, source: str):
    """Libellés du formulaire -> codes attendus par tac_engine.calculer()."""
    return (ENSOLEILLEMENTS.index(ensoleillement) + 1,
            INTENSITES.index(intensite) + 1,
            SOURCES.index(source) + 1)
```

- [ ] **Step 4 : Remplacer le bloc calcul + affichage dans l'onglet de saisie**

Remplacer ce bloc :

```python
    # Calcul en direct (Streamlit réexécute le script à chaque interaction)
    tac = calcul_tac(temp, hum, ensoleillement, source, coton)
    zone = zone_de(tac, intensite)
    reco = zones.get(zone, {})

    st.divider()
    m1, m2 = st.columns([1, 2])
    m1.metric("TAC", f"{tac:.1f} °C".replace(".", ","))
    bandeau = {"Zone verte": m2.success, "Zone vert pâle": m2.success,
               "Zone jaune": m2.warning, "Zone rouge": m2.error}.get(zone, m2.info)
    bandeau(f"**{zone}** — {reco.get('Hydration', 'hydratation : voir rapport officiel')}")
    if reco.get("MessageApp"):
        st.caption(reco["MessageApp"])
    st.caption("Guidance provisoire · le PDF officiel de l'IRSST fait foi. "
               "Seuils de zone à valider avec la table CNESST (SST).")
```

par :

```python
    # Calcul officiel via tac_engine (Streamlit réexécute le script à chaque interaction)
    ens_code, charge_code, src_code = _codes_entrees(ensoleillement, intensite, source)
    res = tac_engine.calculer(temp, hum, ens_code, charge_code,
                              combinaison_coton=coton, source=src_code)

    _BANDEAU = {"V": "success", "VP": "success",
                "J1": "warning", "J2": "warning", "J3": "warning", "R": "error"}
    pause = res["pause_min_par_heure"]
    alt = ("ARRÊT" if pause is None else
           "travail continu" if pause == 0 else f"pause {pause} min/h")

    st.divider()
    m1, m2 = st.columns([1, 2])
    m1.metric("TAC", f"{res['tac']:.1f} °C".replace(".", ","))
    afficher = getattr(m2, _BANDEAU.get(res["code_zone"], "info"))
    afficher(f"**Zone {res['zone']}** — hydratation 1 verre / "
             f"{res['hydratation_min']} min · {alt}")
    st.caption("Rapport officiel IRSST généré à l'enregistrement.")
```

- [ ] **Step 5 : Mettre à jour les emojis de l'onglet « Mes relevés »**

Remplacer la ligne :

```python
        c = {"Zone verte": "🟢", "Zone vert pâle": "🟩", "Zone jaune": "🟡", "Zone rouge": "🔴"}.get(r.get("Zone"), "⚪")
```

par :

```python
        c = {"Verte": "🟢", "Vert pale": "🟩", "Jaune": "🟡", "Rouge": "🔴"}.get(r.get("Zone"), "⚪")
```

- [ ] **Step 6 : Retirer la lecture de la liste Zones (désormais inutile)**

Remplacer :

```python
projets = sorted([p.get("Title", "") for p in lire_liste(LISTE_PROJETS, "Title") if p.get("Title")])
zones = {z.get("Title"): z for z in lire_liste(LISTE_ZONES)}   # clé = nom de zone
```

par (temporairement, remplacé en Task 4) :

```python
projets = sorted([p.get("Title", "") for p in lire_liste(LISTE_PROJETS, "Title") if p.get("Title")])
```

- [ ] **Step 7 : Vérifier la syntaxe**

Run : `.venv/bin/python -m py_compile app.py && echo OK`
Expected : `OK`.

- [ ] **Step 8 : Vérifier la cohérence du calcul (sanity check)**

Run :
```bash
.venv/bin/python -c "import tac_engine as t; r=t.calculer(29,47,1,3,combinaison_coton=False,source=1); print(r['tac'], r['zone'], r['code_zone'], r['hydratation_min'], r['pause_min_par_heure'])"
```
Expected : une ligne du type `34.x Jaune J1 20 10` (valeurs numériques cohérentes, pas d'exception).

- [ ] **Step 9 : Commit**

```bash
git add app.py
git commit -m "refactor: app calcule et affiche la TAC via tac_engine (moteur officiel)"
```

---

### Task 4 : Configuration Entrepreneur / Responsable SST par chantier

**Prérequis manuel (à faire AVANT le Step de vérification 6) :** dans SharePoint, liste **Projets**, créer deux colonnes « Une seule ligne de texte » nommées **exactement** (sans espace) `Entrepreneur` et `ResponsableSST`.

**Files:**
- Modify: `app.py` (helpers Graph config ; source du menu déroulant ; panneau « Configurer ce chantier »)

**Interfaces:**
- Consumes: `resoudre_liste`, `_headers` (déjà dans `app.py`).
- Produces:
  - `lire_projets_config() -> dict` : `{nom: {"id", "entrepreneur", "responsable", "compagnie"}}`.
  - `enregistrer_config_chantier(item_id: str, entrepreneur: str, responsable: str) -> None`.
  - variable `cfg` (dict de config du chantier courant) disponible pour Task 5.

- [ ] **Step 1 : Ajouter les helpers Graph de config (après `retirer_favori`)**

Dans `app.py`, après la fonction `retirer_favori(...)`, ajouter :

```python
# ─────────────────────────────── Config par chantier (liste Projets) ───────────────────────────────
@st.cache_data(ttl=300)
def lire_projets_config() -> dict:
    """{nom_chantier: {"id", "entrepreneur", "responsable", "compagnie"}}.
    Lit TOUS les champs (pas de $select) : fonctionne même si les colonnes
    Entrepreneur/ResponsableSST n'existent pas encore (valeurs vides)."""
    lid = resoudre_liste(LISTE_PROJETS)
    out, url = {}, f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items"
    params = {"$expand": "fields", "$top": "999"}
    while url:
        d = requests.get(url, headers=_headers(), params=params).json()
        for it in d.get("value", []):
            f = it.get("fields", {})
            nom = f.get("Title")
            if nom:
                out[nom] = {
                    "id": it["id"],
                    "entrepreneur": f.get("Entrepreneur", "") or "",
                    "responsable": f.get("ResponsableSST", "") or "",
                    "compagnie": f.get("Compagnie", "") or "",
                }
        url = d.get("@odata.nextLink"); params = None
    return out


def enregistrer_config_chantier(item_id: str, entrepreneur: str, responsable: str) -> None:
    lid = resoudre_liste(LISTE_PROJETS)
    r = requests.patch(f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items/{item_id}/fields",
                       headers={**_headers(), "Content-Type": "application/json"},
                       json={"Entrepreneur": entrepreneur, "ResponsableSST": responsable})
    r.raise_for_status()
```

- [ ] **Step 2 : Alimenter le menu déroulant depuis la config**

Remplacer (issu de Task 3, Step 6) :

```python
projets = sorted([p.get("Title", "") for p in lire_liste(LISTE_PROJETS, "Title") if p.get("Title")])
```

par :

```python
projets_cfg = lire_projets_config()
projets = sorted(projets_cfg.keys())
```

- [ ] **Step 3 : Ajouter le panneau « Configurer ce chantier »**

Dans l'onglet de saisie, juste après le bloc `if fav_only and not favoris: st.caption(...)` et **avant** `col1, col2 = st.columns(2)`, ajouter :

```python
    cfg = projets_cfg.get(chantier, {}) if chantier else {}
    if chantier:
        with st.expander("⚙️ Configurer ce chantier"):
            e = st.text_input("Entrepreneur", value=cfg.get("entrepreneur", ""),
                              key="cfg_entrepreneur")
            r = st.text_input("Responsable SST", value=cfg.get("responsable", ""),
                              key="cfg_responsable")
            if st.button("Enregistrer la configuration"):
                if not cfg.get("id"):
                    st.error("Chantier introuvable dans la liste Projets.")
                else:
                    try:
                        enregistrer_config_chantier(cfg["id"], e, r)
                        lire_projets_config.clear()
                        st.success("Configuration enregistrée.")
                        st.rerun()
                    except Exception as ex:
                        st.error("Échec — vérifiez que les colonnes « Entrepreneur » "
                                 f"et « ResponsableSST » existent dans Projets. ({ex})")
```

- [ ] **Step 4 : Vérifier la syntaxe**

Run : `.venv/bin/python -m py_compile app.py && echo OK`
Expected : `OK`.

- [ ] **Step 5 : (Prérequis) Créer les deux colonnes dans SharePoint**

Action manuelle (voir prérequis en tête de tâche). Confirmer la présence des colonnes :

Run :
```bash
.venv/bin/python -c "
import msal, requests, tomllib
cfg=tomllib.load(open('.streamlit/secrets.toml','rb'))['graph'] if False else __import__('toml').load('.streamlit/secrets.toml')['graph']
" 2>/dev/null || echo "utiliser le script de vérification ci-dessous"
```

Utiliser le script de vérification décrit au Step 6 (il liste les colonnes).

- [ ] **Step 6 : Vérifier lecture + écriture de la config contre SharePoint**

Créer un script jetable `scratch_verif_config.py` (hors dépôt, ex. dans un dossier temporaire) :

```python
import toml, msal, requests
g = toml.load(".streamlit/secrets.toml")["graph"]
GRAPH="https://graph.microsoft.com/v1.0"
SITE="elemgroup.sharepoint.com,04f6c13a-680e-4b41-a859-a54a57c2560c,c9267413-b94f-4272-8dde-9e516f5ac910"
tok=msal.ConfidentialClientApplication(g["client_id"],authority=f"https://login.microsoftonline.com/{g['tenant_id']}",client_credential=g["client_secret"]).acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])["access_token"]
H={"Authorization":f"Bearer {tok}"}
# id liste Projets
lid=[l["id"] for l in requests.get(f"{GRAPH}/sites/{SITE}/lists?$select=id,displayName&$top=200",headers=H).json()["value"] if l["displayName"]=="Projets"][0]
# colonnes
cols=[c["name"] for c in requests.get(f"{GRAPH}/sites/{SITE}/lists/{lid}/columns?$select=name",headers=H).json()["value"]]
print("Entrepreneur présent :", "Entrepreneur" in cols, "| ResponsableSST présent :", "ResponsableSST" in cols)
# écrire/relire sur le 1er projet
it=requests.get(f"{GRAPH}/sites/{SITE}/lists/{lid}/items?$expand=fields&$top=1",headers=H).json()["value"][0]
iid=it["id"]; ancien=it["fields"].get("ResponsableSST","")
requests.patch(f"{GRAPH}/sites/{SITE}/lists/{lid}/items/{iid}/fields",headers={**H,"Content-Type":"application/json"},json={"ResponsableSST":"TEST_VERIF"}).raise_for_status()
relu=requests.get(f"{GRAPH}/sites/{SITE}/lists/{lid}/items/{iid}?$expand=fields",headers=H).json()["fields"].get("ResponsableSST")
print("Écrit puis relu :", relu)
requests.patch(f"{GRAPH}/sites/{SITE}/lists/{lid}/items/{iid}/fields",headers={**H,"Content-Type":"application/json"},json={"ResponsableSST":ancien}).raise_for_status()  # restaurer
print("Restauré.")
```

Run : `.venv/bin/python scratch_verif_config.py 2>&1 | grep -v NotOpenSSL`
Expected : `Entrepreneur présent : True | ResponsableSST présent : True`, `Écrit puis relu : TEST_VERIF`, `Restauré.`

- [ ] **Step 7 : Commit**

```bash
git add app.py
git commit -m "feat: configuration Entrepreneur/Responsable SST par chantier (liste Projets)"
```

---

### Task 5 : Génération + dépôt du PDF à l'enregistrement

**Files:**
- Modify: `app.py` (helpers Graph fichiers ; flux d'enregistrement)

**Interfaces:**
- Consumes: `res` (Task 3), `cfg` (Task 4), `pdf_releve.construire_pdf`, `pdf_releve.initiales`, `creer_releve` (retourne l'item créé avec `id`), `resoudre_liste`, `_headers`.
- Produces: relevé créé avec `LienPDF` + `Statut = "Traité"` ; fichier PDF dans « Documents ».

- [ ] **Step 1 : Ajouter les helpers Graph fichiers (après `enregistrer_config_chantier`)**

```python
# ─────────────────────────────── Fichiers (bibliothèque Documents) ───────────────────────────────
@st.cache_data(ttl=300)
def _drive_id() -> str:
    r = requests.get(f"{GRAPH}/sites/{SITE_ID}/drive?$select=id", headers=_headers())
    r.raise_for_status()
    return r.json()["id"]


def _slug_chemin(s: str) -> str:
    """Nettoie un segment de chemin SharePoint (retire les caractères interdits)."""
    for c in '\\/:*?"<>|#%':
        s = s.replace(c, "-")
    return s.strip() or "chantier"


def televerser_pdf(chemin_relatif: str, donnees: bytes) -> str:
    """PUT du PDF dans la bibliothèque Documents. Retourne l'URL web du fichier."""
    from urllib.parse import quote
    did = _drive_id()
    url = f"{GRAPH}/drives/{did}/root:/{quote(chemin_relatif)}:/content"
    r = requests.put(url, headers={**_headers(), "Content-Type": "application/pdf"},
                     data=donnees)
    r.raise_for_status()
    return r.json()["webUrl"]


def maj_releve(item_id: str, fields: dict) -> None:
    lid = resoudre_liste(LISTE_RELEVES)
    r = requests.patch(f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items/{item_id}/fields",
                       headers={**_headers(), "Content-Type": "application/json"}, json=fields)
    r.raise_for_status()
```

- [ ] **Step 2 : Remplacer le flux d'enregistrement**

Remplacer ce bloc :

```python
    if st.button("Enregistrer le relevé", type="primary", disabled=not (chantier and lieu)):
        try:
            creer_releve({
                "Title": f"{chantier} {dt.datetime.now():%Y-%m-%d %H:%M}",
                "Chantier": chantier,
                "Lieu": lieu,
                "DateHeure": dt.datetime.now().isoformat(),
                "Intensite": intensite,
                "TempOmbre": float(temp),
                "Humidite": int(hum),
                "Ensoleillement": ensoleillement,
                "SourceDonnes": source,
                "CombinaisonCoton": bool(coton),
                "Note": note,
                "Statut": "En attente",
                "TAC": round(tac, 1),
                "Zone": zone,
                "SaisiPar": st.user.email,
            })
            lire_liste.clear()   # rafraîchir le cache
            st.success("Relevé enregistré. Le PDF officiel sera généré par le traitement planifié.")
        except Exception as e:
            st.error(f"Échec de l'enregistrement : {e}")
```

par :

```python
    if not cfg.get("entrepreneur") or not cfg.get("responsable"):
        st.info("Astuce : configurez l'entrepreneur et le responsable SST de ce "
                "chantier (⚙️ ci-dessus) pour un PDF complet.")

    if st.button("Enregistrer le relevé", type="primary", disabled=not (chantier and lieu)):
        maintenant = dt.datetime.now()
        # 1. Créer le relevé (En attente)
        try:
            item = creer_releve({
                "Title": f"{chantier} {maintenant:%Y-%m-%d %H:%M}",
                "Chantier": chantier,
                "Lieu": lieu,
                "DateHeure": maintenant.isoformat(),
                "Intensite": intensite,
                "TempOmbre": float(temp),
                "Humidite": int(hum),
                "Ensoleillement": ensoleillement,
                "SourceDonnes": source,
                "CombinaisonCoton": bool(coton),
                "Note": note,
                "Statut": "En attente",
                "TAC": res["tac"],
                "Zone": res["zone"],
                "SaisiPar": st.user.email,
            })
        except Exception as e:
            st.error(f"Échec de l'enregistrement : {e}")
            st.stop()

        # 2. Générer le PDF, le déposer, mettre à jour le relevé
        try:
            entete = {
                "entrepreneur": cfg.get("entrepreneur", ""),
                "chantier": chantier,
                "responsable": cfg.get("responsable", ""),
                "date": maintenant.date().isoformat(),
                "heure": maintenant.strftime("%H:%M"),
                "lieu": lieu,
                "initiales": pdf_releve.initiales(cfg.get("responsable", "")),
            }
            pdf = pdf_releve.construire_pdf(res, entete)
            chemin = (f"Relevés PDF/{_slug_chemin(chantier)}/"
                      f"{maintenant:%Y-%m-%d_%H%M%S}.pdf")
            url = televerser_pdf(chemin, pdf)
            maj_releve(item["id"], {"LienPDF": {"Url": url, "Description": "PDF officiel"},
                                    "Statut": "Traité"})
            lire_liste.clear()
            st.success("Relevé enregistré et PDF officiel généré. "
                       "Retrouvez-le dans « Mes relevés ».")
        except Exception as e:
            lire_liste.clear()
            st.warning("Relevé enregistré, mais le PDF n'a pas pu être généré/déposé "
                       f"(statut « En attente ») : {e}")
```

- [ ] **Step 3 : Vérifier la syntaxe**

Run : `.venv/bin/python -m py_compile app.py && echo OK`
Expected : `OK`.

- [ ] **Step 4 : Vérifier le flux complet contre SharePoint (relevé + PDF + upload + patch)**

Créer un script jetable `scratch_verif_pdf.py` (hors dépôt) :

```python
import toml, msal, requests
from urllib.parse import quote
import tac_engine, pdf_releve
g = toml.load(".streamlit/secrets.toml")["graph"]
GRAPH="https://graph.microsoft.com/v1.0"
SITE="elemgroup.sharepoint.com,04f6c13a-680e-4b41-a859-a54a57c2560c,c9267413-b94f-4272-8dde-9e516f5ac910"
tok=msal.ConfidentialClientApplication(g["client_id"],authority=f"https://login.microsoftonline.com/{g['tenant_id']}",client_credential=g["client_secret"]).acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])["access_token"]
H={"Authorization":f"Bearer {tok}"}; HJ={**H,"Content-Type":"application/json"}
res=tac_engine.calculer(29,47,1,3,combinaison_coton=False,source=1)
pdf=pdf_releve.construire_pdf(res,{"entrepreneur":"Ondel","chantier":"__TEST__","responsable":"Marie-Pier Arsenault","date":"2026-07-13","heure":"14:22","lieu":"Aire Est","initiales":"MPA"})
did=requests.get(f"{GRAPH}/sites/{SITE}/drive?$select=id",headers=H).json()["id"]
up=requests.put(f"{GRAPH}/drives/{did}/root:/{quote('Relevés PDF/__TEST__/verif.pdf')}:/content",headers={**H,"Content-Type":"application/pdf"},data=pdf)
print("upload:",up.status_code,"url:",up.json().get("webUrl"))
# nettoyage
requests.delete(f"{GRAPH}/drives/{did}/items/{up.json()['id']}",headers=H)
print("fichier test supprimé")
```

Run : `.venv/bin/python scratch_verif_pdf.py 2>&1 | grep -v NotOpenSSL`
Expected : `upload: 201 url: https://elemgroup.sharepoint.com/...verif.pdf`, puis `fichier test supprimé`.

- [ ] **Step 5 : Vérification manuelle dans l'app**

Lancer `.venv/bin/streamlit run app.py`, se connecter, choisir un chantier, configurer entrepreneur/responsable, saisir un relevé, cliquer « Enregistrer ». Vérifier : message de succès, puis dans « Mes relevés » le bouton « PDF officiel » ouvre le PDF déposé dans SharePoint.

- [ ] **Step 6 : Commit**

```bash
git add app.py
git commit -m "feat: génère et dépose le PDF officiel du relevé à l'enregistrement"
```

---

## Auto-revue du plan

- **Couverture de la spec :**
  - Moteur unique (spec §1) → Task 3.
  - Config par chantier + colonnes manuelles (spec §2) → Task 4.
  - PDF style B (spec §3) → Task 2.
  - Stockage SharePoint + LienPDF + Statut (spec §4, flux) → Task 5.
  - reportlab (spec module) → Task 1.
  - Cohérence nommage des zones (spec) → Task 3 Steps 4-5.
  - Gestion d'erreur découplée (spec) → Task 5 Step 2.
- **Placeholders :** aucun — chaque step contient le code/commande réels.
- **Cohérence des types :** `res` (dict tac_engine) et `entete` (dict) utilisés de façon identique entre Task 2 et Task 5 ; `cfg` produit en Task 4 consommé en Task 5 ; `creer_releve` retourne l'item (avec `id`) — déjà le cas dans `app.py` actuel.
