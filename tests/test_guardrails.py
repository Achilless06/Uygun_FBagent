"""Unit tests for src/guardrails.py.

Each validator gets 1-3 tests: a passing case + the most important failing
case. We deliberately do NOT mock the brand constants — the validators
read them directly from brand.py, and we want changes there to flag any
test that depends on a now-stale value.
"""

from __future__ import annotations

from src import brand, guardrails
from src.guardrails import Draft, Severity


def _draft(body: str, **kwargs) -> Draft:
    """Build a Draft with sensible defaults for tests."""
    return Draft(
        body_text=body,
        hashtags=kwargs.get("hashtags", ["#UygunGeorgia", "#ვულკანიზაცია", "#ბათუმი"]),
        featured_product_code=kwargs.get("featured_product_code"),
        featured_product_price=kwargs.get("featured_product_price"),
        featured_product_stock_qty=kwargs.get("featured_product_stock_qty", 1),
    )


# ─── address form ────────────────────────────────────────────────────────────


class TestAddressForm:
    def test_shen_form_passes(self):
        d = _draft("გვითხარი რა გჭირდება, გავაგზავნით უფასოდ.")
        assert guardrails.check_address_form(d) == []

    def test_tkven_form_blocks(self):
        d = _draft("გვითხარით რა გჭირდებათ, გავაგზავნით.")
        violations = guardrails.check_address_form(d)
        assert len(violations) >= 1
        assert all(v.severity is Severity.BLOCK for v in violations)
        assert violations[0].rule == "address_form"

    def test_tkven_possessive_blocks(self):
        d = _draft("თქვენი ვულკანიზაცია გვჭირდება.")
        violations = guardrails.check_address_form(d)
        assert len(violations) >= 1


# ─── banned phrases ──────────────────────────────────────────────────────────


class TestBannedPhrases:
    def test_clean_text_passes(self):
        d = _draft("გვაქვს ცემენტი მარაგში, შემოგვიარე.")
        assert guardrails.check_banned_phrases(d) == []

    def test_marketing_phrase_blocks(self):
        d = _draft("არ გამოტოვო ეს უნიკალური შესაძლებლობა!")
        violations = guardrails.check_banned_phrases(d)
        assert len(violations) >= 1
        assert violations[0].rule == "banned_phrase"


# ─── tire word ───────────────────────────────────────────────────────────────


class TestTireWord:
    def test_saburavi_passes(self):
        d = _draft("საბურავი ეფეთქა გზაზე.")
        assert guardrails.check_tire_word(d) == []

    def test_salte_blocks(self):
        d = _draft("სალტე ეფეთქა გზაზე.")
        violations = guardrails.check_tire_word(d)
        assert len(violations) == 1
        assert violations[0].rule == "tire_word"
        assert violations[0].severity is Severity.BLOCK


# ─── banned topics ───────────────────────────────────────────────────────────


class TestBannedTopics:
    def test_neutral_passes(self):
        d = _draft("საბურავი ეფეთქა, ვულკანიზაცია გჭირდება.")
        assert guardrails.check_banned_topics(d) == []

    def test_accident_blocks(self):
        d = _draft("ცუდი საბურავი = ავარია გზაზე.")
        violations = guardrails.check_banned_topics(d)
        assert len(violations) >= 1
        assert violations[0].rule == "banned_topic"

    def test_politics_blocks(self):
        d = _draft("პოლიტიკური სიტუაცია ხელს უშლის ბიზნესს.")
        violations = guardrails.check_banned_topics(d)
        assert len(violations) >= 1


# ─── price grounding ─────────────────────────────────────────────────────────


class TestPriceGrounding:
    def test_no_price_mentioned_passes(self):
        d = _draft("გვაქვს ცემენტი მარაგში.", featured_product_price=20.0)
        assert guardrails.check_price_grounding(d) == []

    def test_matching_price_passes(self):
        d = _draft("ცემენტი 20 ლარი.", featured_product_price=20.0)
        assert guardrails.check_price_grounding(d) == []

    def test_close_enough_passes(self):
        # 1 ლარი tolerance — 20.5 ≈ 20.
        d = _draft("ცემენტი 20.5 ლარი.", featured_product_price=20.0)
        assert guardrails.check_price_grounding(d) == []

    def test_mismatched_price_blocks(self):
        d = _draft("ცემენტი 30 ლარი.", featured_product_price=20.0)
        violations = guardrails.check_price_grounding(d)
        assert len(violations) >= 1
        assert violations[0].rule == "price_mismatch"

    def test_invented_price_when_no_real_price_blocks(self):
        d = _draft("ცემენტი 25 ლარი.", featured_product_price=None)
        violations = guardrails.check_price_grounding(d)
        assert len(violations) >= 1
        assert violations[0].rule == "price_invented"

    def test_lari_symbol_caught(self):
        d = _draft("ფასი 30 ₾.", featured_product_price=20.0)
        violations = guardrails.check_price_grounding(d)
        assert len(violations) >= 1


# ─── stock grounding ─────────────────────────────────────────────────────────


class TestStockGrounding:
    def test_in_stock_claim_passes(self):
        d = _draft(
            "გვაქვს ცემენტი მარაგში.",
            featured_product_code="29",
            featured_product_stock_qty=1,
        )
        assert guardrails.check_stock_grounding(d) == []

    def test_out_of_stock_with_claim_blocks(self):
        d = _draft(
            "გვაქვს ცემენტი მარაგში.",
            featured_product_code="29",
            featured_product_stock_qty=0,
        )
        violations = guardrails.check_stock_grounding(d)
        assert len(violations) == 1
        assert violations[0].rule == "stock_claim_without_stock"

    def test_out_of_stock_without_claim_passes(self):
        # No "გვაქვს"/"მარაგში"/"ხელმისაწვდომი" → no claim, no violation.
        d = _draft(
            "ცემენტი ვულკანიზაციის სტანდარტია.",
            featured_product_code="29",
            featured_product_stock_qty=0,
        )
        assert guardrails.check_stock_grounding(d) == []


# ─── hashtag count ───────────────────────────────────────────────────────────


class TestHashtags:
    def test_in_range_passes(self):
        # New minimal format: 2-3 hashtags
        d = _draft("test body", hashtags=["#a", "#b"])
        assert guardrails.check_hashtags(d) == []
        d3 = _draft("test body", hashtags=["#a", "#b", "#c"])
        assert guardrails.check_hashtags(d3) == []

    def test_too_few_warns(self):
        d = _draft("test body", hashtags=["#a"])
        violations = guardrails.check_hashtags(d)
        assert len(violations) == 1
        assert violations[0].severity is Severity.WARN

    def test_too_many_blocks(self):
        d = _draft("test body", hashtags=["#a"] * 11)
        violations = guardrails.check_hashtags(d)
        assert len(violations) == 1
        assert violations[0].severity is Severity.BLOCK


# ─── contact block ───────────────────────────────────────────────────────────


class TestContactBlock:
    def test_phone_present_passes(self):
        d = _draft(f"გვითხარი რა გჭირდება. {brand.CONTACT_PHONE}")
        assert guardrails.check_contact_block(d) == []

    def test_address_present_passes(self):
        d = _draft(f"შემოგვიარე — {brand.CONTACT_ADDRESS}")
        assert guardrails.check_contact_block(d) == []

    def test_neither_warns(self):
        d = _draft("ცემენტი მარაგშია.")
        violations = guardrails.check_contact_block(d)
        assert len(violations) == 1
        assert violations[0].severity is Severity.WARN


# ─── placeholders ────────────────────────────────────────────────────────────


class TestPlaceholders:
    def test_no_placeholder_passes(self):
        d = _draft("ცემენტი 20 ლარი. დაგვირეკე.")
        assert guardrails.check_placeholders(d) == []

    def test_bracket_placeholder_blocks(self):
        d = _draft("დაგვირეკე [ტელეფონის ნომერი]")
        violations = guardrails.check_placeholders(d)
        assert len(violations) == 1
        assert violations[0].rule == "placeholder"

    def test_english_placeholder_blocks(self):
        d = _draft("Call [phone number]")
        violations = guardrails.check_placeholders(d)
        assert len(violations) == 1


# ─── integration ─────────────────────────────────────────────────────────────


class TestValidate:
    def test_clean_draft_passes(self):
        d = _draft(
            f"ცემენტი 1L — ვულკანიზაციის სტანდარტი. გვაქვს მარაგში. "
            f"20 ლარი. {brand.CONTACT_PHONE}",
            featured_product_code="29",
            featured_product_price=20.0,
            featured_product_stock_qty=1,
        )
        violations = guardrails.validate(d)
        assert not guardrails.has_blocking_violations(violations)

    def test_multiple_violations_collected(self):
        # 'თქვენ' form + invented price + 'სალტე'.
        d = _draft(
            "თქვენ გვინდა გავაგზავნოთ სალტე 999 ლარად",
            featured_product_price=20.0,
        )
        violations = guardrails.validate(d)
        rules = {v.rule for v in violations}
        assert "address_form" in rules
        assert "tire_word" in rules
        assert "price_mismatch" in rules

    def test_has_blocking_violations_helper(self):
        assert guardrails.has_blocking_violations(
            [guardrails.Violation(rule="x", severity=Severity.BLOCK, detail="...")]
        )
        assert not guardrails.has_blocking_violations(
            [guardrails.Violation(rule="x", severity=Severity.WARN, detail="...")]
        )
        assert not guardrails.has_blocking_violations([])
