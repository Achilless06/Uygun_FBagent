"""Reclassify all products into a clean Georgian-only taxonomy.

Reads every product from the DB, maps it to ONE of 23 Georgian categories based
on keyword + regex rules (priority-ordered), and updates the `category` column.

Run:
    python scripts/recategorize_products.py            # dry run, print plan
    python scripts/recategorize_products.py --apply    # actually write to DB
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "uygun.db"

# ─── Categories (priority order — first match wins) ────────────────────────
# Each entry: (category_name, [list of regex patterns OR plain substrings])
# Substrings are matched case-insensitively. Regex must start with "re:".

CATEGORIES: list[tuple[str, list[str]]] = [
    # ── Tire patches (საბურავის ლატკები) ──
    ("საბურავის ლატკები", [
        "საბურავის ლატკა",
        "re:\\bRAC\\s+\\d+\\s+YAMA",
        "re:\\d+\\s*NO\\s+TIPTOP",
        "re:TIPTOP\\s+T\\s*TIP",
        "re:MBT\\s+\\d+.*CHAMPION",
        "re:PRO\\s+\\d+(\\.\\d+)?\\s+CIVI",
    ]),

    # ── Rubber patches (რეზინის ფირფიტები) ──
    # Includes rubber bands & repair strips (KAUCUK BANT / KUSINGAM).
    ("რეზინის ფირფიტები", [
        "რეზინის ფირფიტა",
        "რეზიის ფირფიტა",  # typo in DB
        "რეზინის ფირფიტები",
        "რეზინის ფურცელი",
        "რეზინის ფურცლები",
        "რეზინის ლენტი",
        "KAUCUK BANT",
        "KAUCUK KUSINGAM",
        "KUSINGAM",
        "kucuk kusingam",
        "re:\\bMLX\\s+(UR|RD|BP)",
        "re:\\bGAV\\s+(R|T|KO)\\s*\\d",
        "re:RUZ?I\\s+M[DR]R",
        "re:UZI\\s+MRR",
        "re:MT\\s+\\d+\\s+CHAM[OP]ION",
        "re:CHAMP[İI]ON\\s+(GUT|UP|MT)",
        "re:R0[34]-YUVARLAK",
        "BP1 YAMA",
        "MLX BP",
    ]),

    # ── Glue & solutions (წებო და ხსნარები) ──
    ("წებო და ხსნარები", [
        "წებო",
        "VALCARN",
        "CEMENT SOLUSYON",
        "CEMENT BETA",
        "OZEL MAVI CEMENT",
        "OZEL MAVİ CEMENT",
        "MONTAJ KREMI",
        "MONTAJ KREMİ",
        "KANGURU PASTE",
        "MDF KIT",
        "წებოს გამამყარებელი",
        "წებოვანი კვალის მოსაშორებელი",
        "Adhesive Remover",
    ]),

    # ── Tire repair plugs/cords (საბურავის ფითილები) ──
    # Match BEFORE valves so "ფითილი" plug isn't mistaken for anything else.
    # Exclude FITIL ATMA (insertion tool — goes to hand tools).
    ("საბურავის ფითილები", [
        "საბურავის ფითილი",
        "რეზინის ფითილი",
        "re:LASTIK\\s+TAMIRI?\\s+FITILI",
        "re:F[İI]T[İI]L\\s+USA",
        "FITIL ATMA",  # but we'll re-route this below — see special case
    ]),


    # ── Tire valves (საბურავის სარქველები) ──
    ("საბურავის სარქველები", [
        "სარქველი",
        "პიპკა",
        "re:\\bSUBAP\\b(?!\\s+(IGNESI|CEKECEGI|PAFTASI))",
        "re:\\bTR\\s+\\d+",
        "re:PVR\\s+\\d+",
        "PIPO SUBAP",
        "ŞOKLAMA SUBABI",
        "TRJ ",
        "ALUMINYUM JANT SUBAP",
        "JUMBO DORSE SUBAP",
        "TRAKTÖR İLAVE SUBAP",
        "ILAVE SUBAP",
        "OTOBUS-KAMYON DUBLEKS",
        "MOTORSIKLET SUBAP",
        "DUBLEKS SUBAP",
        "TAKSI SUBAP",
        "TRAKTOR SUBAP",
        "TRAKTOR DUBLEKS",
        "HORTUMLU ILAVE SUBAP",
        "PLASTIK ILAVE SUBAP",
        "METAL SUBAP ILAVESI",
        "გამაგრძელებელი სარქველი",
    ]),

    # ── Pneumatic tools (პნევმატური ხელსაწყოები) ──
    # Match BEFORE general hand tools so HAVALI* doesn't fall to ხელის.
    # But ქანჩის გასაღების HAVALI LOKMA must go to ქანჩები first.
    ("პნევმატური ხელსაწყოები", [
        "ხელის პნევმატური",
        "ხელის პლევმატური",  # typo in DB
        "პნევმატური ქანჩის მოსაჭერი",
        "ჰერის ფისტოლეტი",
        "ჰაერის ფისტოლეტი",
        "ჰაერის პისტოლეტი",
        "HAVA TABANCASI",
        "HAVA VURMA TABANCASI",
        "HAVA VURMA UCU",
        "MAZOT TABANCASI",
        "SAPPOWER",
        "KUKEN",
        "KALIPCI TASLAMA",
        "KALIPÇI TAŞLAMA",
        "SARTLANDIRICI",
        "გამშხეფი",
        "HAVALI GRES CIHAZI",
        "HAVA UC MANDALI",
        "HAVA JAKI",
        "ჰაერის გასაბერი ტუმბო",
        "სახეხი ინსტრუმენტი",
        "ჰაერის გადამყვანი",
        "ხელის პნევმატური ინსტრუმენტი",
        "HAVALI SOMUN SOKME",
        "HAVALI SOMUN SÖKME",
        "HAVALI SOMUN SUKME",
        "HAVALI SOMUN",
        "re:GAV\\s+(AT|9981|241|285)",
        "re:OSC?\\s*5\\d{3}\\s+OSACAR",
        "OSACAR",
        "POMPASI",  # ზეთის ამოსაქაჩი ტუმბო etc
    ]),

    # ── Nuts & wrenches (ქანჩები და გასაღებები) ──
    ("ქანჩები და გასაღებები", [
        "ქანჩი",
        "ქანჩის გასაღები",
        "ქანჩის გასაღების",
        "ქანჩის გასარების",  # typo
        "BIJON ANAHTARI",
        "HAVALI LOKMA",
        "HAVALI LOMKA",
        "ANAHTARI",
        "LOKMA",
        "LOMKA",
        "ADAPTORU ქანჩის",
        "ADAPTORU",
        "ლითონის ქანჩი",
        "ISTAVROZ BIJON",
    ]),

    # ── Hand tools (ხელის ხელსაწყოები) ──
    ("ხელის ხელსაწყოები", [
        "ხელის ინსტრუმენტი",
        "ხელის ხელსაწყო",
        "LASTIK LEVYESI",
        "LASTİK LEVYESI",
        "LEVYESI",
        "FITIL ATMA",
        "KANAL ACICI",
        "YAMA MAKARASI",
        "T TIP SUBAP PAFTASI",
        "TORNAVIDA PAFTA",
        "ბრტყელტუჩა",
        "საბურავის ფანქარი",
        "LASTIK TEBESIRI",
        "TEBESIRI",
        "SAPLI TAS",
        "BEYAZ KOPUK TAS",
        "RASPA TASI",
        "GRIT RASPA",
        "DIS ACMA BICAGI",
        "DIŞ ACMA",
        "სალესი ქვა",
        "საპრიალებელი ქვა",
        "SUBAP IGNESI SOKECEGI",
        "SUBAP IGNESI",
        "SUBAP CEKECEGI",
        "SIS YEDEK UC",
        "ჩამკეტი სარქველი",
        "მანტიროვკა",
        "საბურავის დასაშლელი",
        "KAMYON LASTIGI SOKME DUBLEKS APARATI",
        "PLUS APARATI",
        "PLUS APARATI ATEK",
    ]),

    # ── Jacks (დომკრატები) ──
    ("დომკრატები", [
        "დომკრატი",
        "დონგრატი",  # typo
        "დომკრატის",
        "KRIKO",
        "KRİKO",
        "HIDROPNOMATIK ARABALI",
        "TWO POST LIFT",
        "DIKEY SANZUMAN",
        "ამწე ურიკა",
        "TRANSPALET",
        "NET LİFT",
        "BEST LİFT",
        "HIDROLIK KILITLI LIFT",
        "ჰიდრავლიკური ამწე",
        "ჰიდრავლიკური მოძრავი ჯეკი",
        "ჰიდრავლიკური დომკრატის",
        "HIDROLIK KRIKO",
        "ჰაერის დომკრატის ჩამკეტი",
    ]),

    # ── Tire equipment (საბურავის დანადგარები) ──
    ("საბურავის დანადგარები", [
        "ბალანსის დანადგარი",
        "ბალანსირების დანადგარი",
        "მაბალანსირებელი დანადგარი",
        "საბურავის ბალანსირების",
        "BALANS MAKİNASI",
        "BALANS MAKINASI",
        "BALANS MAKINA",
        "BALANS MAKİNA",
        "SOKME TAKMA",
        "SÖKME TAKMA",
        "SOKME TAK",
        "SÖKME TAK",
        "JANT DUZELTME",
        "JANT DÜZELTME",
        "JANT DÜZELTME FLANŞI",
        "TYRE CHANGER",
        "ECO-SWING",
        "MOBIL ALLEGRO",
        "ZANINI",
        "BRAVA",
        "SPEEDY",
        "ATEK",
        "SIRION",
        "SİRİON",
        "MESSMATIC",
        "MESSMATİC",
        "UNITROL",
        "KMAK",
        "MAXI RIM PRESS",
        "MAXI TYRE",
        "დამშლელ ამწყობი",
        "დამშლელ-ამწყობი",
        "დასაშლელ-ასაწყობი",
        "დასაშლელი დანადგარი",
        "ამწყობი დანადგარი",
        "გასასწორებელი დანადგარი",
        "დისკის გასასწორებელი",
        "რკინის დისკის გასასწორებელი",
        "სატვირთო საბურავის",
        "სახარატო ჩარხი",
        "DISK TORNA",
        "LASTİK YANAK AÇMA",
        "UTU REZISTANSI",
        "DIS SALTIK KAYNAK",
        "DIS SALTIK",
        "საბურავის შესადუღებელი უთო",
        "საბურაის საკერი უთო",
        "ALUMINYUM DISLI",  # changer part
        "OTOMOTIVLASTIKSANAYI",
        "ROLLER MAXI",
    ]),

    # ── Air compressors (ჰაერის კომპრესორები) ──
    ("ჰაერის კომპრესორები", [
        "ჰაერის კომპრესორი",
        "ჰაერის საშრობი",
        "კომპრესორის ნაწილი",
        "კომპრესორის ნაწილ",  # truncated in DB
        "HAVA KOMPRESORU",
        "HAVA KOMPRESÖRÜ",
        "HAVA KOMPRESOR",
        "HAVA KOMPRESÖR",
        "HAVA KURUTUCUSU",
        "KOMPRESÖR KAFASI",
        "KOMPRESÖR",
        "KOMPRESOR",
        "VİDALI HAVA",
    ]),

    # ── Pressure washers (წყლით რეცხვის მოწყობილობები) ──
    ("წყლით რეცხვის მოწყობილობები", [
        "წყლით რეცხვის",
        "YIKAMA MAKİNASI",
        "YIKAMA MAKINESI",
        "BASINCLI YIKAMA",
        "JETONLU YIKAMA",
        "JETONLU",
        "re:\\d+\\s+BAR\\s+(SOGUK\\s+)?BASINCLI",
        "YIKAMA TABANCASI",
        "სარეცხი პისტოლეტი",
        "TETIKSIZ YIKAMA",
        "წყლით რეცხვის მოწყობილობის პისტოლეტი",
    ]),

    # ── Hoses & fittings (შლანგები და ფიტინგები) ──
    # Includes O-rings (sealing components used with fittings).
    ("შლანგები და ფიტინგები", [
        "შლანგი",
        "რეზინის მილი",
        "ORING",
        "ORİNG",
        "შუასადები",
        "HORTUM",
        "HAVA HORTUM",
        "KAPLIN",
        "ფიტინგი",
        "ლითონის ფიტინგი",
        "ლითონის ხამუთი",
        "HORTUM KELEPCESI",
        "MAKARALI HORTUM",
        "MAKARALI HAVA",
        "PUMA MAKARALI",
        "HAVA SAATI ICIN YEDEK HORTUM",
        "ჰაერის გამანაწილებელი",
        "DAGITICI",
        "HAVA DAGITICI",
        "STOPER GOVDE",
        "STOPER GÖVDE",
        "KAPLIN ICIN UC",
        "HORTUM ICIN STOPER",
        "HORTUM UC STOPER",
        "ERKEK STOPER",
        "DİŞİ STOPER",
        "DISI KAPLIN",
        "ERKEK KAPLIN",
    ]),

    # ── Balance weights (ბალანსირების ტყვია) ──
    ("ბალანსირების ტყვია", [
        "ტყვიის ნაწარმი",
        "BALANS AGIRLIGI",
        "BALANS AĞIRLIĞI",
        "BALANS KURSUN",
        "KAMYON YAPIŞTIRMA",
        "KAMYON YAPISTIRMA",
        "TURBO BALANS",
        "NORMAL BALANS",
        "სხმული პირწონა",
        "YAPISTIRMA BALANS",
        "BALANS AGI",
    ]),

    # ── Polish (საპრიალებელი საშუალებები) ──
    ("საპრიალებელი საშუალებები", [
        "საპრიალებელი",
        "გასაპრიალებელი",
        "LASTIK PARLATICI",
        "PARLATICI",
        "TORPIDO BAKIM",
        "Tire Shiner",
        "RED SHINE",
        "GUMUS REFRES",
        "Dashboard Maintenance",
        "Blue Edition Trim Care",
        "TRIM CARE",
        "ტორპედოს საპრიალებელი",
        "საბურავის და პლასტმასის საპრიალებელი",
        "პლასტმასის გასაშავებელი",
    ]),

    # ── Wash chemicals (სარეცხი საშუალებები) ──
    # Match before cleaning chems so "სარეცხი საშუალება CARWASH..." goes here.
    ("სარეცხი საშუალებები", [
        "სარეცხი საშუალება",
        "CARWASH",
        "ACTV.FOAM",
        "FIRCASIZ OTO YIKAMA URUNU",
        "OTO YIKAMA URUNU",
        "ACTV.FOAM CARW",
        "KOPUK SARI",
        "KOPUK YESIL",
        "KOPUK YEISL",
        "FOAM CARW",
        "მანქანის სარეცხი ქაფი",
        "მანქანი სარეცხი ქაფი",  # typo
    ]),

    # ── Air fresheners (არომატიზატორები) ──
    ("არომატიზატორები", [
        "არომატიზატორი",
        "KLIMA FRESH",
        "OTO PARFUMU",
        "OTO PARFÜMÜ",
        "FELICE",
        "BASIS CAR",
        "GENIS ALAN KOKUSU",
        "ODOR GUARD",
        "ALU. KLIMA FRESH",
        "ALU. KLIMA",
    ]),

    # ── Fuel & engine additives (საწვავის და ძრავის დანამატები) ──
    ("საწვავის და ძრავის დანამატები", [
        "YAKIT KATKISI",
        "ბენზინის საწვავის დანამატი",
        "დიზელის საწვავის დანამატი",
        "EKONOMIZER",
        "ეკონომაიზერი",
        "MOTOR YAG SIZINTI",
        "ძრავის ზეთის გაჟონვის",
        "LIFTER KATKISI",
        "ჰიდრავლიკური ამწე ზეთის დანამატი",
        "RADYATOR CATLAK",
        "RADYALTOR REMIZLEYICI",
        "რადიატორის გასარეცხი სითხე",
        "რადიატორიდან წყლის გაჟონვის",
        "PARTIKUL FILTRE TEMIZLEME",
        "PATRIKUL FILTRE TEMIZLEME",
        "ფილტრის საწმენდი დანამატი",
        "ENJEKTOR TEM",
        "ENJEKTOR TEMIZLEME",  # additive context
        "ინჟექტორის საწმენდი დანამატი",
        "ინჯექტორის საწმენდი დანამატი",
        "სილიკონის სპრეი",  # silicon spray — engine maintenance
        "SILIKON SPREY",
        "ZINCER HALAT YAGLAMA",
        "შესაზეთი სპრეი",
        "GRES SPREYI",
        "თხევადი ცხიმიანი სპრეი",
        "ჯაჭვის და რემნის შესაზეთი",
        "ცხიმოვანი დანამატი",
        "AERO EP KATKILI",
        "MOS2 GUCLI PAS SOKUCU",
        "MOS2 PAS SOKUCU",
        "PAS SOKUCU",
        "POS SOKUMU",
        "ჟანგის საწინააღმდეგო სპრეი",
        "PASLAMAZ BAKIM",
        "უჟანგავი მოვლის",
        "COK AMACLI BAKIM",
        "მრავალფუნქციური მოვლის",
        "BUZ COZUCU",
        "ყინულის მოსაშორებელი",
        "AERO LASTIK TAMIR KITI",
        "საბურავის გასაბერი სპრეი",
        "აღდგენითი სპრეი",
        "ზეთისა და კვამლის",
        "YAG VE DUMAN KESICI",
    ]),

    # ── Cleaning chemicals (საწმენდი საშუალებები) ──
    ("საწმენდი საშუალებები", [
        "გამწმენდი",
        "საწმენდი",
        "TEMIZLEME",
        "TEMIZLEYICI",
        "TEMIZLE",
        "KARBURATOR",
        "FULL CLEAN MOTOR",
        "MOTOR ICI TEMIZLEME",
        "MOTOR TEMIZLEME",
        "KLIMA TEMIZLEME",
        "EKRAN TEMIZLEME",
        "KONTAK TEMIZLEME",
        "EGR TEMIZLEME",
        "FREN BALATA TEMIZLEME",
        "FREN BALATA",
        "MOTOSIKLET ZINCER TEMIZLEME",
        "VORTEX MOTOR TEMIZLEME",
        "ZAGSIZ KONTAK",
        "YAGSIZ KONTAK",
        "YAGLI KONTAK",
        "სამუხრუჭე ბალიშის საწმენდი",
        "ჯაჭვის გამწმენდი",
        "ეკრანის საწმენდი",
        "კონდინციონერის საწმენდი",
        "ძრავის გასარეცხი",
        "ძრავის საწმენდი",
        "ძრავის საწმედი",  # typo
        "ნავთობის საკონტაქტო",
        "უცხიმო გამწმენდი",
        "უცხიმო  გამწმენდი",
        "სალონის საწმენდი",
        "ტორპედოს საწმენდი",
        "TORPIDO BAKIM SUTU",
        "დასუფთავების",
        "MIKROFIBER",
        "GUDERI BEZ",
        "საწმენდი ტილო",
        "Cleaner Spray",
        "All Purpose Cleaner",
        "JANT TEMIZLEME",
        "დისკის საწმენდი",
        "უნივერსალური საწმენდი",
        "AERO MOTOR TEMIZLEME",
        "AERO ENJEKTOR TEMIZLEME",
        "AERO KARBURATOR",
        "AERO KONTAK",
        "AERO EKRAN",
        "AERO MOTOR ICI",
    ]),

    # ── Measuring tools (საზომი ხელსაწყოები) ──
    ("საზომი ხელსაწყოები", [
        "მანომეტრი",
        "წნევის საზომი",
        "ა/მ საბურავის წნევის საზომი",
        "საზომი ხელსაწყო",
        "HAVA SAATI",
        "DİJİTAL HAVA",
        "GOSTERGELI",
        "GÖSTERGELI",
        "TG 18",
        "MEHAK",
        "CKB-700",
        "AT-7800",
    ]),

    # ── Misc accessories (სხვა აქსესუარები) — fallback ──
    ("სხვა აქსესუარები", [
        # caps & containers
        "ხუფი",
        "KAPAK",
        "SUBAP KAPAĞI",
        "SUBAP KAPAGI",
        "FISFIS",
        "ჭურჭელი",
        "ბოთლი",
        "Plastic Bottle",
        # other accessories
        "FENER",
        "GUC KAYNAGI",
        "უწყვეტი კვების წყარო",
        "KAYIS",
        "რეზინის ღვედი",
        "ACMA KAPAMA",
        "გადამრთველი",
        "ETIKET",
        "წებოვანი ეტიკეტი",
        "ბალანსის აპარარტი",  # typo, balance machine (could be equipment but typo)
        "ბალანსის აპარატი",
        "ლითონის ტევადობა",
        "ლითონის სადგამი",
        "KATLAMALI SEHPA",
        "KOPUK SIVI",
        "SOKLAMA TUPU",
        "BASINC SARTEL",
        "დნობადი მცველი",
        "სალონის",
        "ინსტრუმენტების ყუთი",
        "ALET CANTASI",
        "OTO KUAFOR SUPURGE",
        "მტვერსასრუტი",
        "SÜPÜRGE",
        "ტუმბოს ნაწილი",
        "GRES POMPA UCU",
        "საპოხი დანადგარი",
        "საპოხი აპარატი",
        "HAVALI GRES",
        "FENER MILI",
        "ავტომატიზირებული მოწყობილოების ნაწილი",
        "BALANCE MACHINE",  # has typos; fallback
        "ბალანსირების ჩაქუჩი",
        "BALANS KURSUN CEKICI",
        "AHTAPOT",
        "ცხელი ჰაერის გენერატორი",
        "PLASTIK KELEPCE",
        "პლასტმასის ხამუთი",
        "პლასტმასის ნაწარმი",
        "პლასტმასის გამაგრძელებელი",
        "DOMKRATIS NAWILI",
        "CEKVALF KRIKO",
    ]),
]


def normalize(s: str) -> str:
    """Strip and uppercase for case-insensitive matching."""
    return s.strip()


def classify(name: str) -> str | None:
    """Return the matching category name, or None if no rule matched."""
    if not name:
        return None
    n = normalize(name)
    n_upper = n.upper()
    for cat, patterns in CATEGORIES:
        for pat in patterns:
            if pat.startswith("re:"):
                if re.search(pat[3:], n, re.IGNORECASE):
                    return cat
            else:
                if pat.upper() in n_upper:
                    return cat
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to DB (default: dry run).")
    parser.add_argument("--show-unmatched", action="store_true",
                        help="Print products that don't match any category.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, name, category FROM products ORDER BY code")
    rows = cur.fetchall()

    counts: Counter[str] = Counter()
    unmatched: list[tuple[str, str]] = []
    changes: list[tuple[str, str, str | None, str]] = []  # code, name, old, new

    for code, name, old_cat in rows:
        new_cat = classify(name)
        if new_cat is None:
            counts["(unmatched)"] += 1
            unmatched.append((code, name))
            new_cat = "სხვა აქსესუარები"  # fallback
        counts[new_cat] += 1
        if new_cat != old_cat:
            changes.append((code, name, old_cat, new_cat))

    print(f"\n=== Classification plan ({len(rows)} products) ===\n")
    for cat, _ in CATEGORIES:
        print(f"  {counts.get(cat, 0):4d}  {cat}")
    if counts.get("(unmatched)"):
        print(f"  {counts['(unmatched)']:4d}  (fell through → სხვა აქსესუარები)")

    if args.show_unmatched and unmatched:
        print(f"\n=== Unmatched (fell through, n={len(unmatched)}) ===")
        for code, name in unmatched[:50]:
            print(f"  {code:8s}  {name}")
        if len(unmatched) > 50:
            print(f"  ... and {len(unmatched) - 50} more")

    print(f"\n=== Would change: {len(changes)} products ===")
    if not args.apply:
        print("\n(Dry run. Re-run with --apply to write to DB.)")
        return 0

    print("\nApplying...")
    for code, name, old, new in changes:
        cur.execute("UPDATE products SET category = ? WHERE code = ?", (new, code))
    conn.commit()
    print(f"✓ Updated {len(changes)} products.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
