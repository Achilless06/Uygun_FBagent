"""One-off: translate raw supplier product names into clean Georgian display names.

The catalog names are mixed "Georgian prefix + raw Turkish supplier tail"
("საბურავის ლატკა MR 10 RADYAL YAMASI") — the Turkish tail looks broken on the
public site. This script translates every product name in batches via
ClaudeClient (budget-tracked in api_spend), validates the results, and writes
the code→georgian mapping to assets/product_names_ka.json.

That JSON is committed to git; db.apply_name_ka_seed() applies it to any DB
(local dev + Railway prod) at startup, filling only NULL name_ka rows, so a
founder edit in /admin/products is never overwritten.

Usage:
    source .venv/bin/activate
    python -m scripts.georgianize_names            # translate codes missing from the JSON
    python -m scripts.georgianize_names --apply    # ...then backfill the local DB too
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config, db  # noqa: E402
from src.ai.claude_client import ClaudeClient  # noqa: E402

SEED_PATH = ROOT / "assets" / "product_names_ka.json"
BATCH_SIZE = 40
MAX_NAME_LEN = 120

# Turkish-specific letters must not survive into the Georgian display name.
_TURKISH_LETTERS = re.compile(r"[ıİğĞşŞçÇöÖüÜ]")
_GEORGIAN_CHAR = re.compile(r"[Ⴀ-ჿ]")
# SKU-ish tokens (A0, B0, M2, L3, MR-10, 4TS…) must be preserved verbatim.
_SKU_TOKEN = re.compile(r"^[A-Z]{1,4}[-/]?\d+[A-Z0-9./-]*$|^\d+[A-Z]{1,4}$")
# Brand lines from the writer-prompt glossary — verbatim in output.
_BRAND_TOKENS = {
    "VALCARN", "MLX", "MR", "MU", "BP", "BARS", "DIVORTEX", "AERO", "RAC", "KMAK",
}

SYSTEM = """შენ ხარ Uygun Georgia-ს (ბათუმი, ვულკანიზაციისა და ავტოქიმიის მომწოდებელი) \
კატალოგის რედაქტორი. მოგეწოდება პროდუქტების სია — კოდი და მომწოდებლის ნედლი სახელი \
(ხშირად ქართული დასაწყისი + თურქული ბოლო). დააბრუნე სუფთა ქართული საკატალოგო სახელები.

წესები:
1. პასუხი მხოლოდ ერთი JSON ობიექტია: {"კოდი": "ქართული სახელი", ...} — არც ერთი სხვა სიმბოლო.
2. არსებული ქართული ნაწილი შეინარჩუნე; თურქული/ინგლისური აღწერითი სიტყვები თარგმნე, \
ხოლო თუ იმეორებს ქართულ ნაწილს (მაგ. "... ლატკა ... YAMASI") — უბრალოდ წაშალე.
3. ბრენდის/სერიის კოდები (VALCARN, MLX, MR, MU, BP, BARS, DIVORTEX, AERO, RAC, KMAK, \
A0, B0, M2, L3, 4TS და მსგ.) და ყველა რიცხვი/ზომა — უცვლელად, ლათინურით.
4. საზომი ერთეულები CC / ML / GR / L / LT / KG — უცვლელად. თურქული რაოდენობის სუფიქსი \
("25 LI", "24 LU", "16 LI") ნიშნავს შეკვრას → "25 ცალი".
5. თურქული ასოები ლათინურ ტოკენებში → ASCII: BEST LİFT → BEST LIFT, 2000 KĞ → 2000 KG.
6. ტერმინები: "საბურავი" (არასდროს "სალტე") · patch = "ლატკა" · sheet = "ფურცელი".
7. წაშალე ნაგავი: სიტყვაზე მიწებებული "000" ბოლოში, "(ძირითადი საშუალება)", ზედმეტი ჰარები.
8. სახელი დარჩეს მოკლე, ფაქტობრივ საკატალოგო დასახელებად (≤70 სიმბოლო). არ გამოიგონო \
მახასიათებელი, რომელიც სახელში არ წერია. არ დაამატო ფასი ან ემოჯი.
9. თუ სახელი უკვე სუფთა ქართულია — დააბრუნე უცვლელად.

ლექსიკონი: CIVI/ÇİVİ=ლურსმანი · DELIK/DELIGI=ნახვრეტი · YAMA/YAMASI=ლატკა · \
RADYAL=რადიალური · TABAKA=ფურცლოვანი · OZEL=სპეციალური · SOLUSYON=ხსნარი · \
MAVI=ლურჯი · YESIL=მწვანე · KIRMIZI=წითელი · SIYAH=შავი · BEYAZ=თეთრი · \
SOKME TAKMA MAKINASI=მოხსნა-მონტაჟის დანადგარი · HAVA KOMPRESOR=ჰაერის კომპრესორი · \
TRANSPALET=ტრანსპალეტი · TWO POST LIFT=ორსვეტიანი ამწე.

მაგალითები:
- "საბურავის ლატკა MR 10 RADYAL YAMASI" → "საბურავის რადიალური ლატკა MR 10"
- "საბურავის ლატკა MU A0 CIVI DELIGI YAMASI000" → "ლურსმანის ნახვრეტის ლატკა MU A0"
- "წებო 1000CC SUPER VALCARN" → "წებო VALCARN SUPER 1000CC"
- "რეზინის ფურცელი L OVAL TABAKA YAMA 24 LU" → "რეზინის ოვალური ფურცლოვანი ლატკა L, 24 ცალი"
- "ამწე ურიკა (ძირითადი საშუალება) BEST LİFT 2000 KĞ TRANSPALET" → "ამწე ურიკა (ტრანსპალეტი) BEST LIFT 2000 KG"
- "14-56 SOKME. TAK. MAKINASI KMAK" → "საბურავის მოხსნა-მონტაჟის დანადგარი KMAK 14-56"
"""


def _clean_source(name: str) -> str:
    """Strip obvious import junk before translating/validating."""
    cleaned = re.sub(r"(?<=[A-Za-zႠ-ჿ])000$", "", name.strip())
    cleaned = cleaned.replace("(ძირითადი საშუალება)", " ")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _digit_runs(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def _required_tokens(source: str) -> set[str]:
    """Latin tokens that must survive translation verbatim."""
    required: set[str] = set()
    for tok in re.findall(r"[A-Z0-9./-]{2,}", source.upper()):
        tok = tok.strip(".-/")
        if not tok:
            continue
        if tok in _BRAND_TOKENS or _SKU_TOKEN.match(tok):
            required.add(tok)
    return required


def _validate(source: str, translated: str) -> list[str]:
    problems: list[str] = []
    t = translated.strip()
    if not t:
        return ["empty"]
    if len(t) > MAX_NAME_LEN:
        problems.append(f"too_long:{len(t)}")
    if not _GEORGIAN_CHAR.search(t):
        problems.append("no_georgian")
    if _TURKISH_LETTERS.search(t):
        problems.append("turkish_letters")
    up = t.upper()
    for run in _digit_runs(source):
        if run not in up:
            problems.append(f"lost_number:{run}")
    for tok in _required_tokens(source):
        if tok not in up:
            problems.append(f"lost_token:{tok}")
    return problems


def _translate_batch(
    claude: ClaudeClient, batch: list[tuple[str, str]]
) -> dict[str, str]:
    payload = json.dumps(
        [{"code": c, "name": n} for c, n in batch], ensure_ascii=False, indent=0
    )
    resp = claude.generate(
        system=SYSTEM,
        user=f"თარგმნე ეს {len(batch)} პროდუქტი:\n{payload}",
        operation="georgianize_names",
        max_tokens=4000,
    )
    raw = ClaudeClient.strip_json_fences(resp.text)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object, got {type(data)}")
    return {str(k): str(v).strip() for k, v in data.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="backfill local DB after translating")
    parser.add_argument("--limit", type=int, default=0, help="translate at most N products (0 = all)")
    args = parser.parse_args()

    cfg = config.load()
    db.init_engine(cfg.database_url)

    existing: dict[str, str] = {}
    if SEED_PATH.exists():
        existing = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    with db.session_scope() as s:
        products = [
            (p.code, p.name)
            for p in s.query(db.Product).order_by(db.Product.code_sort.asc().nullslast(), db.Product.code.asc()).all()
        ]

    todo = [(c, _clean_source(n)) for c, n in products if c not in existing and n and n.strip()]
    if args.limit:
        todo = todo[: args.limit]
    print(f"products={len(products)} already_translated={len(existing)} todo={len(todo)}")
    if not todo:
        if args.apply:
            print(f"applied_to_db={db.apply_name_ka_seed()}")
        return 0

    claude = ClaudeClient(cfg)
    failures: list[tuple[str, str, list[str]]] = []
    total_cost = 0.0

    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i : i + BATCH_SIZE]
        try:
            result = _translate_batch(claude, batch)
        except Exception as e:  # noqa: BLE001 — report and continue with next batch
            print(f"batch {i // BATCH_SIZE + 1}: FAILED ({e})")
            failures.extend((c, n, ["batch_error"]) for c, n in batch)
            continue

        for code, source in batch:
            translated = result.get(code, "")
            problems = _validate(source, translated)
            if problems:
                # One retry: ask for this single item with the problems spelled out.
                try:
                    single = _translate_batch(claude, [(code, source)])
                    translated = single.get(code, translated)
                    problems = _validate(source, translated)
                except Exception:
                    pass
            if problems:
                failures.append((code, source, problems))
                print(f"  SKIP {code}: {problems} :: {source!r} -> {translated!r}")
            else:
                existing[code] = translated

        # Crash-safe: persist after every batch, sorted for stable diffs.
        SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEED_PATH.write_text(
            json.dumps(dict(sorted(existing.items())), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"batch {i // BATCH_SIZE + 1}/{(len(todo) + BATCH_SIZE - 1) // BATCH_SIZE}: "
              f"ok={len(existing)} skip={len(failures)}")

    print(f"\ndone: translated={len(existing)} failed={len(failures)} seed={SEED_PATH}")
    if failures:
        print("failed codes:", ", ".join(c for c, _, _ in failures))
    if args.apply:
        print(f"applied_to_db={db.apply_name_ka_seed()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
