"""
Construction du PDF officiel d'un relevé de contrainte thermique (chaleur).
S'appuie sur le dict retourné par tac_engine.calculer(). Aucune écriture disque :
construire_pdf(...) renvoie les octets du PDF.
"""
from __future__ import annotations
import io
import os
import re
import unicodedata
import xml.sax.saxutils as _sax

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer, Image, HRFlowable)

import tac_engine

# Dossier des logos de compagnies, embarqué avec le module.
_DOSSIER_LOGOS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "assets", "logos")

# Couleur du bandeau selon le code de zone du moteur.
_COULEUR_ZONE = {
    "V":  colors.HexColor("#22c55e"),
    "VP": colors.HexColor("#86efac"),
    "J1": colors.HexColor("#f59e0b"),
    "J2": colors.HexColor("#f59e0b"),
    "J3": colors.HexColor("#f59e0b"),
    "R":  colors.HexColor("#ef4444"),
}
_FONCE = colors.HexColor("#1f2937")
_GRIS = colors.HexColor("#6b7280")
_LIGNE = colors.HexColor("#e5e7eb")


def initiales(nom: str) -> str:
    mots = re.findall(r"[A-Za-zÀ-ÿ]+", nom or "")
    return "".join(m[0] for m in mots).upper()


def _echapper(s) -> str:
    """Échappe le texte libre avant insertion dans un Paragraph reportlab."""
    return _sax.escape("" if s is None else str(s))


def _slug_compagnie(nom) -> str:
    """Nom de compagnie -> slug de fichier (minuscules, sans accents).
    Ex. « Industro-tech » -> « industro-tech »."""
    s = unicodedata.normalize("NFKD", (nom or "").strip()).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def chemin_logo(compagnie, dossier=None):
    """Chemin du PNG de logo pour cette compagnie, ou None s'il n'existe pas.
    `dossier` : répertoire des logos (défaut : assets/logos embarqué)."""
    slug = _slug_compagnie(compagnie)
    if not slug:
        return None
    dossier = _DOSSIER_LOGOS if dossier is None else str(dossier)
    chemin = os.path.join(dossier, f"{slug}.png")
    return chemin if os.path.isfile(chemin) else None


def _flowable_logo(logo, largeur_max):
    """Construit l'Image du logo (chemin ou octets), calée à ~14 mm de haut,
    largeur plafonnée à `largeur_max`. Retourne None si illisible."""
    try:
        src = io.BytesIO(logo) if isinstance(logo, (bytes, bytearray)) else logo
        iw, ih = ImageReader(src).getSize()
        if iw <= 0 or ih <= 0:
            return None
        h = 14 * mm
        w = iw * (h / ih)
        if w > largeur_max:              # logo très large : borner par la largeur
            w = largeur_max
            h = ih * (w / iw)
        src2 = io.BytesIO(logo) if isinstance(logo, (bytes, bytearray)) else logo
        img = Image(src2, width=w, height=h)
        img.hAlign = "LEFT"
        return img
    except Exception:
        return None


def _texte_pause(pause) -> str:
    if pause is None:
        return "ARRÊT — rendre les conditions sécuritaires"
    if pause == 0:
        return "travail continu, aucune pause imposée"
    return f"pause {pause} min / heure"


def construire_pdf(res: dict, entete: dict, logo=None) -> bytes:
    """logo : chemin PNG/JPG ou octets d'image. Si fourni et lisible, une bande
    claire avec le logo (aligné à gauche) est ajoutée en tête. Sinon ignorée."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Rapport contrainte thermique")
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=styles["Normal"], fontSize=9, leading=13)
    titre = ParagraphStyle("t", parent=styles["Normal"], fontSize=15,
                           textColor=colors.white, fontName="Helvetica-Bold")
    sous = ParagraphStyle("s", parent=styles["Normal"], fontSize=8,
                          textColor=colors.HexColor("#cbd5e1"))
    label = ParagraphStyle("l", parent=styles["Normal"], fontSize=8,
                           textColor=_GRIS, spaceAfter=2)

    story = []

    # Bande logo compagnie (optionnelle) : logo à gauche + filet fin.
    if logo is not None:
        img = _flowable_logo(logo, doc.width)
        if img is not None:
            story.append(img)
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=0.5, color=_LIGNE,
                                    spaceAfter=8))

    # Bandeau de titre
    bandeau_titre = Table(
        [[Paragraph("Contrainte thermique — Chaleur", titre)],
         [Paragraph("Outil IRSST (TAC) · Gestion des températures extrêmes", sous)]],
        colWidths=[doc.width])
    bandeau_titre.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _FONCE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    story.append(bandeau_titre)
    story.append(Spacer(1, 8))

    # En-tête (identité)
    lignes_entete = [
        ("Entrepreneur", entete.get("entrepreneur", "")),
        ("Chantier / Projet", entete.get("chantier", "")),
        ("Responsable SST", entete.get("responsable", "")),
        ("Date / Heure", f"{entete.get('date', '')}  {entete.get('heure', '')}"),
        ("Lieu de mesure", entete.get("lieu", "")),
        ("Initiales", entete.get("initiales", "")),
    ]
    t_entete = Table([[Paragraph(_echapper(k), label), Paragraph(_echapper(v), normal)]
                      for k, v in lignes_entete],
                     colWidths=[doc.width * 0.32, doc.width * 0.68])
    t_entete.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(t_entete)
    story.append(Spacer(1, 10))

    # Bloc TAC + bandeau zone
    couleur = _COULEUR_ZONE.get(res["code_zone"], _GRIS)
    # Fond clair (V, VP) => texte foncé pour rester lisible ; sinon texte blanc.
    couleur_texte_zone = "#1f2937" if res["code_zone"] in ("V", "VP") else "white"
    tac_txt = _echapper(f"{res['tac']:.1f} °C".replace(".", ","))
    zone_txt = _echapper(f"ZONE {res['zone'].upper()}")
    detail_zone = _echapper(
        f"Hydratation : 1 verre / {res['hydratation_min']} min  ·  "
        f"Alternance : {_texte_pause(res['pause_min_par_heure'])}")
    # Deux paragraphes empilés par cellule (interlignes propres) plutôt qu'un
    # seul <br/> : évite que la grande valeur écrase le label « TAC ».
    tac_lbl = ParagraphStyle("tac_lbl", parent=normal, fontSize=8,
                             textColor=_GRIS, leading=10)
    tac_val = ParagraphStyle("tac_val", parent=normal, fontSize=20,
                             leading=22, fontName="Helvetica-Bold")
    zone_titre = ParagraphStyle("zt", parent=normal, fontSize=13, leading=16)
    zone_detail = ParagraphStyle("zd", parent=normal, fontSize=8, leading=11)
    bloc = Table([[
        [Paragraph("TAC", tac_lbl), Paragraph(tac_txt, tac_val)],
        [Paragraph(f"<font color='{couleur_texte_zone}'><b>{zone_txt}</b></font>", zone_titre),
         Paragraph(f"<font color='{couleur_texte_zone}'>{detail_zone}</font>", zone_detail)],
    ]], colWidths=[doc.width * 0.30, doc.width * 0.70])
    bloc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (1, 0), (1, 0), couleur),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(bloc)
    story.append(Spacer(1, 12))

    # Intrants
    i = res["intrants"]
    story.append(Paragraph("INTRANTS", label))
    donnees_intrants = [
        ("Température à l'ombre", f"{i['temp_ombre']} °C"),
        ("Humidité relative", f"{i['humidite']} %"),
        ("Condition d'exposition", i["ensoleillement"]),
        ("Charge de travail", i["charge"]),
        ("Combinaison coton", "Oui" if i["combinaison_coton"] else "Non"),
        ("Source des données", i["source"]),
    ]
    t_intr = Table([[Paragraph(_echapper(k), normal), Paragraph(_echapper(v), normal)]
                    for k, v in donnees_intrants],
                   colWidths=[doc.width * 0.55, doc.width * 0.45])
    t_intr.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, -1), 0.5, _LIGNE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(t_intr)
    story.append(Spacer(1, 12))

    # Recommandations
    story.append(Paragraph("RECOMMANDATIONS DU JOUR", label))
    for r in tac_engine.recommandations(res):
        story.append(Paragraph(f"• {_echapper(r)}", normal))
        story.append(Spacer(1, 2))

    # Pied de page : qui a généré le document (et quand).
    genere_par = entete.get("genere_par", "")
    if genere_par:
        pied = ParagraphStyle("pied", parent=styles["Normal"], fontSize=7.5,
                              textColor=_GRIS)
        texte = f"Document généré par {_echapper(genere_par)}"
        if entete.get("genere_le"):
            texte += f" le {_echapper(entete['genere_le'])}"
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width="100%", thickness=0.5, color=_LIGNE,
                                spaceAfter=6))
        story.append(Paragraph(texte, pied))

    doc.build(story)
    return buf.getvalue()


# Couleur de zone par libellé stocké dans SharePoint (le rapport sommaire reçoit
# le libellé, pas le code du moteur).
_COULEUR_ZONE_LIBELLE = {
    "Verte": _COULEUR_ZONE["V"],
    "Vert pale": _COULEUR_ZONE["VP"],
    "Jaune": _COULEUR_ZONE["J1"],
    "Rouge": _COULEUR_ZONE["R"],
}


def construire_pdf_rapport(entete: dict, lignes: list, logo=None) -> bytes:
    """Rapport sommaire des relevés d'un chantier : en-tête d'identité, décompte
    par zone, puis tableau chronologique (une ligne par relevé).

    entete : entrepreneur, chantier, responsable, periode, genere_par, genere_le.
    lignes : dicts {date, lieu, temp, hum, tac, zone, saisi_par} — date déjà
             formatée ; temp/hum/tac numériques ou None (affichés « – »).
    logo   : chemin PNG/JPG ou octets d'image (même convention que construire_pdf).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Rapport sommaire — contrainte thermique")
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=styles["Normal"], fontSize=9, leading=13)
    titre = ParagraphStyle("t", parent=styles["Normal"], fontSize=15,
                           textColor=colors.white, fontName="Helvetica-Bold")
    sous = ParagraphStyle("s", parent=styles["Normal"], fontSize=8,
                          textColor=colors.HexColor("#cbd5e1"))
    label = ParagraphStyle("l", parent=styles["Normal"], fontSize=8,
                           textColor=_GRIS, spaceAfter=2)
    cellule = ParagraphStyle("c", parent=styles["Normal"], fontSize=8, leading=10)
    cellule_tete = ParagraphStyle("ct", parent=cellule, textColor=colors.white,
                                  fontName="Helvetica-Bold")

    story = []

    if logo is not None:
        img = _flowable_logo(logo, doc.width)
        if img is not None:
            story.append(img)
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=0.5, color=_LIGNE,
                                    spaceAfter=8))

    bandeau_titre = Table(
        [[Paragraph("Contrainte thermique — Chaleur", titre)],
         [Paragraph("Rapport sommaire des relevés · Outil IRSST (TAC)", sous)]],
        colWidths=[doc.width])
    bandeau_titre.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _FONCE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    story.append(bandeau_titre)
    story.append(Spacer(1, 8))

    lignes_entete = [
        ("Entrepreneur", entete.get("entrepreneur", "")),
        ("Chantier / Projet", entete.get("chantier", "")),
        ("Responsable SST", entete.get("responsable", "")),
        ("Période couverte", entete.get("periode", "")),
        ("Nombre de relevés", str(len(lignes))),
    ]
    t_entete = Table([[Paragraph(_echapper(k), label), Paragraph(_echapper(v), normal)]
                      for k, v in lignes_entete],
                     colWidths=[doc.width * 0.32, doc.width * 0.68])
    t_entete.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(t_entete)
    story.append(Spacer(1, 10))

    # Décompte par zone + TAC max, sur une ligne.
    def _fmt_temp(v):
        if v is None or v == "":
            return "–"
        try:
            return f"{float(v):.1f}".replace(".", ",")
        except (TypeError, ValueError):
            return str(v)

    tacs = [float(l["tac"]) for l in lignes
            if l.get("tac") not in (None, "")]
    morceaux = []
    for z in ("Verte", "Vert pale", "Jaune", "Rouge"):
        n = sum(1 for l in lignes if l.get("zone") == z)
        if n:
            morceaux.append(f"{z} : {n}")
    if tacs:
        morceaux.append(f"TAC max : {_fmt_temp(max(tacs))} °C")
    if morceaux:
        story.append(Paragraph("SOMMAIRE", label))
        story.append(Paragraph(_echapper("  ·  ".join(morceaux)), normal))
        story.append(Spacer(1, 10))

    # Tableau des relevés.
    story.append(Paragraph("RELEVÉS", label))
    tete = ["Date / Heure", "Lieu", "T° ombre", "Hum.", "TAC", "Zone", "Saisi par"]
    donnees = [[Paragraph(_echapper(t), cellule_tete) for t in tete]]
    for l in lignes:
        donnees.append([
            Paragraph(_echapper(l.get("date", "")), cellule),
            Paragraph(_echapper(l.get("lieu", "")), cellule),
            Paragraph(_echapper(f"{_fmt_temp(l.get('temp'))} °C"), cellule),
            Paragraph(_echapper(f"{l.get('hum')} %" if l.get("hum") not in (None, "") else "–"), cellule),
            Paragraph(_echapper(f"{_fmt_temp(l.get('tac'))} °C"), cellule),
            Paragraph(_echapper(l.get("zone", "")), cellule),
            Paragraph(_echapper(l.get("saisi_par", "")), cellule),
        ])
    t = Table(donnees, repeatRows=1,
              colWidths=[doc.width * w for w in
                         (0.16, 0.20, 0.09, 0.08, 0.09, 0.12, 0.26)])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _FONCE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, _LIGNE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    # Pastille de couleur : fond de la cellule « Zone » selon la zone du relevé.
    for i, l in enumerate(lignes, start=1):
        c = _COULEUR_ZONE_LIBELLE.get(l.get("zone"))
        if c is not None:
            style.append(("BACKGROUND", (5, i), (5, i), c))
    t.setStyle(TableStyle(style))
    story.append(t)

    genere_par = entete.get("genere_par", "")
    if genere_par:
        pied = ParagraphStyle("pied", parent=styles["Normal"], fontSize=7.5,
                              textColor=_GRIS)
        texte = f"Document généré par {_echapper(genere_par)}"
        if entete.get("genere_le"):
            texte += f" le {_echapper(entete['genere_le'])}"
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width="100%", thickness=0.5, color=_LIGNE,
                                spaceAfter=6))
        story.append(Paragraph(texte, pied))

    doc.build(story)
    return buf.getvalue()
