"""Offline unit test for import_contest_data.py (no Docker needed): python -m unittest product/test_import_contest_data.py"""
import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_contest_data as m


class ImporterTest(unittest.TestCase):
    def test_cents_are_exact(self):
        self.assertEqual([m.cents(v) for v in (460.5, 999.99, 1000.01, 9622.060000000001, 0)], [46050, 99999, 100001, 962206, 0])

    def test_blank_purpose_stays_null(self):
        self.assertIsNone(m.text("  "))
        self.assertIsNone(m.text(None))
        self.assertEqual(m.text("购买办公文具"), "购买办公文具")

    def test_password_hash_matches_java_format(self):
        salt, derived = m.password_hash("x" * 20).split(":")
        self.assertEqual((len(m.base64.b64decode(salt)), len(m.base64.b64decode(derived))), (16, 32))

    def test_rules_keep_disabled_version_and_guidance_has_no_fields(self):
        r002 = {r[2]: r for r in m.RULES if r[1] == "R002"}
        self.assertEqual(r002["1.0"][8], "retired")
        self.assertEqual(r002["1.0"][7], "2026-09-01")
        self.assertEqual(r002["2.0"][8], "published")
        self.assertTrue(all(r[5] == [] for r in m.RULES if r[1] in ("R001", "R004")))

    def test_r003_threshold_is_1000_inclusive_and_repaired_on_rerun(self):
        rules = {(r[0], r[1], r[2]): r for r in m.RULES}
        self.assertEqual(rules[("C002", "R003", "1.0")][9], 100000)
        self.assertIsNone(rules[("C001", "R002", "2.0")][9])
        sql = m.build_sql({"C001": "甲", "C002": "乙"}, [], [], {"u001": "p" * 20, "u002": "q" * 20})
        r003 = next(l for l in sql.splitlines() if "'R003'" in l)
        self.assertIn(",100000)", r003)
        self.assertIn("DO UPDATE SET min_amount_cents = EXCLUDED.min_amount_cents", r003)

    def test_sql_is_idempotent_and_quotes(self):
        inv = [{"enterprise_id": "C001", "invoice_id": "F001", "period": dt.date(2026, 9, 1), "purpose": "a'b", "note": None,
                "amount_cents": 50000, "seller": "s", "item_name": "i"}]
        bank = [{"enterprise_id": "C001", "transaction_id": "T001", "period": dt.date(2026, 9, 1), "date": dt.date(2026, 9, 3),
                 "direction": "income", "amount_cents": 1, "counterparty": "c", "note": None}]
        sql = m.build_sql({"C001": "甲", "C002": "乙"}, inv, bank, {"u001": "p" * 20, "u002": "q" * 20})
        self.assertIn("'a''b'", sql)
        self.assertNotIn("p" * 20, sql)
        inserts = [l for l in sql.splitlines() if l.startswith("INSERT")]
        self.assertTrue(all("ON CONFLICT" in l for l in inserts))
        self.assertFalse(any("DO UPDATE" in l for l in inserts if "invoice_rule" not in l))
        self.assertLess(sql.index("DISABLE TRIGGER"), sql.index("INSERT INTO product_bank_transaction"))
        self.assertLess(sql.index("INSERT INTO product_bank_transaction"), sql.index("ENABLE TRIGGER"))

    def test_env_passwords_appended_once(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("A=1", encoding="utf-8")
            first, added = m.ensure_passwords(env)
            second, again = m.ensure_passwords(env)
            self.assertEqual(added, ["PRODUCT_U001_PASSWORD", "PRODUCT_U002_PASSWORD"])
            self.assertEqual((first, again), (second, []))
            self.assertTrue(env.read_text(encoding="utf-8").startswith("A=1\n"))

    @unittest.skipUnless(os.getenv("CONTEST_XLSX"), "set CONTEST_XLSX to the official 02_示例数据.xlsx")
    def test_official_workbook_matches_its_summary(self):
        names, invoices, bank, published = m.load_workbook_data(os.environ["CONTEST_XLSX"])
        self.assertEqual((len(invoices), len(bank)), (40, 48))
        computed = m.summarize(invoices, bank)
        for key, value in published.items():
            self.assertEqual(computed.get(key, m.EMPTY), value, key)


if __name__ == "__main__":
    unittest.main()
