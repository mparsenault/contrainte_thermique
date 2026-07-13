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
