#!/usr/bin/env python3
"""
🏠 Chasseur d'appartements — Zone 69 Ouest
Sources : Bien'ici (géoloc GPS), LeBonCoin RSS, PAP RSS
"""

import json, hashlib, logging, re, xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

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
        "pollionnay", "st-genis", "saint-genis",
        "69290", "69630", "69340", "69510", "69280", "69160"
    ],
}

DPE_ORDRE    = ["A","B","C","D","E","F","G"]
FICHIER_VUES = Path("annonces_vues.json")
FICHIER_JSON = Path("docs/annonces.json")
FICHIER_HTML = Path("docs/index.html")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


# ─── FILTRAGE ─────────────────────────────────────────────────────────────────

def dpe_ok(dpe):
    if not dpe: return True
    dpe = dpe.strip().upper()
    if dpe not in DPE_ORDRE: return True
    return DPE_ORDRE.index(dpe) <= DPE_ORDRE.index(CRITERES["dpe_max"])

def commune_ok(texte):
    if not texte: return True
    t = texte.lower().replace("-"," ").replace("'"," ")
    return any(c.replace("-"," ") in t for c in CRITERES["communes"])

def prix_ok(prix):
    try:
        p = int(re.sub(r"[^\d]","",str(prix)))
        return p == 0 or CRITERES["budget_min"] <= p <= CRITERES["budget_max"]
    except: return True

def pieces_ok(pieces):
    try: return int(re.sub(r"[^\d]","",str(pieces))) >= CRITERES["pieces_min"]
    except: return True

def filtrer(ann):
    texte = " ".join([str(ann.get(k,"")) for k in ("titre","ville","description")])
    return prix_ok(ann.get("prix")) and pieces_ok(ann.get("pieces","0")) \
           and dpe_ok(ann.get("dpe")) and commune_ok(texte)

def score_annonce(ann):
    s = 5
    try:
        p = int(re.sub(r"[^\d]","",str(ann.get("prix","0"))))
        if 0 < p <= 950: s += 2
        elif p <= 1100: s += 1
        elif p > 1200: s -= 1
    except: pass
    dpe = (ann.get("dpe") or "").upper()
    if dpe == "A": s += 2
    elif dpe == "B": s += 1
    elif dpe in ("D","E"): s -= 1
    try:
        surf = int(re.sub(r"[^\d]","",str(ann.get("surface","0"))))
        if surf >= 90: s += 1
        if surf >= 110: s += 1
    except: pass
    return max(0, min(10, s))

def extraire_prix(t):
    m = re.search(r"(\d[\d\s]{2,})\s*[€e]", t)
    return re.sub(r"\s","",m.group(1)) if m else ""

def extraire_pieces(t):
    m = re.search(r"(\d+)\s*pi[eè]ce", t, re.I)
    if m: return m.group(1)
    m = re.search(r"(\d+)\s*chambre", t, re.I)
    if m: return str(int(m.group(1))+1)
    return ""

def extraire_surface(t):
    m = re.search(r"(\d+)\s*m[²2]", t, re.I)
    return m.group(1)+"m²" if m else ""

def extraire_dpe(t):
    for pat in [r"[Cc]lasse\s+énergie\s*:?\s*([A-G])", r"\bDPE\s*:?\s*([A-G])\b", r"énergie\s*([A-G])\b"]:
        m = re.search(pat, t, re.I)
        if m: return m.group(1).upper()
    return ""


# ─── BIEN'ICI — géolocalisation GPS autour de Francheville ────────────────────

def scraper_bienici() -> list:
    """
    Recherche par cercle GPS centré sur Francheville (69340)
    rayon 8km — couvre toute la zone 69 Ouest
    """
    annonces = []
    # Centre approximatif de la zone (entre Francheville et Tassin)
    filters = {
        "size": 100,
        "from": 0,
        "filterType": "rent",
        "propertyType": ["house", "flat"],
        "minRooms": CRITERES["pieces_min"],
        "maxPrice": CRITERES["budget_max"],
        "minPrice": CRITERES["budget_min"],
        "sortBy": "publicationDate",
        "sortOrder": "desc",
        # Recherche par zone géographique (cercle GPS)
        "zoneIdsByTypes": {
            "zoneIds": ["69340", "69290", "69630", "69160", "69510", "69280"]
        },
        "location": {
            # Francheville centre
            "lat": 45.7328,
            "lng": 4.7642,
            "radius": 10000  # 10km
        }
    }
    try:
        r = requests.get(
            "https://www.bienici.com/realEstateAds.json",
            headers=HEADERS,
            params={"filters": json.dumps(filters)},
            timeout=20,
        )
        data = r.json()
        for ad in data.get("realEstateAds", []):
            city = ad.get("city","")
            dept = ad.get("postalCode","")
            annonces.append({
                "source": "Bien'ici",
                "titre":  ad.get("title",""),
                "prix":   str(ad.get("price","")),
                "surface": str(ad.get("surfaceArea",""))+"m²",
                "pieces":  str(ad.get("roomsQuantity","")),
                "ville":  f"{city} ({dept})" if dept else city,
                "dpe":    ad.get("energyClassification",""),
                "url":    "https://www.bienici.com/annonce/"+str(ad.get("id","")),
                "description": (ad.get("description") or "")[:400],
                "date":   (ad.get("publicationDate") or "")[:10],
                "image":  (ad.get("photos") or [{}])[0].get("url",""),
            })
        log.info(f"Bien'ici : {len(annonces)} annonces (rayon 10km Francheville)")
    except Exception as e:
        log.warning(f"Bien'ici : {e}")
    return annonces


# ─── LEBONCOIN RSS ─────────────────────────────────────────────────────────────

def scraper_leboncoin() -> list:
    annonces = []
    # Un flux RSS par code postal
    for cp in ["69290","69630","69340","69160","69510"]:
        url = (f"https://www.leboncoin.fr/recherche.rss?"
               f"category=10&real_estate_type=2,1&locations={cp}"
               f"&price={CRITERES['budget_min']}-{CRITERES['budget_max']}&rooms=4-99")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                titre = (item.find("title").text or "") if item.find("title") is not None else ""
                lien  = (item.find("link").text or "")  if item.find("link")  is not None else ""
                desc_node = item.find("description")
                desc_raw  = (desc_node.text or "") if desc_node is not None else ""
                desc  = re.sub(r"<[^>]+>"," ", desc_raw)
                texte = titre+" "+desc
                annonces.append({
                    "source": "LeBonCoin",
                    "titre":  titre,
                    "prix":   extraire_prix(texte),
                    "pieces": extraire_pieces(texte),
                    "surface":extraire_surface(texte),
                    "ville":  cp,
                    "dpe":    extraire_dpe(texte),
                    "url":    lien,
                    "description": desc[:400],
                    "date":   (item.find("pubDate").text or "")[:16] if item.find("pubDate") is not None else "",
                    "image":  "",
                })
            log.info(f"LeBonCoin {cp} : {len(annonces)} annonces RSS")
        except Exception as e:
            log.warning(f"LeBonCoin {cp} : {e}")
    return annonces


# ─── PAP RSS ───────────────────────────────────────────────────────────────────

def scraper_pap() -> list:
    annonces = []
    urls = [
        f"https://www.pap.fr/annonce/locations-maison-appartement-rhone-69-g477.rss?loyer-max={CRITERES['budget_max']}&nb-pieces-min=4",
        f"https://www.pap.fr/annonce/locations-maison-appartement-ain-01-g39.rss?loyer-max={CRITERES['budget_max']}&nb-pieces-min=4",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                titre = (item.find("title").text or "") if item.find("title") is not None else ""
                lien  = (item.find("link").text or "")  if item.find("link")  is not None else ""
                desc_node = item.find("description")
                desc_raw  = (desc_node.text or "") if desc_node is not None else ""
                desc  = re.sub(r"<[^>]+>"," ", desc_raw)
                texte = titre+" "+desc
                annonces.append({
                    "source": "PAP",
                    "titre":  titre,
                    "prix":   extraire_prix(texte),
                    "pieces": extraire_pieces(texte),
                    "surface":extraire_surface(texte),
                    "ville":  "",
                    "dpe":    extraire_dpe(texte),
                    "url":    lien,
                    "description": desc[:400],
                    "date":   (item.find("pubDate").text or "")[:16] if item.find("pubDate") is not None else "",
                    "image":  "",
                })
            log.info(f"PAP : {len(annonces)} annonces RSS")
        except Exception as e:
            log.warning(f"PAP : {e}")
    return annonces


# ─── MÉMOIRE ──────────────────────────────────────────────────────────────────

def charger_vues():
    if FICHIER_VUES.exists():
        try: return set(json.loads(FICHIER_VUES.read_text()))
        except: return set()
    return set()

def sauvegarder_vues(vues):
    FICHIER_VUES.write_text(json.dumps(list(vues)))

def uid(url): return hashlib.md5(url.encode()).hexdigest()


# ─── PAGE HTML ────────────────────────────────────────────────────────────────

def generer_page(toutes):
    FICHIER_JSON.parent.mkdir(exist_ok=True)
    historique = []
    if FICHIER_JSON.exists():
        try: historique = json.loads(FICHIER_JSON.read_text())
        except: pass

    urls_ex = {a["url"] for a in historique}
    for a in toutes:
        if a["url"] not in urls_ex:
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
        colors={"A":"#1a9641","B":"#52b241","C":"#a6d96a","D":"#ffffbf","E":"#fdae61","F":"#d7191c","G":"#7b0000"}
        c=colors.get((dpe or "").upper(),"#ccc")
        tc="#fff" if (dpe or "").upper() in "ABCFG" else "#333"
        return f'<span style="background:{c};color:{tc};padding:2px 8px;border-radius:4px;font-weight:700;font-size:.85em">{dpe or "?"}</span>'

    def sc(s): return "#27ae60" if s>=8 else "#f39c12" if s>=6 else "#e74c3c"

    cards=""
    for a in historique[:120]:
        s=a.get("score",5)
        banner="" if a.get("valide") else '<div style="position:absolute;top:0;left:0;right:0;background:rgba(0,0,0,.55);color:#fff;font-size:.75em;padding:3px 8px;border-radius:8px 8px 0 0">⚠️ Hors critères</div>'
        img=f'<img src="{a["image"]}" style="width:100%;height:150px;object-fit:cover;border-radius:8px 8px 0 0;display:block" onerror="this.style.display=\'none\'">' if a.get("image") else ""
        ville=a.get("ville") or ""
        cards+=f"""<div class="card {'invalid' if not a.get('valide') else ''}" style="position:relative;background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.09);overflow:hidden;display:flex;flex-direction:column">
{banner}{img}<div style="padding:14px;flex:1;display:flex;flex-direction:column;gap:6px">
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px"><span style="font-weight:700;font-size:.95em;color:#1a2340;line-height:1.3">{a.get('titre','Sans titre')}</span><span style="min-width:38px;text-align:center;background:{sc(s)};color:#fff;border-radius:20px;padding:2px 9px;font-weight:700;font-size:.85em">{s}/10</span></div>
<div style="display:flex;flex-wrap:wrap;gap:6px;font-size:.82em;color:#555"><span>💰 <b>{a.get('prix','?')}€</b></span><span>📐 {a.get('surface','?')}</span><span>🚪 {a.get('pieces','?')} pièces</span>{'<span>📍 '+ville+'</span>' if ville else ''}<span>⚡ DPE {badge_dpe(a.get('dpe'))}</span></div>
<div style="font-size:.78em;color:#888">{a.get('source','')} · {a.get('date_ajout','')}</div>
<div style="font-size:.82em;color:#444;margin-top:2px;flex:1">{(a.get('description') or '')[:220]}…</div>
<a href="{a.get('url','#')}" target="_blank" style="margin-top:8px;display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:7px 14px;border-radius:6px;font-size:.85em;font-weight:600;text-align:center">Voir l'annonce →</a>
</div></div>"""

    src={};  [src.update({a.get("source","?"):src.get(a.get("source","?"),0)+1}) for a in historique]
    src_txt=" · ".join(f"{k} ({v})" for k,v in src.items())

    html=f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>🏠 Chasseur d'apparts — 69 Ouest</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f4f8}}
header{{background:linear-gradient(135deg,#1a2340,#2563eb);color:#fff;padding:28px 24px 20px;text-align:center}}header h1{{font-size:1.6em;margin-bottom:6px}}header p{{opacity:.85;font-size:.9em}}
.stats{{display:flex;justify-content:center;gap:20px;margin:18px auto;max-width:700px;flex-wrap:wrap;padding:0 16px}}.stat{{background:#fff;border-radius:10px;padding:14px 24px;text-align:center;box-shadow:0 1px 6px rgba(0,0,0,.08);min-width:130px}}.stat .n{{font-size:2em;font-weight:800;color:#2563eb}}.stat .l{{font-size:.82em;color:#666;margin-top:2px}}
.filters{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;padding:0 16px 16px}}.filters button{{border:none;padding:7px 16px;border-radius:20px;cursor:pointer;font-size:.85em;font-weight:600}}.filters button.active{{background:#2563eb;color:#fff}}.filters button:not(.active){{background:#fff;color:#444;box-shadow:0 1px 4px rgba(0,0,0,.1)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:18px;padding:0 16px 40px;max-width:1200px;margin:0 auto}}.card{{transition:transform .15s,box-shadow .15s}}.card:hover{{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,.13)}}.card.invalid{{opacity:.6}}
.criteria{{background:#fff;max-width:750px;margin:0 auto 12px;border-radius:10px;padding:14px 20px;box-shadow:0 1px 6px rgba(0,0,0,.07);font-size:.85em;color:#444;display:flex;flex-wrap:wrap;gap:10px;justify-content:center}}.criteria span{{background:#f0f4f8;padding:4px 10px;border-radius:20px}}
.sources{{text-align:center;font-size:.78em;color:#94a3b8;margin-bottom:12px}}</style></head>
<body><header><h1>🏠 Chasseur d'appartements</h1><p>Zone 69 Ouest · Mis à jour le {now}</p></header>
<div class="stats"><div class="stat"><div class="n">{nb_valid}</div><div class="l">Annonces valides</div></div><div class="stat"><div class="n">{nb_total}</div><div class="l">Total analysées</div></div><div class="stat"><div class="n">1h</div><div class="l">Fréquence MAJ</div></div></div>
<div class="criteria"><span>💰 800–1 300€</span><span>🚪 3 chambres min</span><span>⚡ DPE ≤ C</span><span>📍 Brindas, Tassin, Francheville, Charbonnières, Vaugneray, Messimy, Craponne…</span></div>
<div class="sources">Sources : {src_txt}</div>
<div class="filters"><button class="active" onclick="filtrer('tous',this)">Toutes ({nb_total})</button><button onclick="filtrer('valides',this)">✅ Valides ({nb_valid})</button><button onclick="filtrer('top',this)">⭐ Score ≥ 7</button></div>
<div class="grid" id="grid">{cards}</div>
<script>function filtrer(m,b){{document.querySelectorAll('.filters button').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.card').forEach(c=>{{const inv=c.classList.contains('invalid');const s=parseInt(c.querySelector('[style*="border-radius:20px"]')?.textContent)||0;c.style.display=m==='tous'?'':m==='valides'?inv?'none':'':s>=7?'':'none';}});}}</script>
</body></html>"""

    FICHIER_HTML.write_text(html, encoding="utf-8")
    log.info(f"Page générée : {nb_valid} valides / {nb_total} total")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("🔍 Recherche en cours...")
    vues = charger_vues()

    toutes = scraper_bienici() + scraper_leboncoin() + scraper_pap()

    seen, propres = set(), []
    for a in toutes:
        if not a.get("url") or a["url"] in seen: continue
        seen.add(a["url"])
        a["valide"] = filtrer(a)
        if uid(a["url"]) not in vues:
            propres.append(a)
            vues.add(uid(a["url"]))

    log.info(f"📋 {len(propres)} nouvelles / {len(toutes)} total")
    generer_page(propres)
    sauvegarder_vues(vues)
    log.info("✅ Terminé.")

if __name__ == "__main__":
    main()
