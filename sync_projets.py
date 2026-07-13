"""
Synchronisation des projets : SQL Server (on-prem) → liste SharePoint « Projets »
=================================================================================

Version : ADRESSAGE DIRECT PAR GUID (site + liste) — pas de recherche par nom,
donc plus de dépendance au nom d'affichage ni aux limites de $filter de Graph.
La liste n'a qu'une colonne (Title = nom du projet).
Patron : UPSERT idempotent, clé = nom du projet. Relançable sans doublon.

Sécurité : AUCUN secret en dur — identifiants via variables d'environnement.
    setx GRAPH_TENANT_ID     "....."   (une fois, puis rouvrir le terminal)
    setx GRAPH_CLIENT_ID     "....."
    setx GRAPH_CLIENT_SECRET "....."

Prérequis :
    pip install msal requests pyodbc

Permissions Graph (application) sur l'app enregistrée :
    - Sites.Selected  (recommandé : rôle 'write' accordé À CE SEUL site)
    - à défaut : Sites.ReadWrite.All

PREMIER LANCEMENT : laisser DRY_RUN = True (simulation, aucune écriture).
Une fois le résultat validé, passer DRY_RUN = False.
"""

from __future__ import annotations
import os, sys, time
import pyodbc, requests, msal

# ─────────────────────────────── CONFIGURATION ───────────────────────────────
DRY_RUN = False   # True = simulation. Passer à False après validation.

# --- SQL Server on-prem ---
SQL_CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=SQL2014\\uprodata;"
    "DATABASE=uprodb;"
    "UID=mparsenault;PWD=Elesep22!"          # ou UID=...;PWD=... via variables d'env
)

# Le nom du projet = la Description. Le reste sert au filtrage.
SQL_QUERY = """
    SELECT c.Name, p.Project_No, p.Description
    FROM Projects.Projects p
    LEFT JOIN Common.Company c ON p.ID_Company = c.ID_Company
    WHERE c.ID_Company IN (1, 2, 4, 5, 7)
      AND p.Valid = 1
      AND p.transfer2Maestro = 1
      AND p.maestroProjNo <> ''
"""
CLE_SQL   = "Description"              # colonne SQL portant le nom du projet

# --- SharePoint / Graph : identifiants EXACTS de l'environnement (adressage direct) ---
# ID de site composite Graph : {hostname},{siteCollectionId},{webId}
SITE_ID    = "elemgroup.sharepoint.com,04f6c13a-680e-4b41-a859-a54a57c2560c,c9267413-b94f-4272-8dde-9e516f5ac910"
SP_LIST_ID = "451af36f-f1ae-4ea1-b9d2-238957526a0a"   # GUID de la liste « Projets »
CLE_SP     = "Title"                   # colonne SharePoint qui reçoit le nom

def _txt(v) -> str:
    """Normalise une valeur SQL en texte (None → chaîne vide)."""
    return "" if v is None else str(v).strip()

def mapper_champs(p: dict) -> dict:
    """Ligne SQL → champs SharePoint (noms internes de colonnes)."""
    return {
        "Title":     _txt(p["Description"]),   # nom du projet
        "NoProjet":  _txt(p["Project_No"]),    # No Projet
        "Compagnie": _txt(p["Name"]),          # Compagnie
    }

# Supprimer (corbeille SharePoint) les projets présents dans SP mais absents de SQL ?
# Par prudence : False = on ne fait que les LISTER. Passer à True pour supprimer.
SUPPRIMER_ABSENTS = False

# Utilitaire : afficher les noms internes des colonnes de la liste, puis quitter.
LISTER_COLONNES = False

GRAPH = "https://graph.microsoft.com/v1.0"
BASE_LISTE  = f"{GRAPH}/sites/{SITE_ID}/lists/{SP_LIST_ID}"
BASE_ITEMS  = f"{BASE_LISTE}/items"


# ─────────────────────────────── Authentification ───────────────────────────────
def obtenir_token() -> str:
    tenant = os.environ["GRAPH_TENANT_ID"]
    app = msal.ConfidentialClientApplication(
        client_id=os.environ["GRAPH_CLIENT_ID"],
        client_credential=os.environ["GRAPH_CLIENT_SECRET"],
        authority=f"https://login.microsoftonline.com/{tenant}",
    )
    res = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in res:
        raise RuntimeError(f"Auth échouée : {res.get('error_description', res)}")
    return res["access_token"]


class Graph:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}"})

    def _req(self, method, url, **kw):
        for _ in range(5):
            r = self.s.request(method, url, **kw)
            if r.status_code == 429:                       # limite de débit
                time.sleep(int(r.headers.get("Retry-After", 5)))
                continue
            r.raise_for_status()
            return r.json() if r.content else {}
        r.raise_for_status()

    def get(self, url, **kw):    return self._req("GET", url, **kw)
    def post(self, url, **kw):   return self._req("POST", url, **kw)
    def patch(self, url, **kw):  return self._req("PATCH", url, **kw)
    def delete(self, url, **kw): return self._req("DELETE", url, **kw)

    def verifier_liste(self):
        """Confirme l'accès à la liste (adressage direct par GUID) et renvoie son nom."""
        d = self.get(f"{BASE_LISTE}?$select=id,displayName")
        return d.get("displayName")

    def colonnes(self):
        return self.get(f"{BASE_LISTE}/columns",
                        params={"$select": "displayName,name,readOnly"}).get("value", [])

    def tous_les_items(self):
        items, url = [], BASE_ITEMS
        params = {"$expand": "fields($select=Title,NoProjet,Compagnie)", "$top": "999"}
        while url:
            d = self.get(url, params=params)
            items.extend(d.get("value", []))
            url = d.get("@odata.nextLink")
            params = None                                   # nextLink porte déjà les params
        return items


# ─────────────────────────────── Lecture SQL ───────────────────────────────
def lire_projets_sql() -> list[dict]:
    with pyodbc.connect(SQL_CONN) as cnx:
        cur = cnx.cursor()
        cur.execute(SQL_QUERY)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ─────────────────────────────── Synchronisation ───────────────────────────────
def main():
    g = Graph(obtenir_token())
    nom_liste = g.verifier_liste()                          # échoue tôt et clairement si ID erroné
    print(f"Liste cible : « {nom_liste} »")

    if LISTER_COLONNES:
        print("Colonnes (affiché → interne) :")
        for c in g.colonnes():
            ro = " [lecture seule]" if c.get("readOnly") else ""
            print(f"  {c['displayName']:<28} → {c['name']}{ro}")
        return

    projets = lire_projets_sql()
    # Index des lignes SQL par nom (clé). En cas de noms identiques, la dernière gagne.
    projets_par_nom = { _txt(p[CLE_SQL]): p for p in projets if p[CLE_SQL] is not None }
    print(f"{len(projets)} projet(s) lus dans SQL ({len(projets_par_nom)} nom(s) unique(s)).")

    # Index des items existants, par nom.
    existants = {}
    for it in g.tous_les_items():
        nom = it.get("fields", {}).get(CLE_SP)
        if nom is not None:
            existants[str(nom).strip()] = it
    print(f"{len(existants)} item(s) déjà dans SharePoint.")

    n_crees = n_maj = n_inchanges = 0
    for nom, p in sorted(projets_par_nom.items()):
        champs = mapper_champs(p)
        if nom in existants:
            actuel = existants[nom].get("fields", {})
            diff = {k: v for k, v in champs.items() if _txt(actuel.get(k)) != v}
            if not diff:
                n_inchanges += 1
                continue
            n_maj += 1
            print(f"  ~ MAJ    {nom}  ({', '.join(diff)})")
            if not DRY_RUN:
                g.patch(f"{BASE_ITEMS}/{existants[nom]['id']}/fields", json=diff)
            continue
        n_crees += 1
        print(f"  + CRÉER  {nom}  [No {champs['NoProjet']} / {champs['Compagnie']}]")
        if not DRY_RUN:
            g.post(BASE_ITEMS, json={"fields": champs})

    # Projets présents dans SP mais absents de SQL.
    absents = [(nom, it) for nom, it in existants.items() if nom not in projets_par_nom]
    n_supprimes = 0
    for nom, it in absents:
        if SUPPRIMER_ABSENTS:
            n_supprimes += 1
            print(f"  x SUPPRIMER {nom} (absent de SQL)")
            if not DRY_RUN:
                g.delete(f"{BASE_ITEMS}/{it['id']}")
        else:
            print(f"  ! ABSENT de SQL (conservé) : {nom}")

    mode = "SIMULATION (aucune écriture)" if DRY_RUN else "APPLIQUÉ"
    print(f"\n[{mode}] créés={n_crees}  maj={n_maj}  inchangés={n_inchanges}  "
          f"absents={len(absents)}  supprimés={n_supprimes}")

if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        sys.exit(f"Variable d'environnement manquante : {e}")