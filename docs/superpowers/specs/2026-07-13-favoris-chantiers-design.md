# Favoris de chantiers (par utilisateur) — Design

Date : 2026-07-13
Fichier touché : `app.py`

## Problème

Le menu « Chantier » liste 154 projets. L'utilisateur doit chercher son chantier
à chaque relevé. On veut pouvoir épingler des chantiers en favoris pour les
retrouver rapidement.

## Décisions (validées)

- **Portée** : favoris **par utilisateur** (liés à `st.user.email`).
- **Affichage** : bascule « ⭐ Mes favoris seulement » au-dessus du menu Chantier.
- **Gestion** : bouton étoile contextuel sous le menu (Ajouter / Retirer).

## Stockage — liste SharePoint « Favoris »

Une ligne = un couple *utilisateur + chantier*.

| Colonne     | Type          | Contenu                    |
|-------------|---------------|----------------------------|
| `Title`     | texte (défaut)| nom du chantier            |
| `UserEmail` | texte (à créer)| courriel ELEM du propriétaire |

- **Création manuelle** : l'app Graph a le droit d'écrire des *éléments* mais PAS
  de créer une *liste* (vérifié : POST `/sites/{id}/lists` → **403 Forbidden**,
  POST/DELETE d'un élément → 201/204 OK). La liste « Favoris » doit donc être
  créée une fois dans SharePoint (liste + colonne texte nommée exactement
  `UserEmail`). Si elle est absente, l'app affiche un message clair et retombe
  sur la liste complète des chantiers (dégradation gracieuse, aucun plantage).

## Fonctions (dans `app.py`)

- `_assurer_liste_favoris() -> str` : id de la liste, la crée si absente.
- `lire_favoris(email) -> dict` : `{nom_chantier: item_id}` pour l'utilisateur
  (on garde l'`id` SharePoint, requis pour la suppression). Cache court.
- `ajouter_favori(chantier, email)` : POST d'une ligne.
- `retirer_favori(item_id)` : DELETE de la ligne.
- Après mutation : `lire_favoris.clear()` puis `st.rerun()`.

## Interface (onglet « Nouveau relevé »)

```
⭐ Mes favoris seulement   [toggle]     (défaut : ON si l'utilisateur a des favoris)

Chantier
▾ <options = favoris si bascule ON, sinon les 154 projets>

[ ⭐ Ajouter aux favoris ]   ← si le chantier sélectionné n'est pas favori
[ ☆ Retirer des favoris  ]   ← s'il l'est déjà
```

- Bascule ON mais aucun favori → message : « Aucun favori — décochez la bascule
  pour voir tous les chantiers et en ajouter ».
- Si les favoris sont indisponibles (erreur Graph) → avertissement, on retombe
  sur la liste complète.

## Hors périmètre

- Le filtre « Filtrer par chantier » de l'onglet « Mes relevés » reste sur la
  liste complète (inchangé).
- Pas de favoris partagés / d'équipe.
