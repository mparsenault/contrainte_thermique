#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moteur de calcul des contraintes thermiques (CHALEUR) - IRSST / CNESST.
Logique extraite du code source officiel du calculateur IRSST (calcul-tac.ctrl.js)
et du Programme de gestion des temperatures extremes (AKT rev5, 2026).

Usage CLI / import :
    from tac_engine import calculer, generer_rapport, enregistrer_rapport

Aucune dependance externe. Python 3.8+.
"""
import json
import math
import datetime
import os
import unicodedata

# ----------------------------------------------------------------------------
# Table officielle IRSST (25 paliers). Pour une TAC donnee, on prend le 1er
# palier dont TemperatureCorrigee >= TAC (sinon palier 1 si <=30.4, ou 25 si >=43.9).
# Codes zone : V=vert, VP=vert pale, J1/J2/J3=jaune (croissant), R=rouge.
# EauConsigne = frequence d'hydratation en minutes.
# ----------------------------------------------------------------------------
TABLE = [
    (30.4, "V",  "V",  "V",  20),
    (31.0, "V",  "V",  "V",  20),
    (31.6, "V",  "V",  "VP", 20),
    (32.2, "V",  "V",  "VP", 20),
    (32.8, "V",  "V",  "VP", 20),
    (33.3, "V",  "V",  "VP", 20),
    (33.9, "V",  "V",  "VP", 20),
    (34.5, "V",  "V",  "VP", 20),
    (35.0, "V",  "VP", "VP", 20),
    (35.6, "V",  "VP", "VP", 20),
    (36.1, "V",  "VP", "J1", 20),
    (36.7, "V",  "VP", "J1", 20),
    (37.2, "V",  "VP", "J1", 20),
    (37.8, "VP", "J1", "J2", 20),
    (38.3, "VP", "J1", "J2", 20),
    (38.9, "VP", "J2", "J3", 20),
    (39.5, "VP", "J2", "J3", 15),
    (40.0, "VP", "J3", "J3", 15),
    (40.6, "VP", "J3", "J3", 15),
    (41.1, "J1", "J3", "R",  15),
    (41.7, "J2", "J3", "R",  10),
    (42.2, "J2", "R",  "R",  10),
    (42.8, "J3", "R",  "R",  10),
    (43.3, "J3", "R",  "R",  10),
    (43.9, "R",  "R",  "R",  10),
]

ZONE_NOM = {
    "V":  "Verte",
    "VP": "Vert pale",
    "J1": "Jaune", "J2": "Jaune", "J3": "Jaune",
    "R":  "Rouge",
}

# Regle travail-repos (par heure de travail) - aide-memoire IRSST « travail a la
# chaleur ». La table officielle ne montre que deux durees de pause :
#   Zone jaune (J1/J2/J3) -> 10 min / heure
#   Zone rouge (R)        -> 15 min / heure  (le rouge affiche « 15 min », pas « arret »)
# La mise en garde « rendre les conditions securitaires » en zone rouge reste
# portee par recommandations() et le drapeau danger_extreme (TAC >= 43,9).
PAUSE_MIN = {
    "V":  0,
    "VP": 0,
    "J1": 10,
    "J2": 10,
    "J3": 10,
    "R":  15,
}

ENSOLEILLEMENT = {
    1: ("Exposition directe au soleil", 4.5, 6.0),
    2: ("Ciel nuageux ou a l'ombre",    2.0, 3.5),
    3: ("A l'interieur, sans source de chaleur radiante", 0.0, 0.0),
}
CHARGE = {1: "Leger (< 250 Kcal/h)", 2: "Moyen (250-350 Kcal/h)", 3: "Lourd (> 350 Kcal/h)"}
SOURCE = {1: "Mesurees sur les lieux de travail", 2: "Service meteo regional"}


def correction_humidite(hr):
    if hr < 20:
        return 0.0
    return (0.0000026144 * hr**3) - (0.0011066 * hr**2) + (0.2506 * hr) - 6.6021


def calculer(temp_ombre, humidite, ensoleillement, charge,
             combinaison_coton=False, source=1):
    """
    temp_ombre   : float, T a l'ombre en degres C
    humidite     : float, HR en %
    ensoleillement: 1=soleil direct, 2=nuageux/ombre, 3=interieur
    charge       : 1=leger, 2=moyen, 3=lourd
    combinaison_coton : bool
    source       : 1=mesure sur place, 2=service meteo
    Retourne un dict complet.
    """
    temp_ombre = float(temp_ombre)
    humidite = float(humidite)
    ensoleillement = int(ensoleillement)
    charge = int(charge)
    source = int(source)

    c_hum = correction_humidite(humidite)
    _, sol_place, sol_meteo = ENSOLEILLEMENT[ensoleillement]
    c_sol = sol_meteo if source == 2 else sol_place
    c_comb = 4.4 if combinaison_coton else 0.0
    c_src = 1.5 if source == 2 else 0.0

    tac = temp_ombre + c_hum + c_sol + c_comb + c_src
    tac = round(tac * 10) / 10  # arrondi 0.1 comme IRSST

    # selection du palier
    if tac <= TABLE[0][0]:
        row = TABLE[0]
    elif tac >= TABLE[-1][0]:
        row = TABLE[-1]
    else:
        row = TABLE[-1]
        for i in range(1, len(TABLE)):
            if TABLE[i - 1][0] < tac <= TABLE[i][0]:
                row = TABLE[i]
                break

    seuil, code_l, code_m, code_lo, eau = row
    code = {1: code_l, 2: code_m, 3: code_lo}[charge]
    zone = ZONE_NOM[code]
    pause = PAUSE_MIN[code]

    danger = tac >= 43.9
    attention_humidite = (temp_ombre >= 34 and humidite >= 70)
    attention_air = (ensoleillement == 1)

    return {
        "intrants": {
            "temp_ombre": temp_ombre,
            "humidite": humidite,
            "ensoleillement": ENSOLEILLEMENT[ensoleillement][0],
            "charge": CHARGE[charge],
            "combinaison_coton": combinaison_coton,
            "source": SOURCE[source],
        },
        "corrections": {
            "humidite": round(c_hum, 2),
            "ensoleillement": c_sol,
            "combinaison": c_comb,
            "source": c_src,
        },
        "tac": tac,
        "code_zone": code,
        "zone": zone,
        "hydratation_min": eau,
        "pause_min_par_heure": pause,
        "danger_extreme": danger,
        "attention_humidite": attention_humidite,
        "attention_manque_air": attention_air,
    }


def recommandations(res):
    """Liste de recommandations du jour selon la zone."""
    z = res["code_zone"]
    eau = res["hydratation_min"]
    pause = res["pause_min_par_heure"]
    recs = []
    recs.append(f"Hydratation : 1 verre d'eau fraiche (250 mL) toutes les {eau} minutes, meme sans soif. Ne jamais depasser 1,5 L/h.")
    recs.append("Vetements legers, clairs, en coton. Se couvrir la tete a l'exterieur.")
    recs.append("Travailler en equipe; eviter le travail isole.")
    recs.append("Cesser le travail aux premiers symptomes (etourdissements, vertiges, fatigue inhabituelle) et prevenir le secouriste/superviseur.")

    if z == "V":
        recs.insert(0, "ZONE VERTE - Risque faible. Precautions de base et surveillance.")
        recs.append("Reevaluer le risque plusieurs fois par jour.")
    elif z == "VP":
        recs.insert(0, "ZONE VERT PALE - Risque plus grand. Attention aux travailleurs NON acclimates (5 jours d'acclimatation).")
        recs.append("Resserrer la surveillance; ajuster le rythme; reporter les taches ardues non essentielles a une periode plus fraiche.")
        recs.append("Determiner des mesures temporaires avec l'employeur.")
    elif z in ("J1", "J2", "J3"):
        recs.insert(0, f"ZONE JAUNE - Risque eleve. PAUSE de {pause} min CHAQUE HEURE (a l'ombre/au frais; ecourtable si prise au frais).")
        recs.append("Travail plus leger; zones de repos ombragees/climatisees; rotation des taches; aides mecaniques; ventilation.")
        recs.append("Interdiction de travailler seul. Augmenter la duree des pauses si la TAC monte.")
    elif z == "R":
        recs.insert(0, "ZONE ROUGE - Risque TRES eleve. Rendre IMMEDIATEMENT les conditions securitaires AVANT de poursuivre.")
        recs.append("Appliquer toutes les mesures (travail plus leger, ombrage, ventilation, rotation) puis REEVALUER : le risque doit revenir en zone verte (sans pause) ou jaune (avec pause horaire).")

    if res["danger_extreme"]:
        recs.append("DANGER : TAC >= 43,9 C. Conditions extremes - arret des travaux non essentiels.")
    if res["attention_humidite"]:
        recs.append("Attention : T >= 34 C ET HR >= 70 % - risque sous-estime.")
    if res["attention_manque_air"]:
        recs.append("Attention : travail au soleil - risque sous-estime s'il n'y a pas de circulation d'air.")
    return recs


def generer_rapport(res, entete):
    """Genere le texte du rapport. entete = dict (entrepreneur, chantier, responsable, date, heure, lieu, initiales)."""
    L = []
    L.append("=" * 64)
    L.append("  RAPPORT - CONTRAINTE THERMIQUE (CHALEUR)")
    L.append("  Outil IRSST (TAC) + Programme gestion temperatures extremes")
    L.append("=" * 64)
    L.append(f"Entrepreneur     : {entete.get('entrepreneur','')}")
    L.append(f"Chantier/Projet  : {entete.get('chantier','')}")
    L.append(f"Responsable SST  : {entete.get('responsable','')}")
    L.append(f"Date / Heure     : {entete.get('date','')}  {entete.get('heure','')}")
    L.append(f"Lieu de mesure   : {entete.get('lieu','')}")
    L.append(f"Initiales        : {entete.get('initiales','')}")
    L.append("-" * 64)
    i = res["intrants"]
    L.append("INTRANTS")
    L.append(f"  Temp. a l'ombre        : {i['temp_ombre']} C")
    L.append(f"  Humidite relative      : {i['humidite']} %")
    L.append(f"  Condition d'exposition : {i['ensoleillement']}")
    L.append(f"  Charge de travail      : {i['charge']}")
    L.append(f"  Combinaison coton      : {'Oui' if i['combinaison_coton'] else 'Non'}")
    L.append(f"  Source des donnees     : {i['source']}")
    L.append("-" * 64)
    L.append("RESULTAT")
    L.append(f"  Temp. de l'air corrigee (TAC) : {res['tac']} C")
    L.append(f"  Zone de risque                : {res['zone']}  [{res['code_zone']}]")
    L.append(f"  Hydratation                   : 1 verre / {res['hydratation_min']} min")
    pause = res["pause_min_par_heure"]
    if pause is None:
        L.append(f"  Alternance travail-repos      : ARRET - rendre les conditions securitaires")
    elif pause == 0:
        L.append(f"  Alternance travail-repos      : travail continu, aucune pause imposee")
    else:
        L.append(f"  Alternance travail-repos      : pause {pause} min / heure")
    L.append("-" * 64)
    L.append("RECOMMANDATIONS DU JOUR")
    for r in recommandations(res):
        L.append(f"  - {r}")
    L.append("=" * 64)
    L.append(f"Genere le {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(L)


def _slug(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in s).strip("_") or "chantier"


def enregistrer_rapport(texte, entete, dossier_base=None):
    """Enregistre le rapport. Retourne le chemin absolu."""
    if dossier_base is None:
        dossier_base = os.path.expanduser("~/Documents/Registres_contraintes_thermiques")
    chantier = _slug(entete.get("chantier", "chantier"))
    d = os.path.join(dossier_base, chantier)
    os.makedirs(d, exist_ok=True)
    date = entete.get("date") or datetime.date.today().isoformat()
    heure = (entete.get("heure") or datetime.datetime.now().strftime("%H%M")).replace(":", "")
    nom = f"{_slug(date)}_{_slug(heure)}_TAC.txt"
    chemin = os.path.join(d, nom)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(texte)
    return chemin


def ajouter_au_registre_csv(res, entete, dossier_base=None):
    """Ajoute une ligne au registre CSV cumulatif du chantier. Retourne le chemin."""
    import csv
    if dossier_base is None:
        dossier_base = os.path.expanduser("~/Documents/Registres_contraintes_thermiques")
    chantier = _slug(entete.get("chantier", "chantier"))
    d = os.path.join(dossier_base, chantier)
    os.makedirs(d, exist_ok=True)
    chemin = os.path.join(d, f"registre_{chantier}.csv")
    existe = os.path.exists(chemin)
    pause = res["pause_min_par_heure"]
    pause_txt = "ARRET" if pause is None else ("continu" if pause == 0 else f"{pause} min/h")
    with open(chemin, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if not existe:
            w.writerow(["Date", "Heure", "Lieu", "Intensite", "Temp_ombre_C",
                        "HR_%", "TAC_C", "Zone", "Hydratation_min",
                        "Travail_repos", "Mesures", "Initiales"])
        w.writerow([
            entete.get("date", ""), entete.get("heure", ""), entete.get("lieu", ""),
            res["intrants"]["charge"], res["intrants"]["temp_ombre"],
            res["intrants"]["humidite"], res["tac"], res["zone"],
            res["hydratation_min"], pause_txt,
            entete.get("mesures", ""), entete.get("initiales", ""),
        ])
    return chemin


if __name__ == "__main__":
    import sys
    # mode test rapide
    r = calculer(28, 60, ensoleillement=1, charge=2, combinaison_coton=False, source=1)
    print(json.dumps(r, indent=2, ensure_ascii=False))
