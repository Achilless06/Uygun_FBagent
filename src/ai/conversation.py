"""Conversational SMM-manager mode.

The founder DMs the bot in natural language ("write me a punchier post",
"target younger audience", "use fewer emojis") and Gemini responds as if
it's an in-house SMM manager. This is the killer feature — the bot ceases
to be a command palette and becomes an actual collaborator.

Why Gemini for chat (not Claude): brandbook page 13 specifies Gemini for
Georgian text generation. In practice gemini-2.5-flash-lite handles Georgian
morphology + idioms better than Claude Sonnet, and it's ~30x cheaper for
the same workload.

Three things are injected into every Gemini call as context:
  1. The brand voice + system prompt (encodes brandbook §4)
  2. ALL saved memories (preferences, dislikes, style notes)
  3. The last 20 turns of conversation so it has continuity

Cost: ~$0.0002-0.0008 per message. The api_spend table tracks every call.

Future hook: when the post generator (Phase 3) is wired in, the
conversation engine will be able to call it as a tool ("aha, you want a
new post — let me generate one") via function calling.
"""

from __future__ import annotations

from src import brand, db
from src.ai.gemini_client import GeminiClient
from src.logging_setup import get_logger

log = get_logger(__name__)

CONVERSATION_WINDOW = 20  # last N turns sent back to Claude as context

# System prompt — Claude's persona for the chat.
SYSTEM_PROMPT_TEMPLATE = """\
შენ ხარ Uygun Georgia-ს SMM კოლეგა. არა AI ბოტი — ნამდვილი თანამშრომელი, რომელიც
მფლობელთან ერთად ხურავს ფეიჯს და თამამდ თამამდ ეუბნება რა მუშაობს, რა — არა.

ვინ ხარ:
- გამოცდილი, პრაქტიკოსი — წერ მოკლედ, არსში
- პირდაპირი — თუ რამე ცუდი იდეაა, ეუბნები ღიად
- ცოტა cheeky, არ ხარ ფორმალური
- ქართულად ლაპარაკობ ისე, როგორც მეგობარი — "შენ" ფორმაში
- მშვიდად აიღებ კრიტიკას — ნუ ეუბნები "უი, ჩემი ბრალია" / "სულ დავიბენი" /
  "ბოდიში". უბრალოდ გადააკეთე და მიეცი ახალი ვერსია.

ვისთვის მუშაობს Uygun Georgia:
{mission}

ჩვენი კლიენტები:
• ვულკანიზაცია/ავტოსამრეცხაო მფლობელები (B2B — ბათუმი + დასავლეთ საქართველო)
• ავტოენთუზიასტი DIY მძღოლები (B2C)

ხელთ გაქვს:
📞 {phone}  ·  📍 {address}  ·  🚚 უფასო მიწოდება საქართველოს მასშტაბით
როცა გჭირდება — ეს რეალური ციფრები ჩასვი, არასოდეს [placeholder] ან [...].

რას ნიშნავს "კარგი პოსტი" აქ:
✓ ერთი ძლიერი hook (ფაქტი, კითხვა, ან პრობლემა)
✓ მოკლე — 2-4 წინადადება ხშირად საკმარისია
✓ რეალური ციფრები და კონკრეტიკა
✓ ერთი CTA, არასოდეს ორი
✓ 1-3 emoji, არასოდეს მეტი
✓ "შენ" ფორმაში — ისე, როგორც მექანიკოსი ელაპარაკება მუშტარს

რასაც თავიდან ვიცილებთ (არც გვინდა და არც გვჭირდება):
× "თქვენ" ფორმა — Facebook-ის კონტექსტში ცივი ხდება
× ცარიელი ფრაზები: "მაღალი ხარისხის", "ფანტასტიკური შემოთავაზება", "სანდო მიმწოდებელი"
× მოგონილი ფასები — თუ ფასი არ ვიცი, ვამბობ "ვამოწმებ"
× კონკურენტების ხსენება — სახელით ან გარდასახულად
× პოსტში პროდუქტის შიდა კოდი (#N) — ეს მფლობელისთვისაა, არა საჯარო

ქართული ენის წესები (ბევრი LLM ქართულს word-for-word თარგმნის — ჩვენ ბუნებრივად):

❌ "საბურავი გაიბერა" (means "tire inflated" — wrong direction!)
✅ "საბურავი დაგიფეთქდა" / "ლურსმანი ჩავარდა საბურავში" / "ბორბალი დასკდა"
❌ "სალტე" → ✅ "საბურავი"
❌ "გათავდა მარაგი" → ✅ "მარაგი დაგიმთავრდა" ან "მარაგი მთავრდება"
❌ "გთავაზობთ" (formal გ-...-თ) → ✅ "გთავაზობ" ან "გვაქვს"
❌ "6 ლარის ღირებულების" → ✅ "6 ლარი" ან "6 ლარად"
❌ "შენი მანქანის ვარსკვლავი გახდი" → ✅ უბრალოდ ფაქტი

წინასწარ შეამოწმე ყოველი ფრაზა: "ქართველი ადამიანი ასე იტყვის?" თუ არა — შეცვალე.

შენი სტილი ჩატში:
- მფლობელი გეუბნება "დაწერე პოსტი" — ერთი draft მიაცი, არა 3 ვარიანტი. შემდეგ ჰკითხე
  "ეს მოგწონს, თუ სხვა მიდგომა?"
- გეუბნება "უფრო მოკლე გახადე" / "emoji შემცირე" — გააკეთე და მიეცი ახალი ვერსია.
  არ ახსნა რას აპირებ, უბრალოდ გააკეთე.
- გეუბნება რომ რამე არ მოეწონა — დაიკავე ეს preference, შესთავაზე "გნებავს /remember-ით
  დავიმახსოვრო?"
- ეკითხება ანალიტიკას ან რჩევას — გამოიყენე ქვემოთ მოცემული რეალური ციფრები, ნუ
  მოიგონებ.
- რაიმეს ვერ აკეთებ (FB-ზე გამოქვეყნება, ემეილი) — პირდაპირ უთხარი ეს და შესთავაზე
  რა შეგიძლია გააკეთო.

ის რაც მფლობელის შესახებ ვიცი (მახსოვრობა — გადახედე ყოველი პასუხის წინ):
{memories_block}

დღევანდელი მდგომარეობა:
• თარიღი: {today}
• დღევანდელი კალენდრის ფოკუსი: {calendar_slot}
• Facebook პოსტი სულ გამოქვეყნებული: {posts_published}
• დასადასტურებლად ელოდება: {pending_drafts}
• პროდუქცია სულ: {total_products} (მარაგში: {in_stock})

ერთი წინადადებით: მფლობელი დანამდვილებით იცის რა გვინდა — შენ ისე ელაპარაკე,
როგორც ერთი მათგანი, არა როგორც corporate ბოტი.
"""


def _build_memories_block(memories: list[db.Memory]) -> str:
    if not memories:
        return "_(ჯერ მახსოვრობა ცარიელია — დროთა განმავლობაში ჩაიწერება)_"
    lines = []
    for m in memories:
        lines.append(f"- [{m.category}] {m.content}")
    return "\n".join(lines)


def _build_system_prompt(today_iso: str) -> str:
    from datetime import date

    memories = db.list_memories()
    today = date.fromisoformat(today_iso)
    weekday = today.weekday()
    calendar_slot = brand.WEEKLY_CALENDAR.get(weekday, "B2C")

    with db.session_scope() as s:
        total_products = s.query(db.Product).count()
        in_stock = s.query(db.Product).filter(db.Product.stock_qty > 0).count()
        posts_published = s.query(db.Post).count()
        pending_drafts = s.query(db.PostDraft).filter(db.PostDraft.status == "pending").count()

    return SYSTEM_PROMPT_TEMPLATE.format(
        mission=brand.MISSION,
        vision=brand.VISION,
        phone=brand.CONTACT_PHONE,
        address=brand.CONTACT_ADDRESS,
        memories_block=_build_memories_block(memories),
        today=today_iso,
        calendar_slot=f"{calendar_slot} ({brand.SLOT_DESCRIPTIONS.get(calendar_slot, '')[:80]})",
        total_products=total_products,
        in_stock=in_stock,
        posts_published=posts_published,
        pending_drafts=pending_drafts,
    )


class ChatEngine:
    """Stateless dispatcher — every call rebuilds context from the DB."""

    def __init__(self, gemini: GeminiClient) -> None:
        self._gemini = gemini

    def respond(self, user_message: str) -> str:
        """Take a user message, save it, ask Gemini, save the reply, return it."""
        from datetime import date

        # 1. Persist the user's turn.
        db.append_conversation_message(role="user", content=user_message)

        # 2. Build context.
        history = db.recent_conversation(limit=CONVERSATION_WINDOW)
        system_prompt = _build_system_prompt(today_iso=date.today().isoformat())
        formatted = self._format_history(history)

        # 3. Single multi-turn call.
        try:
            response = self._gemini.generate_multi(
                system=system_prompt,
                messages=formatted,
                operation="chat",
                max_tokens=1500,
            )
        except Exception:
            log.exception("chat_gemini_call_failed")
            return (
                "😕 ვერ შევძელი პასუხის გენერაცია. "
                "ხშირი მიზეზები: API ლიმიტი, ქსელის შეცდომა. სცადე თავიდან."
            )

        reply = response.text.strip()

        # 4. Persist the assistant's turn (with cost tracking).
        db.append_conversation_message(
            role="assistant",
            content=reply,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
        )

        return reply

    @staticmethod
    def _format_history(history: list[db.ConversationMessage]) -> list[dict]:
        """Turn DB rows into {"role", "content"} dicts.

        Gemini requires the conversation to alternate user/model and end with
        a user turn. We collapse consecutive same-role messages and add an
        empty user turn as a safeguard if the last turn happens to be assistant.
        """
        out: list[dict] = []
        last_role: str | None = None
        for row in history:
            role = "user" if row.role == "user" else "assistant"
            if role == last_role:
                if out and isinstance(out[-1]["content"], str):
                    out[-1]["content"] += "\n\n" + row.content
                continue
            out.append({"role": role, "content": row.content})
            last_role = role
        if not out or out[-1]["role"] != "user":
            out.append({"role": "user", "content": ""})
        return out
