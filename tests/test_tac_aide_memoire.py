"""Vérifie que tac_engine reproduit l'aide-mémoire IRSST « travail à la chaleur »
pour TOUTE la plage de TAC (25 paliers × 3 intensités) : pauses et hydratation.

Référence transcrite depuis l'aide-mémoire officiel :
  - Vert / vert pâle        -> travail continu (0 min)
  - Jaune (J1, J2, J3)      -> pause 10 min / heure
  - Rouge                   -> pause 15 min / heure  (le rouge affiche « 15 min », pas « arrêt »)
  - Eau : 1 verre / 20 min, puis / 15 min, puis / 10 min selon la TAC.

Chaque ligne : (TAC, pause_léger, pause_moyen, pause_lourd, eau_min).
Valeurs littérales lues sur la table — volontairement PAS calculées depuis le moteur."""
import tac_engine as t

# TAC, pause min/h (léger, moyen, lourd), hydratation (min entre 2 verres)
AIDE_MEMOIRE = [
    (30.4,  0,  0,  0, 20),
    (31.0,  0,  0,  0, 20),
    (31.6,  0,  0,  0, 20),
    (32.2,  0,  0,  0, 20),
    (32.8,  0,  0,  0, 20),
    (33.3,  0,  0,  0, 20),
    (33.9,  0,  0,  0, 20),
    (34.5,  0,  0,  0, 20),
    (35.0,  0,  0,  0, 20),
    (35.6,  0,  0,  0, 20),
    (36.1,  0,  0, 10, 20),
    (36.7,  0,  0, 10, 20),
    (37.2,  0,  0, 10, 20),
    (37.8,  0, 10, 10, 20),
    (38.3,  0, 10, 10, 20),
    (38.9,  0, 10, 10, 20),
    (39.5,  0, 10, 10, 15),
    (40.0,  0, 10, 10, 15),
    (40.6,  0, 10, 10, 15),
    (41.1, 10, 10, 15, 15),
    (41.7, 10, 10, 15, 10),
    (42.2, 10, 15, 15, 10),
    (42.8, 10, 15, 15, 10),
    (43.3, 10, 15, 15, 10),
    (43.9, 15, 15, 15, 10),
]

CHARGE = {"leger": 1, "moyen": 2, "lourd": 3}


def _res(tac, intensite):
    # temp_ombre=tac, HR<20 (corr 0), intérieur (corr 0), source sur place (corr 0)
    # => TAC calculée == tac (au dixième), sans autre correction.
    return t.calculer(tac, 0, ensoleillement=3, charge=CHARGE[intensite],
                      combinaison_coton=False, source=1)


def test_tac_calculee_egale_au_palier():
    # garantit que nos intrants reproduisent bien chaque palier de TAC
    for tac, *_ in AIDE_MEMOIRE:
        assert _res(tac, "leger")["tac"] == tac


def test_pauses_correspondent_a_l_aide_memoire():
    ecarts = []
    for tac, p_leger, p_moyen, p_lourd, _ in AIDE_MEMOIRE:
        attendu = {"leger": p_leger, "moyen": p_moyen, "lourd": p_lourd}
        for intensite, att in attendu.items():
            obtenu = _res(tac, intensite)["pause_min_par_heure"]
            if obtenu != att:
                ecarts.append(f"TAC {tac} {intensite}: moteur={obtenu} attendu={att}")
    assert not ecarts, "Écarts de pause :\n" + "\n".join(ecarts)


def test_hydratation_correspond_a_l_aide_memoire():
    ecarts = []
    for tac, *_, eau in AIDE_MEMOIRE:
        obtenu = _res(tac, "leger")["hydratation_min"]
        if obtenu != eau:
            ecarts.append(f"TAC {tac}: moteur={obtenu} attendu={eau}")
    assert not ecarts, "Écarts d'hydratation :\n" + "\n".join(ecarts)


def test_balayage_fin_toutes_temperatures():
    """Balaye la T° au dixième sur toute la plage utile, pour les 3 intensités :
    aucune exception, valeurs dans le domaine, et pauses/hydratation MONOTONES
    (jamais moins de pause ni moins d'eau quand la TAC monte)."""
    for intensite in ("leger", "moyen", "lourd"):
        pause_prec, eau_prec = -1, 999
        temp = 250  # 25,0 °C en dixièmes, pour éviter l'arithmétique flottante
        while temp <= 480:  # jusqu'à 48,0 °C
            r = _res(temp / 10, intensite)
            pause = r["pause_min_par_heure"] or 0
            eau = r["hydratation_min"]
            assert pause in (0, 10, 15), f"pause hors domaine {pause} à {temp/10} {intensite}"
            assert eau in (10, 15, 20), f"eau hors domaine {eau} à {temp/10} {intensite}"
            assert pause >= pause_prec, f"pause NON monotone à {temp/10} {intensite}"
            assert eau <= eau_prec, f"eau NON monotone à {temp/10} {intensite}"
            pause_prec, eau_prec = pause, eau
            temp += 1
