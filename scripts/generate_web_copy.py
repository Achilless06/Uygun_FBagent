"""One-shot: have Gemini write all Georgian website copy.

Run when you want to refresh the site's wording:

    python -m scripts.generate_web_copy

The script:
  1. Builds a strict system prompt using the brand voice rules + banned phrases
     from src/brand.py and src/ai/prompts.py.
  2. Asks Gemini for ONE JSON object containing every copy slot the site needs.
  3. Validates the JSON has all expected keys (warns if any missing).
  4. Writes src/web/copy.py as a Python module of string constants.
  5. Restart the bot to pick up the new copy.

Cost: one Gemini call (~$0.005). Cached automatically via api_spend table.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from src import brand, config, db
from src.ai.gemini_client import GeminiClient
from src.logging_setup import configure as configure_logging
from src.logging_setup import get_logger

log = get_logger(__name__)

# Every copy slot the website templates expect. Keep keys in sync with src/web/copy.py.
EXPECTED_KEYS: dict[str, str] = {
    # Hero
    "hero_eyebrow": "3-5 სიტყვა, ბრენდის ფარგლები. გამოჩნდება უპერკეისით.",
    "hero_heading_1": "ერთი სიტყვა, ფარდობითი ცნება (ვიზუალურად ფერმკრთალი).",
    "hero_heading_2": "ერთი სიტყვა, hero_heading_1-ის წყვილი (ვიზუალურად მთავარი). მაგ. 'ხარისხი/სიჩქარე', 'მტკიცე/სანდო'.",
    "hero_subtitle": "12-18 სიტყვა. უნდა ჩავტიო '480+ პროდუქცია' და 'უფასო მიწოდება'. დაიწერე ნატურალურად, არა 'შეარჩიე...და ისარგებლე' სტილში.",
    "cta_primary": "1-2 სიტყვა, კატალოგზე გადასაყვანი ღილაკი (მაგ: 'პროდუქცია' ან 'კატალოგი').",
    "cta_secondary": "1-2 სიტყვა, ზარის CTA (მაგ: 'დაგვირეკე' ან 'მოგვწერე').",

    # Values section
    "values_eyebrow": "1-2 სიტყვა — რა მოდის ქვემოთ.",
    "values_title_line_1": "3-5 სიტყვა, headline-ის პირველი ხაზი.",
    "values_title_line_2": "3-5 სიტყვა, მეორე ხაზი (გრძელდება line_1-დან). მაგ: 'ბიზნესის შეუფერხებელი მუშაობისთვის'.",
    "values_intro": "1 წინადადება (15-25 სიტყვა). რას ვაკეთებთ მოკლედ. არ ახსენო 'ბათუმიდან', 'ვამარაგებთ მთელ საქართველოს' კი არა, უფრო ცოცხალი ფრაზა.",

    # Three customer-facing value cards (NOT internal AI rules — these go on the public landing page).
    # Each card: title (1-2 words), body (1 short sentence, 10-15 words, შენ-ფორმაში სადაც გამოდის).
    # სტილი: მოკლე, კონკრეტული, წარდგენილი როგორც BENEFIT to მომხმარებლისთვის. არანაირი მონოლოგი
    # AI-ის ხმაში, არანაირი '=', არანაირი ფრჩხილიანი ახსნა.
    "value_1_title": "1-2 სიტყვა. value pillar #1 (მაგ: 'მარაგი' ან 'სიჩქარე').",
    "value_1_body": "ერთი მოკლე წინადადება, 10-14 სიტყვა. რა ხდება მომხმარებლისთვის.",
    "value_2_title": "1-2 სიტყვა. value pillar #2 (განსხვავებული პირველისგან).",
    "value_2_body": "ერთი მოკლე წინადადება, 10-14 სიტყვა.",
    "value_3_title": "1-2 სიტყვა. value pillar #3.",
    "value_3_body": "ერთი მოკლე წინადადება, 10-14 სიტყვა.",

    # Featured products section
    "featured_eyebrow": "1-2 სიტყვა.",
    "featured_title": "2-4 სიტყვა — სათაური 'რა მოდის ქვემოთ'-ისთვის.",
    "featured_cta": "2-3 სიტყვა — link ყველა პროდუქციაზე.",

    # Posts section
    "posts_eyebrow": "1-2 სიტყვა (მაგ: 'სიახლეები').",
    "posts_title": "2-4 სიტყვა.",
    "posts_cta": "2-3 სიტყვა.",

    # CTA strip
    "cta_strip_eyebrow": "1-3 სიტყვა.",
    "cta_strip_title_1": "3-5 სიტყვა, headline-ის პირველი ხაზი.",
    "cta_strip_title_2": "3-5 სიტყვა, მეორე ხაზი (ვიზუალურად მონაცრისფრო — გასარკვევ-დასაბოლოვებელი).",
    "cta_strip_body": "1-2 წინადადება (20-35 სიტყვა). რა მოხდება დარეკვის შემდეგ.",

    # Footer
    "footer_tagline": "1 წინადადება (8-15 სიტყვა). ბრენდის lead-line, არა marketing speak.",

    # Products page
    "products_page_eyebrow": "1 სიტყვა.",
    "products_page_title": "1-2 სიტყვა (მაგ: 'პროდუქცია').",

    # Posts page
    "posts_page_eyebrow": "1-2 სიტყვა.",
    "posts_page_title": "1-3 სიტყვა.",

    # Contact page
    "contact_page_eyebrow": "1 სიტყვა.",
    "contact_page_title_1": "2-3 სიტყვა.",
    "contact_page_title_2": "2-3 სიტყვა (ვიზუალურად მონაცრისფრო, line_1-ის გაგრძელება).",
    "contact_delivery_title": "1-3 სიტყვა.",
    "contact_delivery_body": "1 წინადადება (10-20 სიტყვა) — როგორ მუშაობს მიწოდება.",
}


SYSTEM_PROMPT = f"""\
შენ ხარ Uygun Georgia-ს ვებსაიტის კოპირაიტერი. ბრენდი არის ბათუმში
დაფუძნებული ვულკანიზაცია/ავტოსამრეცხაოს ქიმიის მომმარაგებელი.

ბრენდის მისია:
{brand.MISSION}

ხმის წესები (აუცილებელია, გადახვევა აკრძალულია):
1. ყოველთვის "შენ" ფორმა მომხმარებლისთვის. "თქვენ" — არასოდეს.
   "ჩვენ" დასაშვებია მხოლოდ ბრენდის თვითაღწერისთვის (მაგ: 'ჩვენი მაღაზია').
2. არასოდეს გამოიყენო [placeholder] ან გაცვეთილი ფრაზა.
3. აკრძალული ფრაზები: {', '.join(repr(p) for p in brand.BANNED_PHRASES)}.
4. "საბურავი" (არა "სალტე").
5. არასოდეს მოიგონო ფასი.
6. ციფრები რეალური უნდა იყოს: 480+ პროდუქცია, +995 568 90 90 87, მამია ვარშანიძის 189.

ტექსტის ხარისხის წესები (კრიტიკული — წინა ვერსიამ ვერ მოახერხა):
A. ნუ წერ AI-ის სუნით. "შეარჩიე...და ისარგებლე უფასო მიწოდებით" — ეს ცუდია.
   ცოცხალი ფრაზა: "480+ პროდუქცია მარაგში — დაგვირეკე, გავაგზავნოთ".
B. გრძელი, ფორმალური წინადადებები აკრძალულია. მოკლე, კონკრეტული, შენ-ფორმაში.
C. არ ჩაწერო შინაგანი ლოგიკა ან მსჯელობა (მაგ: 'ცუდი შეკეთება = ავარია'),
   არც განმარტებები ფრჩხილებში. პირდაპირ ბენეფიტი მომხმარებლისთვის.
D. არ გამოიყენო ემოჯი (ის HTML-ში ცალკე ჩაიდება).
E. არ გამოიყენო "—" შუა-წინადადებაში, თუ ნამდვილად სასინტაქსოდ არ ჭირდება.
   "დარეკე — გვითხარი — გავაგზავნოთ" სტილი ცუდია.
F. შესახვევი ფრაზები ცუდია ('მაგრამ შენ ფორმაში'). მარტივად დაწერე.
G. value cards არის SITE VISITOR-ისთვის, არა AI-სთვის. დაიწერე ისე, თითქოს
   მომხმარებელი კითხულობს — რა მისთვის სარგებელია.

დააბრუნე მხოლოდ ერთი ვალიდური JSON ობიექტი — სხვა არაფერი, არანაირი
დამატებითი ტექსტი ან კოდის ბლოკი. ყველა მნიშვნელობა ქართულად.
"""


def build_user_prompt() -> str:
    slot_lines = "\n".join(f'  - "{k}": {v}' for k, v in EXPECTED_KEYS.items())
    return textwrap.dedent(f"""\
        დაწერე ვებსაიტის ყველა ტექსტი. დააბრუნე ერთი JSON ობიექტი ზუსტად
        ამ keys-ით (ყველა აუცილებელია):

        {slot_lines}

        წესი: მთლიანი output-ი უნდა იყოს ერთი ვალიდური JSON ობიექტი {{...}}.
        არანაირი ```json ფრაგმენტი, არანაირი კომენტარი წინ ან უკან.
        """)


def parse_json_strict(text: str) -> dict:
    """Strip code-fence wrappers if Gemini added them, then json.loads."""
    t = text.strip()
    if t.startswith("```"):
        # ```json\n{...}\n``` → {...}
        t = t.strip("`")
        # First line might be "json"
        first_nl = t.find("\n")
        if first_nl != -1 and t[:first_nl].strip().lower() in ("json", ""):
            t = t[first_nl + 1 :]
        if t.endswith("```"):
            t = t[:-3]
    return json.loads(t.strip())


def write_copy_module(data: dict, out_path: Path) -> None:
    """Render data into src/web/copy.py as Python string constants."""
    lines = [
        '"""Georgian website copy — generated by scripts/generate_web_copy.py.',
        "",
        "Re-run that script to refresh. Manual edits here are fine but will be",
        "overwritten on next regeneration — bake your preferred wording into the",
        "Gemini prompt at scripts/generate_web_copy.py if it should stick.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for key in EXPECTED_KEYS:
        value = data.get(key, "")
        if not value:
            log.warning("copy_missing_key", key=key)
            value = ""
        # Use a safely-escaped triple-quoted form for multi-line strings; single line for short.
        if "\n" in value or '"' in value or len(value) > 80:
            escaped = value.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
            lines.append(f'{key.upper()} = """{escaped}"""')
        else:
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'{key.upper()} = "{escaped}"')
    lines.append("")  # trailing newline
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("copy_module_written", path=str(out_path), keys=len(EXPECTED_KEYS))


def main() -> int:
    configure_logging("INFO")
    cfg = config.load()
    db.init_engine(cfg.database_url)
    db.create_all()

    gemini = GeminiClient(cfg)

    log.info("copy_generation_start", model=cfg.gemini_text_model, slots=len(EXPECTED_KEYS))
    response = gemini.generate(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(),
        operation="generate_web_copy",
        max_tokens=4000,
    )

    try:
        data = parse_json_strict(response.text)
    except json.JSONDecodeError as e:
        log.error("copy_json_parse_failed", error=str(e), raw=response.text[:500])
        print("\n--- RAW RESPONSE ---")
        print(response.text)
        return 1

    missing = [k for k in EXPECTED_KEYS if k not in data]
    if missing:
        log.warning("copy_missing_keys", keys=missing)

    extra = [k for k in data if k not in EXPECTED_KEYS]
    if extra:
        log.info("copy_extra_keys", keys=extra)

    out_path = Path(__file__).resolve().parent.parent / "src" / "web" / "copy.py"
    write_copy_module(data, out_path)

    log.info(
        "copy_generation_done",
        cost_usd=round(response.cost_usd, 6),
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    print(f"\nWrote {out_path} — restart bot to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
