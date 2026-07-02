# Conception — Synchronisation BD on-prem → liste SharePoint « Projets »

**Date :** 2026-07-02
**Auteur :** Marie-Pier Arsenault (mparsenault@elem.global)
**Statut :** Approuvé (conception)

## Objectif

Pousser la liste des projets valides de la base SQL Server on-prem `UPRODB` vers
une liste SharePoint Online « Projets », de façon récurrente et sans créer de
doublons. Le module est indépendant de `tac_engine.py`, qui reste un moteur de
calcul pur.

## Décision sur les secrets

À la demande explicite de l'utilisatrice, **les identifiants sont mis en dur**
dans un bloc de configuration en tête du script. Contexte : le script reste sur
un serveur on-prem à accès restreint. (Le risque a été signalé; décision assumée.)
Les valeurs manquantes au moment de la rédaction sont marquées `<< À REMPLIR >>`.

## Architecture

Nouveau module autonome : **`sharepoint_sync.py`**.

Dépendances externes :
- `pyodbc` — lecture SQL Server (via ODBC Driver 17/18 for SQL Server).
- `msal` — obtention du jeton app-only (client credentials) pour Microsoft Graph.
- `requests` — appels REST vers Microsoft Graph.

### Flux d'exécution

```
1. Obtenir un jeton Graph (msal, client credentials, scope .default)
2. Lire les "No Projet" déjà présents dans la liste SharePoint (paginé)
3. Interroger SQL Server → toutes les lignes valides
4. Diff : ne garder que les Project_No absents de la liste
5. POST chaque ligne manquante comme item de liste (mapping ci-dessous)
6. Journaliser : lues / déjà présentes / envoyées / échecs
```

### Stratégie incrémentale — Diff par clé métier (approche A)

- La clé métier est **`Project_No`** (unique côté source, mappé sur la colonne
  texte **No Projet** de la liste).
- À chaque exécution, on lit l'ensemble des `No Projet` existants dans la liste,
  puis on n'envoie que les `Project_No` SQL absents de cet ensemble.
- **Auto-correcteur** : un envoi échoué ou une liste rebâtie se rattrape au
  passage suivant. Aucun fichier d'état local à maintenir.
- `ID_Project` sert uniquement au `ORDER BY` (ordre d'insertion stable).

## Source SQL Server

- Serveur : `SQL2014\UPRODATA`
- Base : `UPRODB`
- Authentification : **login SQL** (utilisateur + mot de passe — `<< À REMPLIR >>`)
- Requête :

```sql
select p.ID_Project, c.Name, p.Project_No, p.Description
from Projects.Projects p
left join Common.Company c on c.ID_Company = p.ID_Company
where p.maestroProjNo <> ''
  and p.Valid = 1
  and c.ID_Company in (1, 7, 5, 2, 4)
order by p.ID_Project
```

## Cible SharePoint Online

- Auth : **App registration Azure AD**, flux client credentials.
  - Tenant ID : `<< À REMPLIR >>`
  - Client ID : `<< À REMPLIR >>`
  - Client Secret : `<< À REMPLIR >>`
  - Permission requise sur l'app : `Sites.ReadWrite.All` (application), consentie
    par un admin.
- Site : `https://elemgroup.sharepoint.com/sites/Contraintesthermiques`
- Liste : **Projets**

### Mapping des colonnes

| Colonne SQL      | Colonne SharePoint (affichage) | Type    |
|------------------|--------------------------------|---------|
| `p.Project_No`   | No Projet                      | Texte   |
| `p.Description`  | Nom                            | Texte   |
| `c.Name`         | Compagnie                      | Choix   |

- Les valeurs de `Compagnie` (les 5 compagnies visées) existent déjà comme choix
  dans la liste → pas de risque d'échec d'insertion sur valeur inconnue.
- Les **noms internes** des colonnes seront résolus au démarrage via Graph
  (`/lists/{id}/columns`) à partir des noms d'affichage, puis utilisés dans le
  corps des `POST`. (Évite de coder en dur des `_x0020_` fragiles.)

## Gestion des erreurs

- **Throttling (HTTP 429 / 503)** : respecter l'en-tête `Retry-After`, réessayer
  avec back-off (max ~5 tentatives par item).
- **Échec d'un item** : journaliser (Project_No + message), continuer les autres,
  ne pas interrompre le lot. Code de sortie non nul si au moins un échec.
- **Erreur d'auth ou de connexion SQL** : échec immédiat avec message clair.
- **Colonne introuvable au mapping** : échec immédiat (mauvaise config de liste).

## Journalisation

Sortie console : nombre de lignes lues en SQL, nombre déjà présentes, nombre
envoyées, nombre d'échecs (avec la liste des `Project_No` en échec).

## Hors périmètre (YAGNI)

- Pas de suppression/désactivation dans SharePoint des projets devenus invalides
  (uniquement ajout des nouveaux). À rediscuter si besoin.
- Pas de mise à jour des items existants (ni `Nom` ni `Compagnie`) — création
  seulement.
- Pas de planification intégrée (cron/Tâche planifiée Windows gérée hors script).

## Tests

- Test unitaire de la fonction de **diff** (ensemble source vs ensemble liste)
  avec données simulées.
- Test unitaire du **mapping** d'une ligne SQL vers le corps JSON d'un item.
- Vérification manuelle de bout en bout une fois les secrets remplis (petit lot).
