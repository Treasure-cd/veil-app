import unittest
from decimal import Decimal

from app.services.whatsapp_parser import parse_message
from app.services.phone_numbers import normalize_phone_number


class WhatsAppParserTests(unittest.TestCase):
    def test_pidgin_create_link_with_memo(self):
        parsed = parse_message("abeg make link 5k for shoes")
        self.assertEqual(parsed["intent"], "create_link")
        self.assertEqual(parsed["amount_ngn"], Decimal("5000"))
        self.assertEqual(parsed["memo"], "shoes")

    def test_pidgin_recent_payments(self):
        self.assertEqual(parse_message("wetin I don collect")["intent"], "recent_payments")

    def test_rate_queries_and_conversions(self):
        for message in ("rate", "rates", "exchange rate", "usdc rate"):
            with self.subTest(message=message):
                self.assertEqual(parse_message(message)["intent"], "rate")

        conversion = parse_message("5000 in usdc")
        self.assertEqual(conversion["intent"], "rate")
        self.assertEqual(conversion["rate_amount"], Decimal("5000"))
        self.assertEqual(conversion["rate_currency"], "USDC")
        self.assertFalse(conversion["rate_amount_is_token"])

        query = parse_message("rate 5k")
        self.assertEqual(query["intent"], "rate")
        self.assertEqual(query["rate_amount"], Decimal("5000"))

        token_conversion = parse_message("10 usdc in ngn")
        self.assertEqual(token_conversion["intent"], "rate")
        self.assertEqual(token_conversion["rate_amount"], Decimal("10"))
        self.assertTrue(token_conversion["rate_amount_is_token"])

    def test_daily_summary_queries_do_not_become_link_requests(self):
        for message in ("today", "summary", "daily", "daily summary", "today's sales"):
            with self.subTest(message=message):
                self.assertEqual(parse_message(message)["intent"], "daily_summary")

        self.assertEqual(parse_message("link 5000 for lunch")["intent"], "create_link")

    def test_pidgin_greeting(self):
        self.assertEqual(parse_message("how far")["intent"], "menu")

    def test_amount_and_memo(self):
        parsed = parse_message("5,000 jollof rice")
        self.assertEqual(parsed["amount_ngn"], Decimal("5000"))
        self.assertEqual(parsed["memo"], "jollof rice")

    def test_payment_options_are_parsed_and_removed_from_memo(self):
        parsed = parse_message(
            "link 5k for lunch private pay instead crypto to crypto rather than crypto + bank transfer"
        )
        self.assertEqual(parsed["intent"], "create_link")
        self.assertEqual(parsed["receive_mode"], "private")
        self.assertTrue(parsed["crypto_only"])
        self.assertEqual(parsed["memo"], "lunch")

    def test_default_payment_options_are_unspecified(self):
        parsed = parse_message("5000 for lunch")
        self.assertIsNone(parsed["receive_mode"])
        self.assertFalse(parsed["crypto_only"])

    def test_amount_variants(self):
        for message, amount in (("5k", "5000"), ("2.5k", "2500"), ("₦5000", "5000"), ("5000 naira", "5000")):
            with self.subTest(message=message):
                self.assertEqual(parse_message(message)["amount_ngn"], Decimal(amount))

    def test_link_code(self):
        parsed = parse_message("link AbC_123")
        self.assertEqual(parsed["intent"], "link_code")
        self.assertEqual(parsed["code"], "AbC_123")

    def test_invalid_amount_edges(self):
        self.assertIsNone(parse_message("k")["amount_ngn"])
        self.assertEqual(parse_message("0")["amount_error"], "too_low")
        self.assertEqual(parse_message("5000k")["amount_ngn"], Decimal("5000000"))


class PhoneNumberTests(unittest.TestCase):
    def test_whatsapp_prefix_and_nigerian_local_number(self):
        self.assertEqual(normalize_phone_number("whatsapp:+2348012345678"), "+2348012345678")
        self.assertEqual(normalize_phone_number("08012345678"), "+2348012345678")


if __name__ == "__main__":
    unittest.main()
