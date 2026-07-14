"""
App Streamlit — Contrainte thermique (chaleur)
==============================================

Front-end de saisie des relevés de chaleur :
  - Connexion Microsoft Entra via st.login() (OIDC natif, Streamlit >= 1.42)
  - Calcul de la TAC en direct (Python, fidèle à l'Aide-mémoire)
  - Affichage de la zone + recommandations (lues dans la liste SharePoint « Zones »)
  - Écriture du relevé dans la liste SharePoint « Relevés » via Microsoft Graph

Deux couches d'auth distinctes :
  - st.login() : QUI utilise l'app (identité lue dans st.user) — sert au champ « Saisi par ».
  - Jeton applicatif Graph (client credentials) : l'ÉCRITURE dans SharePoint.
    (OIDC authentifie mais n'autorise pas à agir au nom de l'utilisateur.)

Prérequis :
    pip install "streamlit>=1.42" "Authlib>=1.3.2" msal requests
    streamlit run app_contrainte_thermique.py

Secrets (.streamlit/secrets.toml — À AJOUTER AU .gitignore, jamais dans le code) :
    [auth]
    redirect_uri = "http://localhost:8501/oauth2callback"
    cookie_secret = "<chaîne aléatoire forte>"
    client_id = "<APP ENTRA POUR LE LOGIN>"
    client_secret = "<secret>"
    server_metadata_url = "https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration"

    [graph]                      # peut être la MÊME app que le login, avec permission Sites.Selected (write)
    tenant_id = "<tenant>"
    client_id = "<APP POUR GRAPH>"
    client_secret = "<secret>"

Prérequis liste : ajouter une colonne texte « SaisiPar » à la liste Relevés
(l'écriture se fait sous l'identité applicative, pas celle de l'utilisateur).
"""

import datetime as dt
import msal
import requests
import streamlit as st

import tac_engine
import pdf_releve

# ─────────────────────────────── CONFIGURATION ───────────────────────────────
GRAPH = "https://graph.microsoft.com/v1.0"
SITE_ID = "elemgroup.sharepoint.com,04f6c13a-680e-4b41-a859-a54a57c2560c,c9267413-b94f-4272-8dde-9e516f5ac910"

LISTE_PROJETS = "Projets"
LISTE_RELEVES = "Relevés"
LISTE_ZONES   = "Zones"
LISTE_FAVORIS = "Favoris"

INTENSITES     = ["Léger", "Moyen", "Lourd"]
ENSOLEILLEMENTS = ["Soleil direct", "Nuageux ou ombre", "Intérieur"]
SOURCES        = ["Sur place", "Service météo"]


def _codes_entrees(ensoleillement: str, intensite: str, source: str):
    """Libellés du formulaire -> codes attendus par tac_engine.calculer()."""
    return (ENSOLEILLEMENTS.index(ensoleillement) + 1,
            INTENSITES.index(intensite) + 1,
            SOURCES.index(source) + 1)


def _res_depuis_releve(r: dict):
    """Recalcule le dict tac_engine à partir des intrants stockés d'un relevé.
    Peut lever (label inconnu / champ manquant) : à intercepter par l'appelant."""
    ens, charge, src = _codes_entrees(r["Ensoleillement"], r["Intensite"],
                                      r["SourceDonnes"])
    return tac_engine.calculer(float(r["TempOmbre"]), float(r["Humidite"]),
                               ens, charge,
                               combinaison_coton=bool(r.get("CombinaisonCoton")),
                               source=src)

# ─────────────────────────────── Microsoft Graph (écriture) ───────────────────────────────
@st.cache_resource
def _msal_app():
    g = st.secrets["graph"]
    return msal.ConfidentialClientApplication(
        client_id=g["client_id"],
        client_credential=g["client_secret"],
        authority=f"https://login.microsoftonline.com/{g['tenant_id']}",
    )

def graph_token() -> str:
    res = _msal_app().acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in res:
        raise RuntimeError(res.get("error_description", "Auth Graph échouée"))
    return res["access_token"]

def _headers():
    return {"Authorization": f"Bearer {graph_token()}"}

@st.cache_data(ttl=300)
def resoudre_liste(nom: str) -> str:
    url = f"{GRAPH}/sites/{SITE_ID}/lists?$select=id,displayName,name&$top=200"
    while url:
        d = requests.get(url, headers=_headers()).json()
        for l in d.get("value", []):
            if nom in (l["displayName"], l["name"]):
                return l["id"]
        url = d.get("@odata.nextLink")
    raise RuntimeError(f"Liste {nom!r} introuvable.")

@st.cache_data(ttl=300)
def lire_liste(nom: str, select: str = "") -> list[dict]:
    lid = resoudre_liste(nom)
    items, url = [], f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items"
    params = {"$expand": f"fields{('($select=' + select + ')') if select else ''}", "$top": "999"}
    while url:
        d = requests.get(url, headers=_headers(), params=params).json()
        for it in d.get("value", []):
            f = it.get("fields", {})
            f["_item_id"] = it.get("id")   # id de l'élément (requis pour patcher)
            items.append(f)
        url = d.get("@odata.nextLink"); params = None
    return items

def creer_releve(fields: dict):
    lid = resoudre_liste(LISTE_RELEVES)
    r = requests.post(f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items",
                      headers={**_headers(), "Content-Type": "application/json"},
                      json={"fields": fields})
    r.raise_for_status()
    return r.json()

# ─────────────────────────────── Favoris (par utilisateur) ───────────────────────────────
def _id_liste_favoris() -> str:
    """id de la liste « Favoris ». Elle doit exister (créée manuellement dans SharePoint :
    liste « Favoris » + colonne texte nommée exactement « UserEmail »)."""
    try:
        return resoudre_liste(LISTE_FAVORIS)
    except RuntimeError:
        raise RuntimeError("liste « Favoris » absente — créez-la dans SharePoint "
                           "avec une colonne texte « UserEmail ».")

@st.cache_data(ttl=60)
def lire_favoris(email: str) -> dict:
    """{nom_chantier: item_id} des favoris de l'utilisateur (id requis pour supprimer)."""
    lid = _id_liste_favoris()
    cible = (email or "").strip().lower()
    out, url = {}, f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items"
    params = {"$expand": "fields($select=Title,UserEmail)", "$top": "999"}
    while url:
        d = requests.get(url, headers=_headers(), params=params).json()
        for it in d.get("value", []):
            f = it.get("fields", {})
            if (f.get("UserEmail") or "").strip().lower() == cible and f.get("Title"):
                out[f["Title"]] = it["id"]
        url = d.get("@odata.nextLink"); params = None
    return out

def ajouter_favori(chantier: str, email: str):
    lid = _id_liste_favoris()
    r = requests.post(f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items",
                      headers={**_headers(), "Content-Type": "application/json"},
                      json={"fields": {"Title": chantier, "UserEmail": email}})
    r.raise_for_status()

def retirer_favori(item_id: str):
    lid = _id_liste_favoris()
    r = requests.delete(f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items/{item_id}",
                        headers=_headers())
    r.raise_for_status()

# ─────────────────────────────── Config par chantier (liste Projets) ───────────────────────────────
@st.cache_data(ttl=300)
def lire_projets_config() -> dict:
    """{nom_chantier: {"id", "entrepreneur", "responsable", "compagnie"}}.
    Lit TOUS les champs (pas de $select) : fonctionne même si les colonnes
    Entrepreneur/ResponsableSST n'existent pas encore (valeurs vides)."""
    lid = resoudre_liste(LISTE_PROJETS)
    out, url = {}, f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items"
    params = {"$expand": "fields", "$top": "999"}
    while url:
        d = requests.get(url, headers=_headers(), params=params).json()
        for it in d.get("value", []):
            f = it.get("fields", {})
            nom = f.get("Title")
            if nom:
                out[nom] = {
                    "id": it["id"],
                    "no": f.get("NoProjet", "") or "",
                    "entrepreneur": f.get("Entrepreneur", "") or "",
                    "responsable": f.get("ResponsableSST", "") or "",
                    "compagnie": f.get("Compagnie", "") or "",
                }
        url = d.get("@odata.nextLink"); params = None
    return out


def enregistrer_config_chantier(item_id: str, entrepreneur: str, responsable: str) -> None:
    lid = resoudre_liste(LISTE_PROJETS)
    r = requests.patch(f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items/{item_id}/fields",
                       headers={**_headers(), "Content-Type": "application/json"},
                       json={"Entrepreneur": entrepreneur, "ResponsableSST": responsable})
    r.raise_for_status()

# ─────────────────────────────── Fichiers (bibliothèque Documents) ───────────────────────────────
@st.cache_data(ttl=300)
def _drive_id() -> str:
    r = requests.get(f"{GRAPH}/sites/{SITE_ID}/drive?$select=id", headers=_headers())
    r.raise_for_status()
    return r.json()["id"]


def _slug_chemin(s: str) -> str:
    """Nettoie un segment de chemin SharePoint (retire les caractères interdits)."""
    for c in '\\/:*?"<>|#%':
        s = s.replace(c, "-")
    return s.strip() or "chantier"


def televerser_pdf(chemin_relatif: str, donnees: bytes) -> str:
    """PUT du PDF dans la bibliothèque Documents. Retourne l'URL web du fichier."""
    from urllib.parse import quote
    did = _drive_id()
    url = f"{GRAPH}/drives/{did}/root:/{quote(chemin_relatif)}:/content"
    r = requests.put(url, headers={**_headers(), "Content-Type": "application/pdf"},
                     data=donnees)
    r.raise_for_status()
    return r.json()["webUrl"]


def maj_releve(item_id: str, fields: dict) -> None:
    lid = resoudre_liste(LISTE_RELEVES)
    r = requests.patch(f"{GRAPH}/sites/{SITE_ID}/lists/{lid}/items/{item_id}/fields",
                       headers={**_headers(), "Content-Type": "application/json"}, json=fields)
    r.raise_for_status()


def deposer_pdf_releve(item_id, chantier, lieu, res, cfg, quand):
    """Construit le PDF officiel, le dépose dans « Documents » et passe le relevé
    à « Traité » (avec LienPDF). Partagé par la saisie et le rattrapage.
    quand : datetime du relevé (date/heure imprimées + nom de fichier)."""
    entete = {
        "entrepreneur": cfg.get("entrepreneur", ""),
        "chantier": chantier,
        "responsable": cfg.get("responsable", ""),
        "date": quand.date().isoformat(),
        "heure": quand.strftime("%H:%M"),
        "lieu": lieu,
        "initiales": pdf_releve.initiales(cfg.get("responsable", "")),
    }
    pdf = pdf_releve.construire_pdf(res, entete)
    chemin = f"Relevés PDF/{_slug_chemin(chantier)}/{quand:%Y-%m-%d_%H%M%S}.pdf"
    url = televerser_pdf(chemin, pdf)
    # LienPDF est une colonne « une seule ligne de texte » : Graph ne peut pas
    # écrire de colonne Hyperlien, on stocke donc l'URL en texte brut.
    maj_releve(item_id, {"LienPDF": url, "Statut": "Traité"})
    return url


def _dt_releve(s):
    """Parse la DateHeure stockée (SharePoint peut renvoyer un « Z » UTC / des
    microsecondes non gérés par fromisoformat sous 3.9). Repli : maintenant."""
    s = (s or "").replace("Z", "").split(".")[0]
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return dt.datetime.now()

# ─────────────────────────────── Authentification (login) ───────────────────────────────
st.set_page_config(page_title="Contrainte thermique", page_icon="🌡️", layout="centered")


def _injecter_style() -> None:
    """Style cosmétique léger. Purement visuel : si un sélecteur Streamlit
    ne matche pas (changement de version), l'app reste pleinement fonctionnelle."""
    st.markdown(
        """
        <style>
          /* En-tête : masquer le menu et le footer par défaut, resserrer le haut */
          #MainMenu {visibility: hidden;}
          footer {visibility: hidden;}
          [data-testid="stHeader"] {background: transparent;}
          .block-container {padding-top: 2.6rem; padding-bottom: 3rem; max-width: 820px;}

          /* Onglets un peu plus aérés */
          [data-baseweb="tab-list"] {gap: 6px;}
          button[data-baseweb="tab"] {padding-top: 8px; padding-bottom: 8px;}

          /* Cartes de relevés (st.container(border=True)) : ombre douce */
          [data-testid="stVerticalBlockBorderWrapper"] {
              border-radius: 0.7rem;
              box-shadow: 0 1px 2px rgba(28,37,48,.04), 0 6px 20px rgba(28,37,48,.05);
          }

          /* Bloc TAC : valeur plus grande et lisible */
          [data-testid="stMetricValue"] {
              font-size: 2rem;
              font-variant-numeric: tabular-nums;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


_injecter_style()

if not st.user.is_logged_in:
    st.title("🌡️ Contrainte thermique")
    st.caption("Suivi de la contrainte thermique (chaleur) sur les chantiers ELEM.")
    st.write("Connectez-vous avec votre compte ELEM pour saisir un relevé.")
    st.button("Se connecter", on_click=st.login, args=("microsoft",), type="primary")
    st.stop()

with st.sidebar:
    st.write(f"Connecté : **{st.user.name}**")
    st.button("Se déconnecter", on_click=st.logout)

# ─────────────────────────────── Données de référence ───────────────────────────────
projets_cfg = lire_projets_config()
projets = sorted(projets_cfg.keys(),
                 key=lambda n: (projets_cfg[n].get("no", ""), n))


def libelle_chantier(nom: str) -> str:
    """Libellé affiché dans les menus : « NoProjet · description ».
    Dégrade en simple description si le numéro est absent ou le nom inconnu."""
    no = projets_cfg.get(nom, {}).get("no", "")
    return f"{no} · {nom}" if no else nom

# ─────────────────────────────── Interface ───────────────────────────────
st.title("🌡️ Contrainte thermique — chaleur")
st.caption("Calcul de la TAC en direct · saisie envoyée dans SharePoint pour génération du PDF officiel.")
onglet_saisie, onglet_releves = st.tabs(["Nouveau relevé", "Mes relevés"])

with onglet_saisie:
    # Sélection du chantier — pleine largeur, au-dessus de la grille (favoris compris),
    # pour que les deux colonnes du dessous restent alignées.
    try:
        favoris = lire_favoris(st.user.email)              # {nom: item_id}
    except Exception as e:
        favoris = {}
        st.warning(f"Favoris indisponibles : {e}")

    fav_only = st.toggle("⭐ Mes favoris seulement", value=bool(favoris))
    options = [p for p in projets if p in favoris] if fav_only else projets

    csel, cfav = st.columns([4, 1])
    with csel:
        chantier = st.selectbox("Chantier", options, index=0 if options else None,
                                format_func=libelle_chantier)
    with cfav:
        st.markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)  # aligne le bouton sur le champ
        if chantier and chantier in favoris:
            if st.button("☆ Retirer", use_container_width=True):
                retirer_favori(favoris[chantier]); lire_favoris.clear(); st.rerun()
        elif chantier:
            if st.button("⭐ Favori", use_container_width=True):
                ajouter_favori(chantier, st.user.email); lire_favoris.clear(); st.rerun()

    if fav_only and not favoris:
        st.caption("Aucun favori — décochez la bascule pour voir tous les "
                   "chantiers et en ajouter.")

    cfg = projets_cfg.get(chantier, {}) if chantier else {}
    if chantier:
        with st.expander("⚙️ Configurer ce chantier"):
            e = st.text_input("Entrepreneur", value=cfg.get("entrepreneur", ""),
                              key="cfg_entrepreneur")
            r = st.text_input("Responsable SST", value=cfg.get("responsable", ""),
                              key="cfg_responsable")
            if st.button("Enregistrer la configuration"):
                if not cfg.get("id"):
                    st.error("Chantier introuvable dans la liste Projets.")
                else:
                    try:
                        enregistrer_config_chantier(cfg["id"], e, r)
                        lire_projets_config.clear()
                        st.success("Configuration enregistrée.")
                        st.rerun()
                    except Exception as ex:
                        st.error("Échec — vérifiez que les colonnes « Entrepreneur » "
                                 f"et « ResponsableSST » existent dans Projets. ({ex})")

    col1, col2 = st.columns(2)
    with col1:
        lieu = st.text_input("Lieu de la mesure", placeholder="Aire de coulage Est")
        intensite = st.radio("Intensité de travail", INTENSITES, horizontal=True, index=2)
        note = st.text_area("Note", height=80)
    with col2:
        temp = st.number_input("Température à l'ombre (°C)", value=29.0, step=0.1, format="%.1f")
        hum = st.slider("Humidité relative (%)", 0, 100, 50)
        ensoleillement = st.selectbox("Ensoleillement", ENSOLEILLEMENTS)
        source = st.radio("Source des données", SOURCES, horizontal=True)
        coton = st.toggle("Combinaison coton par-dessus")

    # Calcul officiel via tac_engine (Streamlit réexécute le script à chaque interaction)
    ens_code, charge_code, src_code = _codes_entrees(ensoleillement, intensite, source)
    res = tac_engine.calculer(temp, hum, ens_code, charge_code,
                              combinaison_coton=coton, source=src_code)

    _BANDEAU = {"V": "success", "VP": "success",
                "J1": "warning", "J2": "warning", "J3": "warning", "R": "error"}
    pause = res["pause_min_par_heure"]
    alt = ("ARRÊT" if pause is None else
           "travail continu" if pause == 0 else f"pause {pause} min/h")

    st.divider()
    m1, m2 = st.columns([1, 2])
    m1.metric("TAC", f"{res['tac']:.1f} °C".replace(".", ","))
    afficher = getattr(m2, _BANDEAU.get(res["code_zone"], "info"))
    afficher(f"**Zone {res['zone']}** — hydratation 1 verre / "
             f"{res['hydratation_min']} min · {alt}")
    st.caption("Rapport officiel IRSST généré à l'enregistrement.")

    if not cfg.get("entrepreneur") or not cfg.get("responsable"):
        st.info("Astuce : configurez l'entrepreneur et le responsable SST de ce "
                "chantier (⚙️ ci-dessus) pour un PDF complet.")

    if st.button("Enregistrer le relevé", type="primary", disabled=not (chantier and lieu)):
        maintenant = dt.datetime.now()
        # 1. Créer le relevé (En attente)
        try:
            item = creer_releve({
                "Title": f"{chantier} {maintenant:%Y-%m-%d %H:%M}",
                "Chantier": chantier,
                "Lieu": lieu,
                "DateHeure": maintenant.isoformat(),
                "Intensite": intensite,
                "TempOmbre": float(temp),
                "Humidite": int(hum),
                "Ensoleillement": ensoleillement,
                "SourceDonnes": source,
                "CombinaisonCoton": bool(coton),
                "Note": note,
                "Statut": "En attente",
                "TAC": res["tac"],
                "Zone": res["zone"],
                "SaisiPar": st.user.email,
            })
        except Exception as e:
            st.error(f"Échec de l'enregistrement : {e}")
            st.stop()

        # 2. Générer le PDF, le déposer, mettre à jour le relevé
        try:
            deposer_pdf_releve(item["id"], chantier, lieu, res, cfg, maintenant)
            lire_liste.clear()
            st.success("Relevé enregistré et PDF officiel généré. "
                       "Retrouvez-le dans « Mes relevés ».")
        except Exception as e:
            lire_liste.clear()
            st.warning("Relevé enregistré, mais le PDF n'a pas pu être généré/déposé "
                       f"(statut « En attente ») : {e}")

with onglet_releves:
    f_chantier = st.selectbox("Filtrer par chantier", ["(tous)"] + projets,
                              format_func=lambda n: "(tous)" if n == "(tous)"
                              else libelle_chantier(n))
    releves = lire_liste(LISTE_RELEVES)
    releves = [r for r in releves if f_chantier == "(tous)" or r.get("Chantier") == f_chantier]
    releves.sort(key=lambda r: r.get("DateHeure", ""), reverse=True)

    if not releves:
        st.info("Aucun relevé.")
    for r in releves[:50]:
        c = {"Verte": "🟢", "Vert pale": "🟩", "Jaune": "🟡", "Rouge": "🔴"}.get(r.get("Zone"), "⚪")
        statut = r.get("Statut", "")
        with st.container(border=True):
            a, b = st.columns([3, 1])
            a.write(f"{c} **{r.get('Chantier','')}** — {r.get('Lieu','')}")
            a.caption(f"{r.get('DateHeure','')[:16].replace('T',' ')} · {r.get('Zone','')}")
            b.metric("TAC", f"{r.get('TAC','–')} °C")
            if statut == "Traité" and r.get("LienPDF"):
                lien = r["LienPDF"]
                url = lien.get("Url") if isinstance(lien, dict) else lien
                b.link_button("PDF officiel", url)
            else:
                b.caption(f"⏳ {statut}")
                if statut == "En attente" and r.get("_item_id"):
                    if b.button("Régénérer le PDF", key=f"regen_{r['_item_id']}"):
                        try:
                            res_r = _res_depuis_releve(r)
                            cfg_r = projets_cfg.get(r.get("Chantier", ""), {})
                            deposer_pdf_releve(r["_item_id"], r.get("Chantier", ""),
                                               r.get("Lieu", ""), res_r, cfg_r,
                                               _dt_releve(r.get("DateHeure")))
                            lire_liste.clear()
                            st.success("PDF généré. Relevé passé à « Traité ».")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Échec de la régénération : {e}")