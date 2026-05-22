#!/usr/bin/env python3
"""
🏠 Chasseur d'appartements — Zone 69 Ouest
100% gratuit — Scrape LeBonCoin, PAP, SeLoger, Bien'ici
Filtre par critères, génère une page web statique
"""

import json
import time
import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── CRITÈRES ─────────────────────────────────────────────────────────────────
CRITERES = {
    "budget_min": 800,
    "budget_max": 1300,
    "pieces_min": 4,          # 3 chambres = ~4 pièces
    "dpe_max": "C",           # A B C acceptés
    "communes": [
        "brindas", "marcy", "tassin", "charbonnieres",
        "francheville", "vaugneray", "messimy", "craponne",
        "pollionnay", "st-genis", "saint-genis"
    ],
    "codes_postaux": ["69290", "69630", "69340", "69510", "69280"],
}

DPE_ORDRE = ["A", "B", "C", "D", "E", "F", "G"]
FICHIER_VUES  = Path("annonces_vues.json")
FICHIER_JSON  = Path("docs/annonces.json")
FICHIER_HTML  = Path("docs/index.html")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}


# ─── FILTRAGE ─────────────────────────────────────────────────────────────────

def dpe_ok(dpe: str) -> bool:
    if not dpe:
        return True  # On garde si inconnu
    dpe = dpe.strip().upper()
    max_idx = DPE_ORDRE.index(CRITERES["dpe_max"]) if CRITERES["dpe_max"] in DPE_ORDRE else 2
    return dpe in DPE_ORDRE and DPE_ORDRE.index(dpe) <= max_idx


def commune_ok(ville: str) -> bool:
    if not ville:
        return True
    ville_norm = ville.lower().replace("-", " ").replace("'", " ")
    for c in CRITERES["communes"]:
        if c.replace("-", " ") in ville_norm:
            return True
    return False


def prix_ok(prix) -> bool:
    try:
        p = int(re.sub(r"[^\d]", "", str(prix)))
        return CRITERES["budget_min"] <= p <= CRITERES["budget_max"]
    except:
        return True  # On garde si inconnu


def pieces_ok(pieces) -> bool:
    try:
        return int(re.sub(r"[^\d]", "", str(pieces))) >= CRITERES["pieces_min"]
    except:
        return True


def score_annonce(ann: dict) -> int:
    """Score 0–10 basé sur les critères."""
    s = 5
    # Prix
    try:
        p = int(re.sub(r"[^\d]", "", str(ann.get("prix", "0"))))
        if p == 0:
            pass
        elif p <= 950:
            s += 2
        elif p <= 1100:
            s += 1
        elif p > 1200:
            s -= 1
    except:
        pass
    # DPE
    dpe = (ann.get("dpe") or "").upper()
    if dpe == "A": s += 2
    elif dpe == "B": s += 1
    elif dpe in ("D", "E"): s -= 1
    # Surface
    try:
        surf = int(re.sub(r"[^\d]", "", str(ann.get("surface", "0"))))
        if surf >= 90: s += 1
        if surf >= 110: s += 1
    except:
        pass
    return max(0, min(10, s))


def filtrer(ann: dict) -> bool:
    return (
        prix_ok(ann.get("prix"))
        and pieces_ok(ann.get("pieces") or ann.get("surface_pieces"))
        and dpe_ok(ann.get("dpe"))
        and commune_ok(ann.get("ville"))
    )


# ─── SCRAPING ─────────────────────────────────────────────────────────────────

def scraper_leboncoin() -> list:
    annonces = []
    url = (
        "https://www.leboncoin.fr/recherche?"
        "category=10&real_estate_type=2,1"
        "&locations=69290,69630,69340,69510,69280"
        f"&price={CRITERES['budget_min']}-{CRITERES['budget_max']}"
        "&rooms=4-99&ad_type=offer"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        scripts = BeautifulSoup(r.text, "html.parser").find_all("script", {"id": "__NEXT_DATA__"})
        if scripts:
            data = json.loads(scripts[0].string)
            ads = (data.get("props", {})
                       .get("pageProps", {})
                       .get("searchData", {})
                       .get("ads", []))
            for ad in ads[:30]:
                attrs = {a["key"]: a.get("value_label", a.get("value", "")) for a in ad.get("attributes", [])}
                annonces.append({
                    "source": "LeBonCoin",
                    "titre": ad.get("subject", ""),
                    "prix": ad.get("price", [None])[0],
                    "surface": attrs.get("square", "?"),
                    "pieces": attrs.get("rooms", "?"),
                    "ville": ad.get("location", {}).get("city", ""),
                    "dpe": attrs.get("energy_rate", ""),
                    "url": "https://www.leboncoin.fr" + ad.get("url", ""),
                    "description": ad.get("body", "")[:400],
                    "date": ad.get("first_publication_date", "")[:10],
                    "image": (ad.get("images", {}).get("urls_large") or [""])[0],
                })
        log.info(f"LeBonCoin : {len(annonces)} annonces")
    except Exception as e:
        log.warning(f"LeBonCoin : {e}")
    return annonces


def scraper_pap() -> list:
    annonces = []
    url = (
        "https://www.pap.fr/annonce/locations-maison-appartement"
        "-brindas-tassin-la-demi-lune-francheville-g439"
        f"?loyer-max={CRITERES['budget_max']}&nb-pieces-min=4"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("article.search-list-item")[:20]:
            titre   = card.select_one("h2.item-title")
            prix    = card.select_one(".item-price")
            lien    = card.select_one("a[href]")
            desc    = card.select_one(".item-description")
            tags    = card.select(".item-tags li")
            img     = card.select_one("img")
            annonces.append({
                "source": "PAP",
                "titre":  titre.get_text(strip=True) if titre else "",
                "prix":   re.sub(r"[^\d]", "", prix.get_text()) if prix else "",
                "surface": tags[0].get_text(strip=True) if tags else "?",
                "pieces":  tags[1].get_text(strip=True) if len(tags) > 1 else "?",
                "ville":  "",
                "dpe":    "",
                "url":    "https://www.pap.fr" + lien["href"] if lien else "",
                "description": desc.get_text(strip=True)[:400] if desc else "",
                "date":   "",
                "image":  img["src"] if img and img.get("src") else "",
            })
        log.info(f"PAP : {len(annonces)} annonces")
    except Exception as e:
        log.warning(f"PAP : {e}")
    return annonces


def scraper_seloger() -> list:
    annonces = []
    url = (
        "https://www.seloger.com/list.htm?"
        "idtypebien=1,2&idtt=1"
        f"&pxmax={CRITERES['budget_max']}&pxmin={CRITERES['budget_min']}"
        "&nbpieces=4&cp=69290,69630,69340&tri=d_dt_crea"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        match = re.search(r'"listingData"\s*:\s*(\[.*?\])\s*[,}]', r.text, re.DOTALL)
        if not match:
            match = re.search(r'"classified"\s*:\s*(\[.*?\])', r.text, re.DOTALL)
        if match:
            for ad in json.loads(match.group(1))[:20]:
                annonces.append({
                    "source": "SeLoger",
                    "titre":  ad.get("title", ""),
                    "prix":   ad.get("pricing", {}).get("price", ""),
                    "surface": str(ad.get("surface", "?")) + "m²",
                    "pieces":  str(ad.get("rooms", "?")),
                    "ville":  ad.get("cityLabel", ""),
                    "dpe":    ad.get("energyClassification", ""),
                    "url":    ad.get("classifiedURL", ""),
                    "description": ad.get("description", "")[:400],
                    "date":   ad.get("publicationDate", "")[:10],
                    "image":  (ad.get("photos") or [""])[0],
                })
        log.info(f"SeLoger : {len(annonces)} annonces")
    except Exception as e:
        log.warning(f"SeLoger : {e}")
    return annonces


def scraper_bienici() -> list:
    annonces = []
    try:
        payload = {
            "size": 20, "from": 0,
            "filterType": "rent",
            "propertyType": ["house", "flat"],
            "minRooms": CRITERES["pieces_min"],
            "maxPrice": CRITERES["budget_max"],
            "minPrice": CRITERES["budget_min"],
            "postalCodes": CRITERES["codes_postaux"],
            "sortBy": "publicationDate", "sortOrder": "desc",
        }
        r = requests.get(
            "https://www.bienici.com/realEstateAds.json",
            headers=HEADERS,
            params={"filters": json.dumps(payload)},
            timeout=15,
        )
        for ad in r.json().get("realEstateAds", [])[:20]:
            annonces.append({
                "source": "Bien'ici",
                "titre":  ad.get("title", ""),
                "prix":   ad.get("price", ""),
                "surface": str(ad.get("surfaceArea", "?")) + "m²",
                "pieces":  str(ad.get("roomsQuantity", "?")),
                "ville":  ad.get("city", ""),
                "dpe":    ad.get("energyClassification", ""),
                "url":    "https://www.bienici.com/annonce/" + str(ad.get("id", "")),
                "description": ad.get("description", "")[:400],
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


# ─── GÉNÉRATION HTML ──────────────────────────────────────────────────────────

def generer_page(toutes: list):
    """Génère docs/index.html et docs/annonces.json"""
    FICHIER_JSON.parent.mkdir(exist_ok=True)

    # Charger l'historique existant
    historique = []
    if FICHIER_JSON.exists():
        historique = json.loads(FICHIER_JSON.read_text())

    # Ajouter les nouvelles (éviter les doublons par URL)
    urls_existantes = {a["url"] for a in historique}
    for a in toutes:
        if a["url"] not in urls_existantes:
            a["score"] = score_annonce(a)
            a["date_ajout"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            historique.insert(0, a)

    # Garder les 200 dernières
    historique = historique[:200]
    FICHIER_JSON.write_text(json.dumps(historique, ensure_ascii=False, indent=2))

    valides  = [a for a in historique if a.get("valide")]
    nb_total = len(historique)
    nb_valid = len(valides)
    now      = datetime.now().strftime("%d/%m/%Y à %H:%M")

    def badge_dpe(dpe):
        colors = {"A":"#1a9641","B":"#52b241","C":"#a6d96a","D":"#ffffbf","E":"#fdae61","F":"#d7191c","G":"#7b0000"}
        c = colors.get((dpe or "").upper(), "#ccc")
        return f'<span style="background:{c};color:{"#fff" if dpe in "ABCFG" else "#333"};padding:2px 8px;border-radius:4px;font-weight:700;font-size:0.85em">{dpe or "?"}</span>'

    def score_color(s):
        if s >= 8: return "#27ae60"
        if s >= 6: return "#f39c12"
        return "#e74c3c"

    cards_html = ""
    for a in historique[:80]:
        valid_banner = ""
        if not a.get("valide"):
            valid_banner = '<div style="position:absolute;top:0;left:0;right:0;background:rgba(0,0,0,0.55);color:#fff;font-size:0.75em;padding:3px 8px;border-radius:8px 8px 0 0">⚠️ Hors critères</div>'

        img_html = ""
        if a.get("image"):
            img_html = f'<img src="{a["image"]}" style="width:100%;height:160px;object-fit:cover;border-radius:8px 8px 0 0;display:block" onerror="this.style.display=\'none\'">'

        score = a.get("score", 5)
        cards_html += f"""
        <div class="card {'invalid' if not a.get('valide') else ''}" style="position:relative;background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,0.09);overflow:hidden;display:flex;flex-direction:column">
          {valid_banner}
          {img_html}
          <div style="padding:14px;flex:1;display:flex;flex-direction:column;gap:6px">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
              <span style="font-weight:700;font-size:0.95em;color:#1a2340;line-height:1.3">{a.get('titre','Sans titre')}</span>
              <span style="min-width:38px;text-align:center;background:{score_color(score)};color:#fff;border-radius:20px;padding:2px 9px;font-weight:700;font-size:0.85em">{score}/10</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;font-size:0.82em;color:#555">
              <span>💰 <b>{a.get('prix','?')}€</b></span>
              <span>📐 {a.get('surface','?')}</span>
              <span>🚪 {a.get('pieces','?')} pièces</span>
              <span>📍 {a.get('ville','?')}</span>
              <span>⚡ DPE {badge_dpe(a.get('dpe'))}</span>
            </div>
            <div style="font-size:0.78em;color:#888">{a.get('source','')} · {a.get('date_ajout','')}</div>
            <div style="font-size:0.82em;color:#444;margin-top:2px;flex:1">{(a.get('description') or '')[:200]}…</div>
            <a href="{a.get('url','#')}" target="_blank"
               style="margin-top:8px;display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:7px 14px;border-radius:6px;font-size:0.85em;font-weight:600;text-align:center">
              Voir l'annonce →
            </a>
          </div>
        </div>"""

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
  .card.invalid{{opacity:.65}}
  .criteria{{background:#fff;max-width:700px;margin:0 auto 20px;border-radius:10px;padding:14px 20px;box-shadow:0 1px 6px rgba(0,0,0,0.07);font-size:0.85em;color:#444;display:flex;flex-wrap:wrap;gap:10px;justify-content:center}}
  .criteria span{{background:#f0f4f8;padding:4px 10px;border-radius:20px}}
  @media(max-width:500px){{header h1{{font-size:1.3em}}}}
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
  <span>💰 800–1 300€</span>
  <span>🚪 3 chambres min</span>
  <span>⚡ DPE ≤ C</span>
  <span>📍 Brindas, Tassin, Francheville, Charbonnières, Vaugneray, Messimy…</span>
</div>

<div class="filters">
  <button class="active" onclick="filtrer('tous',this)">Toutes ({nb_total})</button>
  <button onclick="filtrer('valides',this)">✅ Valides ({nb_valid})</button>
  <button onclick="filtrer('top',this)">⭐ Score ≥ 7</button>
</div>

<div class="grid" id="grid">
{cards_html}
</div>

<script>
function filtrer(mode, btn) {{
  document.querySelectorAll('.filters button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card').forEach(c => {{
    const invalid = c.classList.contains('invalid');
    const score = parseInt(c.querySelector('[style*="border-radius:20px"]')?.textContent) || 0;
    if (mode === 'tous') c.style.display = '';
    else if (mode === 'valides') c.style.display = invalid ? 'none' : '';
    else if (mode === 'top') c.style.display = score >= 7 ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""

    FICHIER_HTML.write_text(html, encoding="utf-8")
    log.info(f"Page générée : {FICHIER_HTML} ({nb_valid} valides / {nb_total} total)")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("🔍 Démarrage de la recherche...")
    vues = charger_vues()

    toutes_annonces = (
        scraper_leboncoin() +
        scraper_pap() +
        scraper_seloger() +
        scraper_bienici()
    )

    # Filtrage + marquage
    nouvelles = []
    for a in toutes_annonces:
        a["valide"] = filtrer(a)
        if uid(a["url"]) not in vues:
            nouvelles.append(a)
            vues.add(uid(a["url"]))

    log.info(f"📋 {len(nouvelles)} nouvelles / {len(toutes_annonces)} au total")
    generer_page(nouvelles)
    sauvegarder_vues(vues)
    log.info("✅ Terminé.")


if __name__ == "__main__":
    main()
