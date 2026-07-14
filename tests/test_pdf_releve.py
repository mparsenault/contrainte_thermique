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
