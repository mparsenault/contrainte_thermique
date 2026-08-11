import base64
import tac_engine
import pdf_releve

# PNG 1×1 valide (pixel unique) pour tester l'insertion d'un logo sans dépendance.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


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


def test_echapper_neutralise_les_chevrons():
    assert pdf_releve._echapper("Poste Atwater <Est>") == "Poste Atwater &lt;Est&gt;"
    assert pdf_releve._echapper(None) == ""


def test_slug_compagnie():
    assert pdf_releve._slug_compagnie("Ondel") == "ondel"
    assert pdf_releve._slug_compagnie("Industro-tech") == "industro-tech"
    assert pdf_releve._slug_compagnie("  Quantech  ") == "quantech"
    assert pdf_releve._slug_compagnie("") == ""
    assert pdf_releve._slug_compagnie(None) == ""


def test_chemin_logo(tmp_path):
    # fichier présent -> chemin ; absent / vide -> None
    (tmp_path / "ondel.png").write_bytes(_PNG_1x1)
    assert pdf_releve.chemin_logo("Ondel", dossier=tmp_path) == str(tmp_path / "ondel.png")
    assert pdf_releve.chemin_logo("Inconnue", dossier=tmp_path) is None
    assert pdf_releve.chemin_logo("", dossier=tmp_path) is None
    assert pdf_releve.chemin_logo(None, dossier=tmp_path) is None


def test_construire_pdf_avec_logo_octets():
    data = pdf_releve.construire_pdf(_res_exemple(), _entete_exemple(), logo=_PNG_1x1)
    assert bytes(data[:5]) == b"%PDF-"
    assert b"%%EOF" in bytes(data[-1024:])


def test_construire_pdf_logo_introuvable_ne_plante_pas():
    # chemin bidon : la bande logo est simplement omise, pas d'exception
    data = pdf_releve.construire_pdf(_res_exemple(), _entete_exemple(),
                                     logo="/inexistant/pas_un_logo.png")
    assert bytes(data[:5]) == b"%PDF-"


def test_construire_pdf_avec_pied_de_page():
    entete = _entete_exemple()
    entete["genere_par"] = "mparsenault@elem.global"
    entete["genere_le"] = "2026-07-14 à 14:03"
    data = pdf_releve.construire_pdf(_res_exemple(), entete)
    assert bytes(data[:5]) == b"%PDF-"
    assert b"%%EOF" in bytes(data[-1024:])


def test_construire_pdf_sans_genere_par_pas_de_pied():
    # entête sans genere_par : pas de pied de page, pas d'erreur
    data = pdf_releve.construire_pdf(_res_exemple(), _entete_exemple())
    assert bytes(data[:5]) == b"%PDF-"


def _lignes_exemple():
    return [
        {"date": "2026-07-13 09:10", "lieu": "Aire de coulage Est", "temp": 27.0,
         "hum": 55, "tac": 28.4, "zone": "Verte", "saisi_par": "a@elem.global"},
        {"date": "2026-07-13 13:45", "lieu": "Toiture", "temp": 31.5,
         "hum": 60, "tac": 34.1, "zone": "Rouge", "saisi_par": "b@elem.global"},
    ]


def test_construire_pdf_rapport_retourne_des_octets_pdf():
    entete = {"entrepreneur": "Ondel", "chantier": "1234 · Poste Atwater",
              "responsable": "Marie-Pier Arsenault",
              "periode": "2026-07-13 09:10 au 2026-07-13 13:45",
              "genere_par": "mparsenault@elem.global",
              "genere_le": "2026-08-11 à 10:00"}
    data = pdf_releve.construire_pdf_rapport(entete, _lignes_exemple())
    assert isinstance(data, (bytes, bytearray))
    assert bytes(data[:5]) == b"%PDF-"
    assert b"%%EOF" in bytes(data[-1024:])


def test_construire_pdf_rapport_champs_manquants_ne_plante_pas():
    # Vieux relevés : température/humidité/TAC absents, zone inconnue.
    lignes = [{"date": "", "lieu": "", "temp": None, "hum": None,
               "tac": None, "zone": "", "saisi_par": ""}]
    data = pdf_releve.construire_pdf_rapport({}, lignes)
    assert bytes(data[:5]) == b"%PDF-"


def test_construire_pdf_rapport_avec_logo_octets():
    data = pdf_releve.construire_pdf_rapport({}, _lignes_exemple(), logo=_PNG_1x1)
    assert bytes(data[:5]) == b"%PDF-"
