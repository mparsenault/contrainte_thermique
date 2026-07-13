# Génération du PDF à l'enregistrement + configuration par chantier — Design

Date : 2026-07-13
Fichiers touchés : `app.py`, nouveau `pdf_releve.py`, `requirements.txt`.
Réutilise : `tac_engine.py` (moteur IRSST officiel, déjà présent).

## Problème

Aujourd'hui, enregistrer un relevé écrit une ligne dans la liste SharePoint
« Relevés » avec `Statut = « En attente »` et promet un PDF « généré par le
traitement planifié » — traitement qui **n'existe pas** dans le dépôt. De plus,
`app.py` calcule la TAC avec une formule **simplifiée** (seuils marqués
« illustratifs »), différente du moteur officiel `tac_engine.py`.

On veut : générer le PDF officiel **au moment de l'enregistrement**, avec le
moteur officiel, et le déposer dans SharePoint.

## Décisions validées

1. **Moteur unique** : `tac_engine.calculer()` (IRSST officiel) pour l'affichage
   ET le PDF. La liste « Zones » n'est plus utilisée pour les recommandations
   (le moteur les fournit via `recommandations()`).
2. **Entrepreneur et Responsable SST configurés par chantier** (pas ressaisis à
   chaque relevé), stockés dans la liste Projets.
3. **Style du PDF** : mis en forme (option B) — en-tête sombre, tableau des
   intrants, bandeau coloré selon la zone, TAC en gros, recommandations.
4. **Stockage** : SharePoint uniquement (bibliothèque « Documents »), puis
   `LienPDF` + `Statut = « Traité »`. Upload de fichier vérifié possible (201).

## Contraintes SharePoint vérifiées

- Écrire/supprimer un **élément** : OK (201/204).
- Téléverser un **fichier** dans « Documents » : OK (201).
- Créer une **liste** : **403**. Créer une **colonne** : **403**.
  → Les colonnes de config doivent être créées manuellement.

## Configuration par chantier

### Colonnes à créer manuellement dans la liste Projets

| Colonne          | Type   | Notes                                  |
|------------------|--------|----------------------------------------|
| `Entrepreneur`   | texte  | nom sans espace                        |
| `ResponsableSST` | texte  | nom sans espace                        |

La sync `sync_projets.py` ne les écrase pas (elle n'écrit que Title, NoProjet,
Compagnie ; son diff ne porte que sur ces clés).

### UI — panneau « Configurer ce chantier »

Sous le menu Chantier (dans l'onglet « Nouveau relevé »), un `st.expander`
« ⚙️ Configurer ce chantier » contenant :

- champ texte **Entrepreneur** (pré-rempli avec la valeur actuelle)
- champ texte **Responsable SST** (pré-rempli avec la valeur actuelle)
- bouton **Enregistrer** → PATCH de la ligne Projets du chantier
  (`Entrepreneur`, `ResponsableSST`), puis vidage de cache + `st.rerun()`.

### Lecture robuste

La lecture des projets récupère **tous** les champs (`$expand=fields` sans
`$select`) et lit `Entrepreneur` / `ResponsableSST` via `.get()`. Ainsi l'app
fonctionne **avant** que les colonnes existent (valeurs vides, aucun plantage).
On conserve l'`id` SharePoint de chaque projet (nécessaire au PATCH de config).

## Module `pdf_releve.py`

- Dépendance : **`reportlab`** (Python pur, `pip install`, aucune dépendance
  système — sûr sur le serveur). Ajout à `requirements.txt`.
- Fonction `construire_pdf(res, entete) -> bytes` : rend le PDF en mémoire à
  partir du dict `res` de `tac_engine.calculer()` et d'un `entete`
  (entrepreneur, chantier, responsable, date, heure, lieu, initiales).
- Mise en page (style B) : bandeau titre sombre ; tableau en-tête ; bloc TAC +
  bandeau zone coloré (V=vert, VP=vert pâle, J*=jaune, R=rouge) ; tableau des
  intrants ; liste des recommandations (`tac_engine.recommandations(res)`).
- Initiales déduites du Responsable SST (initiales des mots).

## Flux à l'enregistrement (`app.py`)

1. `res = tac_engine.calculer(temp, hum, ensoleillement→1/2/3, charge→1/2/3,
   coton, source→1/2)`.
2. `creer_releve({... , "Statut": "En attente", ...})` — champs existants,
   `TAC`/`Zone` issus de `res`.
3. `pdf = pdf_releve.construire_pdf(res, entete)` (entete depuis la config du
   chantier + utilisateur + date/heure).
4. Upload dans `Documents` sous `Relevés PDF/<chantier>/<date>_<heure>.pdf`
   (PUT `/drives/{driveId}/root:/{chemin}:/content`). Récupère `webUrl`.
5. PATCH du relevé : `LienPDF = {"Url": webUrl, "Description": "PDF officiel"}`,
   `Statut = "Traité"`.
6. Message de succès + rappel que le PDF est dans « Mes relevés ».

### Gestion d'erreur

Si l'une des étapes 3-5 échoue, le relevé **reste enregistré** (« En attente »)
et un `st.warning` explique l'échec du PDF. L'écriture du relevé et la
génération du PDF sont découplées : rien n'est perdu.

## Affichage à l'écran

Le bandeau de résultat (TAC, zone, hydratation, alternance travail-repos)
utilise désormais `res` de `tac_engine`, cohérent avec le PDF. Si le chantier
n'a pas d'entrepreneur/responsable configuré, un `st.info` invite à le
configurer (le PDF laissera ces champs vides, sans bloquer).

### Cohérence du nommage des zones

`tac_engine` renvoie `res["zone"]` ∈ {Verte, Vert pale, Jaune, Rouge}, alors que
le code actuel (bandeau + emojis de « Mes relevés ») utilise « Zone verte / Zone
vert pâle / Zone jaune / Zone rouge » et `SEUILS_CNESST`. En passant au moteur,
il faut aligner **une seule** convention :

- Stocker dans la colonne `Zone` la valeur `res["zone"]` (nom du moteur).
- Mettre à jour le mapping emoji de l'onglet « Mes relevés » et le choix de
  couleur du bandeau (`success`/`warning`/`error`) sur les codes/zones du moteur
  (`res["code_zone"]` ∈ {V, VP, J1, J2, J3, R} est le plus fiable pour ça).
- Supprimer l'usage de `SEUILS_CNESST` et des fonctions `corr_humidite`,
  `corr_soleil`, `calcul_tac`, `zone_de` de `app.py` (remplacées par le moteur).

## Hors périmètre

- Logo ELEM dans le PDF (ajout ultérieur si un fichier est fourni).
- Aucun traitement planifié : tout se fait à l'enregistrement.
- Pas de nouvelles colonnes dans la liste « Relevés » (Entrepreneur/Responsable
  vivent dans Projets + figés dans le PDF).
- Filtre « Mes relevés » inchangé.

## Cartographie des entrées app → tac_engine

| Formulaire app                 | Paramètre `calculer`         |
|--------------------------------|------------------------------|
| Température à l'ombre           | `temp_ombre`                 |
| Humidité relative               | `humidite`                   |
| Ensoleillement (Soleil direct / Nuageux-ombre / Intérieur) | `ensoleillement` = 1 / 2 / 3 |
| Intensité (Léger / Moyen / Lourd) | `charge` = 1 / 2 / 3      |
| Source (Sur place / Service météo) | `source` = 1 / 2         |
| Combinaison coton               | `combinaison_coton` (bool)   |
