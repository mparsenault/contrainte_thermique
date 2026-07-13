"""
Construction du PDF officiel d'un relevé de contrainte thermique (chaleur).
S'appuie sur le dict retourné par tac_engine.calculer(). Aucune écriture disque :
construire_pdf(...) renvoie les octets du PDF.
"""
from __future__ import annotations
import io
import re
import xml.sax.saxutils as _sax

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer)

import tac_engine

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


def _texte_pause(pause) -> str:
    if pause is None:
        return "ARRÊT — rendre les conditions sécuritaires"
    if pause == 0:
        return "travail continu, aucune pause imposée"
    return f"pause {pause} min / heure"


def construire_pdf(res: dict, entete: dict) -> bytes:
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
    bloc = Table([[
        Paragraph(f"<font size=8 color='#6b7280'>TAC</font><br/>"
                  f"<font size=20><b>{tac_txt}</b></font>", normal),
        Paragraph(f"<font size=13 color='{couleur_texte_zone}'><b>{zone_txt}</b></font><br/>"
                  f"<font size=8 color='{couleur_texte_zone}'>{detail_zone}</font>", normal),
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

    doc.build(story)
    return buf.getvalue()
