# SharePoint Sync « Projets » Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pousser les projets valides de la base SQL Server `UPRODB` vers la liste SharePoint Online « Projets », en ajoutant seulement les projets absents (diff par `No Projet`).

**Architecture:** Un module autonome `sharepoint_sync.py`. Un cœur de fonctions **pures** (diff, mapping, chaîne de connexion, retry, agrégation de clés) couvert par des tests unitaires; une couche I/O (SQL via `pyodbc`, Microsoft Graph via `msal` + `requests`) vérifiée manuellement de bout en bout. Config et secrets en dur en tête de fichier (décision assumée).

**Tech Stack:** Python 3.8+, `pyodbc`, `msal`, `requests`, `pytest` (tests).

## Global Constraints

- Python 3.8+ ; module **indépendant** de `tac_engine.py` (ne pas le modifier).
- Secrets **en dur** dans un bloc config en tête de `sharepoint_sync.py` ; valeurs inconnues = `<< À REMPLIR >>`.
- Auth SharePoint : app-only Azure AD (client credentials), Microsoft Graph, permission app `Sites.ReadWrite.All`.
- Auth SQL : login SQL, driver « ODBC Driver 17 for SQL Server ».
- Stratégie : **création seulement** (pas d'update ni de suppression), diff par clé métier `Project_No` → colonne `No Projet`.
- Site : `https://elemgroup.sharepoint.com/sites/Contraintesthermiques` ; liste `Projets`.
- Mapping : `Project_No`→`No Projet` (texte), `Description`→`Nom` (texte), `Name`→`Compagnie` (choix).

> **Note git :** le dossier n'est pas (encore) un dépôt git. Avant la Task 1, exécuter `git init` si l'on veut les commits ; sinon, ignorer les étapes « Commit ». Les tests utilisent `pytest` — l'installer si absent (`pip install pytest pyodbc msal requests`).

---

### Task 1: Scaffolding + config + diff (cœur pur)

**Files:**
- Create: `sharepoint_sync.py`
- Test: `tests/test_sharepoint_sync.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `_norm_key(value) -> str` — normalise une clé (str + strip ; `None`→`""`).
  - `diff_new_projets(sql_rows: list[dict], existing_keys, key_column: str = "Project_No") -> list[dict]` — retourne les lignes dont la clé normalisée est absente de `existing_keys`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_sharepoint_sync.py
from sharepoint_sync import _norm_key, diff_new_projets


def test_norm_key_strips_and_stringifies():
    assert _norm_key("  P-001 ") == "P-001"
    assert _norm_key(1001) == "1001"
    assert _norm_key(None) == ""


def test_diff_returns_only_new_projets():
    sql_rows = [
        {"Project_No": "P-001", "Description": "A", "Name": "Descimco"},
        {"Project_No": "P-002", "Description": "B", "Name": "Talvi"},
        {"Project_No": "P-003", "Description": "C", "Name": "Ondel"},
    ]
    existing = {"P-002"}
    result = diff_new_projets(sql_rows, existing)
    assert [r["Project_No"] for r in result] == ["P-001", "P-003"]


def test_diff_normalizes_both_sides():
    sql_rows = [{"Project_No": 1001, "Description": "A", "Name": "X"}]
    existing = {"1001"}
    assert diff_new_projets(sql_rows, existing) == []
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `python -m pytest tests/test_sharepoint_sync.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'sharepoint_sync'` ou `ImportError`).

- [ ] **Step 3: Créer `sharepoint_sync.py` avec le bloc config et les fonctions pures**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Synchronisation des projets valides (SQL Server UPRODB) vers la liste
SharePoint Online « Projets ». Création seulement, diff par « No Projet ».
Secrets en dur (script sur serveur on-prem a acces restreint).
"""

# ============================================================================
# CONFIGURATION (secrets en dur — a completer)
# ============================================================================
# --- SQL Server ---
SQL_ODBC_DRIVER = "ODBC Driver 17 for SQL Server"
SQL_SERVER = r"SQL2014\UPRODATA"
SQL_DATABASE = "UPRODB"
SQL_USER = "<< À REMPLIR >>"
SQL_PASSWORD = "<< À REMPLIR >>"

# --- Azure AD / Microsoft Graph ---
TENANT_ID = "<< À REMPLIR >>"
CLIENT_ID = "<< À REMPLIR >>"
CLIENT_SECRET = "<< À REMPLIR >>"

# --- SharePoint ---
SP_HOSTNAME = "elemgroup.sharepoint.com"
SP_SITE_PATH = "/sites/Contraintesthermiques"
SP_LIST_NAME = "Projets"

# Mapping colonne SQL -> nom d'affichage de la colonne SharePoint
COLUMN_MAP = {
    "Project_No": "No Projet",
    "Description": "Nom",
    "Name": "Compagnie",
}
KEY_SQL_COLUMN = "Project_No"
KEY_SP_DISPLAY = "No Projet"

SQL_QUERY = """
select p.ID_Project, c.Name, p.Project_No, p.Description
from Projects.Projects p
left join Common.Company c on c.ID_Company = p.ID_Company
where p.maestroProjNo <> ''
  and p.Valid = 1
  and c.ID_Company in (1, 7, 5, 2, 4)
order by p.ID_Project
"""


# ============================================================================
# Coeur pur (testable)
# ============================================================================
def _norm_key(value):
    """Normalise une cle metier : str + strip ; None -> ''."""
    if value is None:
        return ""
    return str(value).strip()


def diff_new_projets(sql_rows, existing_keys, key_column=KEY_SQL_COLUMN):
    """Retourne les lignes SQL dont la cle est absente de existing_keys."""
    existing = {_norm_key(k) for k in existing_keys}
    return [row for row in sql_rows
            if _norm_key(row.get(key_column)) not in existing]
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `python -m pytest tests/test_sharepoint_sync.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add sharepoint_sync.py tests/test_sharepoint_sync.py
git commit -m "feat(sync): scaffolding, config et diff par cle metier"
```

---

### Task 2: Mapping d'une ligne vers le corps d'un item Graph

**Files:**
- Modify: `sharepoint_sync.py`
- Test: `tests/test_sharepoint_sync.py`

**Interfaces:**
- Consumes: `COLUMN_MAP`.
- Produces:
  - `build_item_fields(row: dict, column_map: dict, internal_names: dict) -> dict` — construit `{nom_interne: valeur}` pour le corps `{"fields": ...}` d'un POST Graph. `None`→`""`. Ignore les colonnes SQL absentes de `row`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_sharepoint_sync.py  (ajouter)
from sharepoint_sync import build_item_fields


def test_build_item_fields_maps_to_internal_names():
    row = {"ID_Project": 5, "Project_No": "P-001",
           "Description": "Toiture", "Name": "Descimco"}
    column_map = {"Project_No": "No Projet", "Description": "Nom", "Name": "Compagnie"}
    internal = {"No Projet": "No_x0020_Projet", "Nom": "Nom", "Compagnie": "Compagnie"}
    fields = build_item_fields(row, column_map, internal)
    assert fields == {"No_x0020_Projet": "P-001", "Nom": "Toiture", "Compagnie": "Descimco"}


def test_build_item_fields_none_becomes_empty_string():
    row = {"Project_No": "P-9", "Description": None, "Name": "Talvi"}
    column_map = {"Project_No": "No Projet", "Description": "Nom", "Name": "Compagnie"}
    internal = {"No Projet": "NoProjet", "Nom": "Nom", "Compagnie": "Compagnie"}
    fields = build_item_fields(row, column_map, internal)
    assert fields["Nom"] == ""
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `python -m pytest tests/test_sharepoint_sync.py -k build_item_fields -v`
Expected: FAIL (`ImportError: cannot import name 'build_item_fields'`).

- [ ] **Step 3: Implémenter `build_item_fields`**

```python
# sharepoint_sync.py  (ajouter apres diff_new_projets)
def build_item_fields(row, column_map, internal_names):
    """Construit le dict {nom_interne: valeur} pour le corps 'fields' d'un item."""
    fields = {}
    for sql_col, display_name in column_map.items():
        if sql_col not in row:
            continue
        internal = internal_names[display_name]
        value = row[sql_col]
        fields[internal] = "" if value is None else str(value)
    return fields
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `python -m pytest tests/test_sharepoint_sync.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add sharepoint_sync.py tests/test_sharepoint_sync.py
git commit -m "feat(sync): mapping ligne SQL -> corps d'item Graph"
```

---

### Task 3: Chaîne de connexion SQL + lecture SQL Server

**Files:**
- Modify: `sharepoint_sync.py`
- Test: `tests/test_sharepoint_sync.py`

**Interfaces:**
- Consumes: `SQL_*` config, `SQL_QUERY`.
- Produces:
  - `build_sql_conn_str(driver, server, database, user, password) -> str` — chaîne ODBC (pure, testable).
  - `fetch_sql_rows() -> list[dict]` — exécute `SQL_QUERY`, retourne une liste de dicts (clés = noms de colonnes SQL). I/O, vérif manuelle.

- [ ] **Step 1: Écrire le test qui échoue (chaîne de connexion)**

```python
# tests/test_sharepoint_sync.py  (ajouter)
from sharepoint_sync import build_sql_conn_str


def test_build_sql_conn_str_contains_all_parts():
    s = build_sql_conn_str("ODBC Driver 17 for SQL Server",
                            r"SQL2014\UPRODATA", "UPRODB", "user", "pw")
    assert "DRIVER={ODBC Driver 17 for SQL Server}" in s
    assert r"SERVER=SQL2014\UPRODATA" in s
    assert "DATABASE=UPRODB" in s
    assert "UID=user" in s
    assert "PWD=pw" in s
    assert "TrustServerCertificate=yes" in s
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `python -m pytest tests/test_sharepoint_sync.py -k conn_str -v`
Expected: FAIL (`ImportError: cannot import name 'build_sql_conn_str'`).

- [ ] **Step 3: Implémenter la chaîne de connexion et le lecteur SQL**

```python
# sharepoint_sync.py  (ajouter en haut des imports)
import sys
import time
import pyodbc
import requests
import msal


# sharepoint_sync.py  (section SQL)
def build_sql_conn_str(driver, server, database, user, password):
    """Construit la chaine de connexion ODBC pour SQL Server (login SQL)."""
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"TrustServerCertificate=yes;"
    )


def fetch_sql_rows():
    """Execute SQL_QUERY et retourne une liste de dicts (cle = nom de colonne)."""
    conn_str = build_sql_conn_str(SQL_ODBC_DRIVER, SQL_SERVER, SQL_DATABASE,
                                  SQL_USER, SQL_PASSWORD)
    with pyodbc.connect(conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `python -m pytest tests/test_sharepoint_sync.py -v`
Expected: PASS (6 tests). `fetch_sql_rows` n'est pas testé unitairement (I/O — vérif manuelle après remplissage des secrets).

- [ ] **Step 5: Commit**

```bash
git add sharepoint_sync.py tests/test_sharepoint_sync.py
git commit -m "feat(sync): chaine de connexion et lecture SQL Server"
```

---

### Task 4: Jeton Graph + requête HTTP résiliente (retry 429/503)

**Files:**
- Modify: `sharepoint_sync.py`
- Test: `tests/test_sharepoint_sync.py`

**Interfaces:**
- Consumes: `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`.
- Produces:
  - `request_with_retry(do_request, max_attempts=5, sleep=time.sleep) -> response` — appelle `do_request()` (callable sans argument retournant un objet à `.status_code`/`.headers`) ; réessaie sur 429/503 en respectant `Retry-After` ; retourne la dernière réponse. Pure/injectable.
  - `get_graph_token() -> str` — jeton app-only via `msal`. I/O, vérif manuelle.
  - `GRAPH = "https://graph.microsoft.com/v1.0"` (constante).

- [ ] **Step 1: Écrire les tests qui échouent (retry)**

```python
# tests/test_sharepoint_sync.py  (ajouter)
from sharepoint_sync import request_with_retry


class _FakeResp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


def test_retry_respects_retry_after_then_succeeds():
    seq = iter([_FakeResp(429, {"Retry-After": "2"}), _FakeResp(200)])
    slept = []
    resp = request_with_retry(lambda: next(seq), sleep=slept.append)
    assert resp.status_code == 200
    assert slept == [2]


def test_retry_returns_immediately_on_success():
    slept = []
    resp = request_with_retry(lambda: _FakeResp(201), sleep=slept.append)
    assert resp.status_code == 201
    assert slept == []


def test_retry_stops_after_max_attempts():
    slept = []
    resp = request_with_retry(lambda: _FakeResp(503, {"Retry-After": "1"}),
                              max_attempts=3, sleep=slept.append)
    assert resp.status_code == 503
    assert slept == [1, 1]  # 3 essais => 2 attentes
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `python -m pytest tests/test_sharepoint_sync.py -k retry -v`
Expected: FAIL (`ImportError: cannot import name 'request_with_retry'`).

- [ ] **Step 3: Implémenter `request_with_retry` et `get_graph_token`**

```python
# sharepoint_sync.py  (constante, pres du haut)
GRAPH = "https://graph.microsoft.com/v1.0"


# sharepoint_sync.py  (section Graph)
def request_with_retry(do_request, max_attempts=5, sleep=time.sleep):
    """Appelle do_request() ; reessaie sur 429/503 (Retry-After). Retourne la reponse."""
    resp = None
    for attempt in range(1, max_attempts + 1):
        resp = do_request()
        if resp.status_code in (429, 503) and attempt < max_attempts:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            sleep(retry_after)
            continue
        return resp
    return resp


def get_graph_token():
    """Jeton app-only Microsoft Graph via client credentials."""
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(
            f"Echec d'authentification Graph : "
            f"{result.get('error')} - {result.get('error_description')}")
    return result["access_token"]
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `python -m pytest tests/test_sharepoint_sync.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add sharepoint_sync.py tests/test_sharepoint_sync.py
git commit -m "feat(sync): jeton Graph et requete HTTP resiliente"
```

---

### Task 5: Résolution site/liste/colonnes + lecture des clés existantes

**Files:**
- Modify: `sharepoint_sync.py`
- Test: `tests/test_sharepoint_sync.py`

**Interfaces:**
- Consumes: `request_with_retry`, `GRAPH`, `SP_*`, `COLUMN_MAP`, `KEY_SP_DISPLAY`.
- Produces:
  - `collect_existing_keys(pages, key_internal_name) -> set[str]` — agrège les valeurs de clé (normalisées) sur une itérable de pages Graph. Pure/testable.
  - `_get_json(token, url) -> dict` — GET Graph + retry, lève sur non-2xx. I/O.
  - `resolve_site_id(token) -> str`, `resolve_list_id(token, site_id) -> str`. I/O.
  - `resolve_internal_names(token, site_id, list_id, display_names) -> dict` — map affichage→interne. I/O.
  - `fetch_existing_keys(token, site_id, list_id, key_internal_name) -> set[str]` — pagine `/items` et délègue à `collect_existing_keys`. I/O.

- [ ] **Step 1: Écrire le test qui échoue (agrégation de clés)**

```python
# tests/test_sharepoint_sync.py  (ajouter)
from sharepoint_sync import collect_existing_keys


def test_collect_existing_keys_across_pages_normalizes():
    pages = [
        {"value": [{"fields": {"NoProjet": " P-001 "}},
                   {"fields": {"NoProjet": 1002}}]},
        {"value": [{"fields": {"NoProjet": "P-003"}},
                   {"fields": {}}]},  # item sans la cle -> ignore
    ]
    keys = collect_existing_keys(pages, "NoProjet")
    assert keys == {"P-001", "1002", "P-003"}
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `python -m pytest tests/test_sharepoint_sync.py -k collect_existing -v`
Expected: FAIL (`ImportError: cannot import name 'collect_existing_keys'`).

- [ ] **Step 3: Implémenter l'agrégation et les fonctions de résolution I/O**

```python
# sharepoint_sync.py  (section SharePoint)
def collect_existing_keys(pages, key_internal_name):
    """Agrege les valeurs de cle (normalisees) sur une iterable de pages Graph."""
    keys = set()
    for page in pages:
        for item in page.get("value", []):
            val = item.get("fields", {}).get(key_internal_name)
            if val is not None:
                keys.add(_norm_key(val))
    return keys


def _get_json(token, url):
    """GET Graph avec retry ; leve sur reponse non-2xx."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = request_with_retry(lambda: requests.get(url, headers=headers))
    if not (200 <= resp.status_code < 300):
        raise RuntimeError(f"GET {url} -> {resp.status_code} : {resp.text}")
    return resp.json()


def resolve_site_id(token):
    """Resout l'ID du site a partir du hostname + chemin."""
    url = f"{GRAPH}/sites/{SP_HOSTNAME}:{SP_SITE_PATH}"
    return _get_json(token, url)["id"]


def resolve_list_id(token, site_id):
    """Resout l'ID de la liste par son nom d'affichage."""
    url = (f"{GRAPH}/sites/{site_id}/lists"
           f"?$filter=displayName eq '{SP_LIST_NAME}'")
    values = _get_json(token, url).get("value", [])
    if not values:
        raise RuntimeError(f"Liste '{SP_LIST_NAME}' introuvable sur le site.")
    return values[0]["id"]


def resolve_internal_names(token, site_id, list_id, display_names):
    """Map {nom d'affichage: nom interne} pour les colonnes demandees."""
    url = f"{GRAPH}/sites/{site_id}/lists/{list_id}/columns"
    cols = _get_json(token, url).get("value", [])
    by_display = {c.get("displayName"): c.get("name") for c in cols}
    mapping = {}
    for disp in display_names:
        if disp not in by_display:
            raise RuntimeError(f"Colonne '{disp}' introuvable dans la liste.")
        mapping[disp] = by_display[disp]
    return mapping


def fetch_existing_keys(token, site_id, list_id, key_internal_name):
    """Pagine les items de la liste et retourne l'ensemble des cles existantes."""
    def pages():
        url = (f"{GRAPH}/sites/{site_id}/lists/{list_id}/items"
               f"?$expand=fields($select={key_internal_name})&$top=2000")
        while url:
            data = _get_json(token, url)
            yield data
            url = data.get("@odata.nextLink")
    return collect_existing_keys(pages(), key_internal_name)
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `python -m pytest tests/test_sharepoint_sync.py -v`
Expected: PASS (10 tests). Les fonctions I/O (`resolve_*`, `fetch_existing_keys`) sont vérifiées manuellement après remplissage des secrets.

- [ ] **Step 5: Commit**

```bash
git add sharepoint_sync.py tests/test_sharepoint_sync.py
git commit -m "feat(sync): resolution site/liste/colonnes et lecture des cles existantes"
```

---

### Task 6: Création d'items + orchestration `main()`

**Files:**
- Modify: `sharepoint_sync.py`
- Test: vérification manuelle de bout en bout.

**Interfaces:**
- Consumes: toutes les fonctions précédentes.
- Produces:
  - `create_item(token, site_id, list_id, fields) -> bool` — POST un item (retry), retourne succès/échec. I/O.
  - `main() -> int` — orchestration ; retourne un code de sortie (0 = ok, 1 = au moins un échec). I/O.

- [ ] **Step 1: Implémenter `create_item` et `main`**

```python
# sharepoint_sync.py  (section SharePoint)
def create_item(token, site_id, list_id, fields):
    """POST un nouvel item de liste. Retourne True si cree, False sinon."""
    url = f"{GRAPH}/sites/{site_id}/lists/{list_id}/items"
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    resp = request_with_retry(
        lambda: requests.post(url, headers=headers, json={"fields": fields}))
    if 200 <= resp.status_code < 300:
        return True
    print(f"    ECHEC POST -> {resp.status_code} : {resp.text}")
    return False


def main():
    print("== Synchronisation Projets -> SharePoint ==")
    token = get_graph_token()
    site_id = resolve_site_id(token)
    list_id = resolve_list_id(token, site_id)
    internal_names = resolve_internal_names(
        token, site_id, list_id, COLUMN_MAP.values())
    key_internal = internal_names[KEY_SP_DISPLAY]

    existing = fetch_existing_keys(token, site_id, list_id, key_internal)
    print(f"Cles deja presentes dans la liste : {len(existing)}")

    rows = fetch_sql_rows()
    print(f"Lignes lues en SQL              : {len(rows)}")

    a_envoyer = diff_new_projets(rows, existing)
    print(f"Nouveaux projets a envoyer      : {len(a_envoyer)}")

    envoyes, echecs = 0, []
    for row in a_envoyer:
        fields = build_item_fields(row, COLUMN_MAP, internal_names)
        no_projet = _norm_key(row.get(KEY_SQL_COLUMN))
        if create_item(token, site_id, list_id, fields):
            envoyes += 1
        else:
            echecs.append(no_projet)

    print(f"Envoyes : {envoyes} | Echecs : {len(echecs)}")
    if echecs:
        print("Projets en echec : " + ", ".join(echecs))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Régression — les tests unitaires passent toujours**

Run: `python -m pytest tests/test_sharepoint_sync.py -v`
Expected: PASS (10 tests, inchangés).

- [ ] **Step 3: Vérification syntaxique / import**

Run: `python -c "import sharepoint_sync"`
Expected: aucune erreur (imports `pyodbc`/`msal`/`requests` résolus ; sinon `pip install pyodbc msal requests`).

- [ ] **Step 4: Vérification manuelle de bout en bout (après remplissage des secrets)**

1. Remplir les 5 `<< À REMPLIR >>` (SQL_USER, SQL_PASSWORD, TENANT_ID, CLIENT_ID, CLIENT_SECRET).
2. Sur une liste **de test** (ou avec un petit lot), lancer : `python sharepoint_sync.py`
3. Vérifier la sortie : nombre de clés existantes, lignes SQL, nouveaux envoyés, échecs.
4. Vérifier dans SharePoint que les items « No Projet / Nom / Compagnie » apparaissent correctement.
5. Relancer immédiatement : « Nouveaux projets a envoyer : 0 » (preuve du diff anti-doublon).

- [ ] **Step 5: Commit**

```bash
git add sharepoint_sync.py
git commit -m "feat(sync): creation d'items et orchestration main"
```

---

## Self-Review

**Spec coverage :**
- Module autonome + config en dur → Task 1. ✅
- Lecture SQL Server (login SQL, requête exacte) → Task 3. ✅
- Auth Graph app-only → Task 4. ✅
- Diff par `No Projet` (approche A, auto-correcteur, sans état local) → Task 1 + Task 5 + `main` (Task 6). ✅
- Résolution des noms internes de colonnes → Task 5. ✅
- Mapping des 3 colonnes → Task 2 + `main`. ✅
- Throttling 429/503 avec `Retry-After` → Task 4. ✅
- Échec par item non bloquant + code de sortie → Task 6. ✅
- Journalisation (lues/présentes/envoyées/échecs) → Task 6. ✅
- Hors périmètre (pas d'update/suppression) → respecté (création seulement). ✅
- Tests : diff + mapping (+ retry + pagination en bonus) → Tasks 1,2,4,5. ✅

**Placeholder scan :** les seuls `<< À REMPLIR >>` sont les secrets, volontaires et documentés. Aucun TODO/TBD dans le code.

**Type consistency :** noms de fonctions et signatures cohérents entre tâches (`diff_new_projets`, `build_item_fields`, `request_with_retry`, `collect_existing_keys`, `resolve_*`, `fetch_existing_keys`, `create_item`, `main`). `KEY_SP_DISPLAY` utilisé de façon cohérente (Task 1 config → Task 6 `main`).
