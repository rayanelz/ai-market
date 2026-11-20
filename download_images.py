"""Downloads a face picture for every card in ai-market-prices.csv.

Put this file in the SAME folder as ai-market-prices.csv and ai-market-prices.html, then run:
    python download_images.py

How it picks pictures
  1. Every card gets its OWN picture id (the resource id with the promo/version offset removed),
     so an Icon's Prime, Mid and Baby versions each get their own face, not a shared one.
  2. First pass: FIFA 21 pictures (SoFIFA, then FUTBIN).
  3. Second pass: anything still missing is searched in every other FIFA / FC game.
  4. If a version still has no picture of its own, it falls back to the player's shared picture (asset id).

Results go in the "images" folder next to the html. Safe to re-run (it skips files it already has).
Needs Python 3 and an internet connection.
"""
import csv, os, shutil, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "images")
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

def sofifa(year):
    def u(i):
        s = i.zfill(6)
        return f"https://cdn.sofifa.net/players/{s[:3]}/{s[3:]}/{year}_120.png"
    return u
def futbin(v):
    return lambda i: f"https://cdn.futbin.com/content/{v}/img/players/{i}.png"


# Aurora Heroes are brand-new cards whose own ids exist in no picture database.
# card (resource) id -> the player's real id, which FC 24 / FUTBIN / SoFIFA do have.
ALIAS = {
    "293201": "191972",   # David Ginola
    "293203": "167425",   # Abedi Pele
    "293204": "266690",   # Lucio
    "293205": "5454",     # Bixente Lizarazu
    "293206": "173210",   # Claudio Marchisio
    "293207": "16619",    # Ivan Cordoba
    "293208": "135455",   # Maicon (Douglas Sisenando)
    "293209": "180175",   # Alexandre Pato
    "293210": "44897",    # Jerzy Dudek
    "293211": "204550",   # Victor Ibarbo
}
FC24 = [sofifa(24), futbin("fifa24")]

PASS1 = [sofifa(21), futbin("fifa21")]
PASS2 = ([sofifa(y) for y in (24, 25, 26, 22, 23, 20, 19, 18, 17, 16, 15)] +
         [futbin(f"fifa{y}") for y in (24, 25, 26, 22, 23, 20, 19, 18, 17, 16, 15)])

def path_of(i): return os.path.join(OUT, f"{i}.png")
def have(i): return os.path.exists(path_of(i)) and os.path.getsize(path_of(i)) > 500

def try_sources(i, sources):
    if have(i): return True
    for src in sources:
        try:
            data = urllib.request.urlopen(urllib.request.Request(src(i), headers=HDR), timeout=15).read()
            if len(data) > 500:
                open(path_of(i), "wb").write(data)
                return True
        except Exception:
            continue
    return False

def run_pass(ids, sources, label):
    ids = [i for i in ids if not have(i)]
    print(f"{label}: {len(ids)} pictures to look for...", flush=True)
    with ThreadPoolExecutor(12) as ex:
        list(ex.map(lambda i: try_sources(i, sources), ids))

def main():
    os.makedirs(OUT, exist_ok=True)
    cards = []
    with open(os.path.join(HERE, "ai-market-prices.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            res = r["resource_id"]
            base = ALIAS.get(res) or str(int(res) & 0xFFFFFF)   # strips the version/promo offset (or uses the real player id)
            cards.append((r["player"], r["card_type"], res, base, r["asset_id"]))

    ids = list(dict.fromkeys([c[3] for c in cards] + [c[4] for c in cards]))
    run_pass(list(ALIAS.values()), FC24, "Pass 0 (FC 24, for the Aurora Heroes)")
    run_pass(ids, PASS1, "Pass 1 (FIFA 21)")
    run_pass(ids, PASS2, "Pass 2 (other FIFA/FC games)")

    exact = shared = missing = 0
    shared_list, missing_list = [], []
    for player, ctype, res, base, asset in cards:
        if have(base): pick = base; exact += 1
        elif have(asset): pick = asset; shared += 1; shared_list.append(f"{player} | {ctype} | {res}")
        else: missing += 1; missing_list.append(f"{player} | {ctype} | {res}"); continue
        if pick != res:                                # the page looks for images/<resource_id>.png first
            shutil.copyfile(path_of(pick), path_of(res))

    print(f"\n{len(cards)} cards: {exact} with their own picture, {shared} using the player's shared picture, {missing} with no picture.")
    for name, lst in (("shared_picture_cards.txt", shared_list), ("missing_picture_cards.txt", missing_list)):
        if lst:
            open(os.path.join(HERE, name), "w", encoding="utf-8").write("\n".join(lst))
            print(f"  list saved to {name}")

if __name__ == "__main__":
    main()
