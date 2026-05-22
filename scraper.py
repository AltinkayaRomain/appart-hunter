#!/usr/bin/env python3
"""
🏠 Chasseur d'appartements — Zone 69 Ouest
Via flux RSS/XML officiels — 100% gratuit, sans blocage
Sources : LeBonCoin RSS, PAP RSS, SeLoger RSS, Logic-Immo RSS
"""

import json
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

# ─── CRITÈRES ─────────────────────────────────────────────────────────────────
CRITERES = {
    "budget_min": 800,
    "budget_max": 1300,
    "pieces_min": 4,
    "dpe_max": "C",
    "communes": [
        "brindas", "marcy", "tassin", "charbonnieres", "charbonnières",
        "francheville", "vaugneray", "messimy", "craponne",
        "pollionnay", "st-genis", "saint-genis", "brindas",
        "69290", "69630", "69340", "69510", "69280"
    ],
}

DPE_ORDRE  = ["A", "B", "C", "D", "E", "F", "G"]
FICHIER_VUES = Path("annonces_vues.json")
FICHIER_JSON = Path("docs/annonces.json")
FICHIER_HTML = Path("docs/index.html")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AppartHunterBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


# ─── FILTRAGE ─────────────────────────────────────────────────────────────────

def dpe_ok(dpe: str) -> bool:
    if not dpe:
        return True
    dpe = dpe.strip().upper()
    if dpe not in DPE_ORDRE:
        return True
    return DPE_ORDRE.index(dpe) <= DPE_ORDRE.index(CRITERES["dpe_max"])

def commune_ok(texte: str) -> bool:
    if not texte:
        return True
    t = texte.lower().replace("-", " ").replace("'", " ")
    for c in CRITERES["communes"]:
        if c.replace("-", " ") in t:
            return True
    return False

def prix_ok(prix) -> bool:
    try:
        p = int(re.sub(r"[^\d]", "", str(prix)))
        if p == 0: return True
        return CRITERES["budget_min"] <= p <= CRITERES["budget_max"]
    except:
        return True

def pieces_ok(pieces) -> bool:
    try:
        return int(re.sub(r"[^\d]", "", str(pieces))) >= CRITERES["pieces_min"]
    except:
        return True

def filtrer(ann: dict) -> bool:
    texte_complet = " ".join([
        str(ann.get("titre", "")),
        str(ann.get("ville", "")),
        str(ann.get("description", "")),
    ])
    return (
        prix_ok(ann.get("prix"))
        and pieces_ok(ann.get("pieces") or "0")
        and dpe_ok(ann.get("dpe"))
        and commune_ok(texte_complet)
    )

def score_annonce(ann: dict) -> int:
    s = 5
    try:
        p = int(re.sub(r"[^\d]", "", str(ann.get("prix", "0"))))
        if 0 < p <= 950: s += 2
        elif p <= 1100: s += 1
        elif p > 1200: s -= 1
    except: pass
    dpe = (ann.get("dpe") or "").upper()
    if dpe == "A": s += 2
    elif dpe == "B": s += 1
    elif dpe in ("D", "E"): s -= 1
    try:
        surf = int(re.sub(r"[^\d]", "", str(ann.get("surface", "0"))))
        if surf >= 90: s += 1
        if surf >= 110: s += 1
    except: pass
    return max(0, min(10, s))


# ─── SCRAPING RSS ─────────────────────────────────────────────────────────────

def parse_rss(url: str, source: str, parser_fn) -> list:
    """Télécharge et parse un flux RSS."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        annonces = [a for item in items if (a := parser_fn(item)) is not None]
        log.info(f"{source} : {len(annonces)} annonces via RSS")
        return annonces
    except Exception as e:
        log.warning(f"{source} RSS erreur : {e}")
        return []


def txt(el, tag: str) -> str:
    node = el.find(tag)
    return (node.text or "").strip() if node is not None else ""


def extraire_prix(texte: str) -> str:
    m = re.search(r"(\d[\d\s]*)\s*€", texte)
    return re.sub(r"\s", "", m.group(1)) if m else ""

def extraire_pieces(texte: str) -> str:
    m = re.search(r"(\d+)\s*pi[eè]ce", texte, re.I)
    if m: return m.group(1)
    m = re.search(r"(\d+)\s*chambre", texte, re.I)
    if m: return str(int(m.group(1)) + 1)
    return ""

def extraire_surface(texte: str) -> str:
    m = re.search(r"(\d+)\s*m[²2]", texte, re.I)
    return m.group(1) + "m²" if m else ""

def extraire_dpe(texte: str) -> str:
    m = re.search(r"[Cc]lasse\s+([A-G])\b", texte)
    if not m:
        m = re.search(r"\bDPE\s*:?\s*([A-G])\b", texte, re.I)
    return m.group(1).upper() if m else ""


# LeBonCoin RSS ----------------------------------------------------------------
def scraper_leboncoin() -> list:
    # LeBonCoin propose des flux RSS par recherche
    urls = [
        # 69290 Brindas/Vaugneray/Messimy
        f"https://www.leboncoin.fr/recherche.rss?category=10&real_estate_type=2,1&locations=69290&price={CRITERES['budget_min']}-{CRITERES['budget_max']}&rooms=4-99",
        # 69630 Chaponost / Francheville
        f"https://www.leboncoin.fr/recherche.rss?category=10&real_estate_type=2,1&locations=69630&price={CRITERES['budget_min']}-{CRITERES['budget_max']}&rooms=4-99",
        # 69340 Francheville/Charbonnières
        f"https://www.leboncoin.fr/recherche.rss?category=10&real_estate_type=2,1&locations=69340&price={CRITERES['budget_min']}-{CRITERES['budget_max']}&rooms=4-99",
        # 69160 Tassin
        f"https://www.leboncoin.fr/recherche.rss?category=10&real_estate_type=2,1&locations=69160&price={CRITERES['budget_min']}-{CRITERES['budget_max']}&rooms=4-99",
    ]
    annonces = []
    for url in urls:
        def parser(item):
            titre = txt(item, "title")
            lien  = txt(item, "link")
            desc  = txt(item, "description")
            texte = titre + " " + desc
            return {
                "source": "LeBonCoin",
                "titre": titre,
                "prix": extraire_prix(texte),
                "pieces": extraire_pieces(texte),
                "surface": extraire_surface(texte),
                "ville": "",
                "dpe": extraire_dpe(texte),
                "url": lien,
                "description": re.sub(r"<[^>]+>", " ", desc)[:400],
                "date": txt(item, "pubDate")[:16],
                "image": "",
            }
        annonces += parse_rss(url, "LeBonCoin", parser)
    return annonces


# PAP RSS ----------------------------------------------------------------------
def scraper_pap() -> list:
    # PAP expose des flux RSS de recherche
    urls = [
        f"https://www.pap.fr/annonce/locations-maison-appartement-rhone-69-g477.rss?loyer-max={CRITERES['budget_max']}&nb-pieces-min=4",
        f"https://www.pap.fr/annonce/locations-maison-appartement-brindas-tassin-la-demi-lune-francheville-g439.rss?loyer-max={CRITERES['budget_max']}&nb-pieces-min=4",
    ]
    annonces = []
    for url in urls:
        def parser(item):
            titre = txt(item, "title")
            lien  = txt(item, "link")
            desc  = txt(item, "description")
            texte = titre + " " + desc
            return {
                "source": "PAP",
                "titre": titre,
                "prix": extraire_prix(texte),
                "pieces": extraire_pieces(texte),
                "surface": extraire_surface(texte),
                "ville": "",
                "dpe": extraire_dpe(texte),
                "url": lien,
                "description": re.sub(r"<[^>]+>", " ", desc)[:400],
                "date": txt(item, "pubDate")[:16],
                "image": "",
            }
        annonces += parse_rss(url, "PAP", parser)
    return annonces


# Logic-Immo RSS ---------------------------------------------------------------
def scraper_logic_immo() -> list:
    url = (
        f"https://www.logic-immo.com/rss/annonces-location-maison-appartement-"
        f"brindas-tassin-francheville-charbonnieres-vaugneray-69,159,164,168,172,175.rss"
        f"?px-max={CRITERES['budget_max']}&px-min={CRITERES['budget_min']}&nb-pieces-min=4"
    )
    def parser(item):
        titre = txt(item, "title")
        lien  = txt(item, "link")
        desc  = txt(item, "description")
        texte = titre + " " + desc
        return {
            "source": "Logic-Immo",
            "titre": titre,
            "prix": extraire_prix(texte),
            "pieces": extraire_pieces(texte),
            "surface": extraire_surface(texte),
            "ville": "",
            "dpe": extraire_dpe(texte),
            "url": lien,
            "description": re.sub(r"<[^>]+>", " ", desc)[:400],
            "date": txt(item, "pubDate")[:16],
            "image": "",
        }
    return parse_rss(url, "Logic-Immo", parser)


# Bien'ici API JSON ------------------------------------------------------------
def scraper_bienici() -> list:
    annonces = []
    try:
        payload = {
            "size": 30, "from": 0,
            "filterType": "rent",
            "propertyType": ["house", "flat"],
            "minRooms": CRITERES["pieces_min"],
            "maxPrice": CRITERES["budget_max"],
            "minPrice": CRITERES["budget_min"],
            "postalCodes": ["69290", "69630", "69340", "69510", "69280", "69160"],
            "sortBy": "publicationDate", "sortOrder": "desc",
        }
        r = requests.get(
            "https://www.bienici.com/realEstateAds.json",
            headers=HEADERS,
            params={"filters": json.dumps(payload)},
            timeout=20,
        )
        for ad in r.json().get("realEstateAds", []):
            annonces.append({
                "source": "Bien'ici",
                "titre":  ad.get("title", ""),
                "prix":   str(ad.get("price", "")),
                "surface": str(ad.get("surfaceArea", "")) + "m²",
                "pieces":  str(ad.get("roomsQuantity", "")),
                "ville":  ad.get("city", ""),
                "dpe":    ad.get("energyClassification", ""),
                "url":    "https://www.bienici.com/annonce/" + str(ad.get("id", "")),
                "description": (ad.get("description") or "")[:400],
                "date":   (ad.get("publicationDate") or "")[:10],
                "image":  (ad.get("photos") or [{}])[0].get("url", ""),
            })
        log.info(f"Bien'ici : {len(annonces)} annonces")
    except Exception as e:
        log.warning(f"Bien'ici : {e}")
    return annonces


# ─── MÉMOIRE ──────────────────────────────────────────────────────────────────

def charger_vues() -> set:
    if FICHIER_VUES.exists():
        return set(json.loads(FICHIER_VUES.read_text()))
    return set()

def sauvegarder_vues(vues: set):
    FICHIER_VUES.write_text(json.dumps(list(vues)))

def uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ─── PAGE HTML ────────────────────────────────────────────────────────────────

def generer_page(toutes: list):
    FICHIER_JSON.parent.mkdir(exist_ok=True)

    historique = []
    if FICHIER_JSON.exists():
        try:
            historique = json.loads(FICHIER_JSON.read_text())
        except:
            historique = []

    urls_existantes = {a["url"] for a in historique}
    for a in toutes:
        if a["url"] not in urls_existantes:
            a["score"] = score_annonce(a)
            a["date_ajout"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            historique.insert(0, a)

    historique = historique[:300]
    FICHIER_JSON.write_text(json.dumps(historique, ensure_ascii=False, indent=2))

    valides  = [a for a in historique if a.get("valide")]
    nb_total = len(historique)
    nb_valid = len(valides)
    now      = datetime.now().strftime("%d/%m/%Y à %H:%M")

    def badge_dpe(dpe):
        colors = {"A":"#1a9641","B":"#52b241","C":"#a6d96a","D":"#ffffbf","E":"#fdae61","F":"#d7191c","G":"#7b0000"}
        c = colors.get((dpe or "").upper(), "#ccc")
        txt_c = "#fff" if (dpe or "").upper() in "ABCFG" else "#333"
        return f'<span style="background:{c};color:{txt_c};padding:2px 8px;border-radius:4px;font-weight:700;font-size:0.85em">{dpe or "?"}</span>'

    def score_color(s):
        if s >= 8: return "#27ae60"
        if s >= 6: return "#f39c12"
        return "#e74c3c"

    cards_html = ""
    for a in historique[:100]:
        valid_banner = "" if a.get("valide") else '<div style="position:absolute;top:0;left:0;right:0;background:rgba(0,0,0,0.55);color:#fff;font-size:0.75em;padding:3px 8px;border-radius:8px 8px 0 0">⚠️ Hors critères</div>'
        img_html = f'<img src="{a["image"]}" style="width:100%;height:150px;object-fit:cover;border-radius:8px 8px 0 0;display:block" onerror="this.style.display=\'none\'">' if a.get("image") else ""
        score = a.get("score", 5)
        ville_display = a.get("ville") or ""
        cards_html += f"""
        <div class="card {'invalid' if not a.get('valide') else ''}" style="position:relative;background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,0.09);overflow:hidden;display:flex;flex-direction:column">
          {valid_banner}{img_html}
          <div style="padding:14px;flex:1;display:flex;flex-direction:column;gap:6px">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
              <span style="font-weight:700;font-size:0.95em;color:#1a2340;line-height:1.3">{a.get('titre','Sans titre')}</span>
              <span style="min-width:38px;text-align:center;background:{score_color(score)};color:#fff;border-radius:20px;padding:2px 9px;font-weight:700;font-size:0.85em">{score}/10</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;font-size:0.82em;color:#555">
              <span>💰 <b>{a.get('prix','?')}€</b></span>
              <span>📐 {a.get('surface','?')}</span>
              <span>🚪 {a.get('pieces','?')} pièces</span>
              {'<span>📍 ' + ville_display + '</span>' if ville_display else ''}
              <span>⚡ DPE {badge_dpe(a.get('dpe'))}</span>
            </div>
            <div style="font-size:0.78em;color:#888">{a.get('source','')} · {a.get('date_ajout','')}</div>
            <div style="font-size:0.82em;color:#444;margin-top:2px;flex:1">{(a.get('description') or '')[:200]}…</div>
            <a href="{a.get('url','#')}" target="_blank" style="margin-top:8px;display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:7px 14px;border-radius:6px;font-size:0.85em;font-weight:600;text-align:center">Voir l'annonce →</a>
          </div>
        </div>"""

    sources_count = {}
    for a in historique:
        s = a.get("source","?")
        sources_count[s] = sources_count.get(s,0) + 1
    sources_html = " · ".join(f"{s} ({n})" for s,n in sources_count.items())

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🏠 Chasseur d'apparts — 69 Ouest</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f4f8;min-height:100vh}}
  header{{background:linear-gradient(135deg,#1a2340,#2563eb);color:#fff;padding:28px 24px 20px;text-align:center}}
  header h1{{font-size:1.6em;margin-bottom:6px}}
  header p{{opacity:.85;font-size:0.9em}}
  .stats{{display:flex;justify-content:center;gap:20px;margin:18px auto;max-width:700px;flex-wrap:wrap;padding:0 16px}}
  .stat{{background:#fff;border-radius:10px;padding:14px 24px;text-align:center;box-shadow:0 1px 6px rgba(0,0,0,0.08);min-width:130px}}
  .stat .n{{font-size:2em;font-weight:800;color:#2563eb}}
  .stat .l{{font-size:0.82em;color:#666;margin-top:2px}}
  .filters{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;padding:0 16px 16px}}
  .filters button{{border:none;padding:7px 16px;border-radius:20px;cursor:pointer;font-size:0.85em;font-weight:600;transition:.15s}}
  .filters button.active{{background:#2563eb;color:#fff}}
  .filters button:not(.active){{background:#fff;color:#444;box-shadow:0 1px 4px rgba(0,0,0,0.1)}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:18px;padding:0 16px 40px;max-width:1200px;margin:0 auto}}
  .card{{transition:transform .15s,box-shadow .15s}}
  .card:hover{{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,0.13)}}
  .card.invalid{{opacity:.6}}
  .criteria{{background:#fff;max-width:750px;margin:0 auto 20px;border-radius:10px;padding:14px 20px;box-shadow:0 1px 6px rgba(0,0,0,0.07);font-size:0.85em;color:#444;display:flex;flex-wrap:wrap;gap:10px;justify-content:center}}
  .criteria span{{background:#f0f4f8;padding:4px 10px;border-radius:20px}}
  .sources{{text-align:center;font-size:0.78em;color:#94a3b8;margin-bottom:12px}}
</style>
</head>
<body>
<header>
  <h1>🏠 Chasseur d'appartements</h1>
  <p>Zone 69 Ouest · Mis à jour le {now}</p>
</header>
<div class="stats">
  <div class="stat"><div class="n">{nb_valid}</div><div class="l">Annonces valides</div></div>
  <div class="stat"><div class="n">{nb_total}</div><div class="l">Total analysées</div></div>
  <div class="stat"><div class="n">1h</div><div class="l">Fréquence MAJ</div></div>
</div>
<div class="criteria">
  <span>💰 800–1 300€</span><span>🚪 3 chambres min</span><span>⚡ DPE ≤ C</span>
  <span>📍 Brindas, Tassin, Francheville, Charbonnières, Vaugneray, Messimy, Craponne…</span>
</div>
<div class="sources">Sources : {sources_html}</div>
<div class="filters">
  <button class="active" onclick="filtrer('tous',this)">Toutes ({nb_total})</button>
  <button onclick="filtrer('valides',this)">✅ Valides ({nb_valid})</button>
  <button onclick="filtrer('top',this)">⭐ Score ≥ 7</button>
</div>
<div class="grid" id="grid">{cards_html}</div>
<script>
function filtrer(mode,btn){{
  document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card').forEach(c=>{{
    const inv=c.classList.contains('invalid');
    const score=parseInt(c.querySelector('[style*="border-radius:20px"]')?.textContent)||0;
    if(mode==='tous') c.style.display='';
    else if(mode==='valides') c.style.display=inv?'none':'';
    else if(mode==='top') c.style.display=score>=7?'':'none';
  }});
}}
</script>
</body></html>"""

    FICHIER_HTML.write_text(html, encoding="utf-8")
    log.info(f"Page générée : {nb_valid} valides / {nb_total} total")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("🔍 Démarrage de la recherche...")
    vues = charger_vues()

    toutes = (
        scraper_leboncoin() +
        scraper_pap() +
        scraper_logic_immo() +
        scraper_bienici()
    )

    # Dédoublonnage + filtrage
    seen_urls = set()
    propres = []
    for a in toutes:
        if not a.get("url") or a["url"] in seen_urls:
            continue
        seen_urls.add(a["url"])
        a["valide"] = filtrer(a)
        if uid(a["url"]) not in vues:
            propres.append(a)
            vues.add(uid(a["url"]))

    log.info(f"📋 {len(propres)} nouvelles / {len(toutes)} au total")
    generer_page(propres)
    sauvegarder_vues(vues)
    log.info("✅ Terminé.")

if __name__ == "__main__":
    main()
