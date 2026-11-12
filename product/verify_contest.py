"""Checks the official v1.1.0 data loaded by import_contest_data.py through the product HTTPS API (isolated P8 only).

Needs PRODUCT_TEST_BASE (P8 gateway), SSL_CERT_FILE and COMPOSE_PROJECT_NAME=tax-product-p8.
Default run is program-only (permissions + rule versions). --chat adds ONE real-model chat turn asking
C001 / 2026-09 invoice total, bank income and bank expense and checks the rendered amounts.
"""
import json
import sys
from urllib.parse import quote
from uuid import uuid4

import verify_agent as v

EXPECTED_C001_2026_09 = {"发票合计": "9,622.06", "银行收入": "13,000.50", "银行支出": "7,180.74"}
# Expected purpose gaps on a freshly imported DB (02_示例数据.xlsx + 03_业务规则.docx):
# 甲 2026-09 uses R002 2.0 (every invoice); 乙 uses R003 1.0 (only amount >= 1000.00, inclusive).
EXPECTED_MISSING = {
    ("C001", "2026-09"): {"F002", "F003", "F004", "F006", "F009"},
    ("C002", "2026-08"): {"F016"},
    ("C002", "2026-09"): {"F002", "F005", "F006"},
}
IDS = {"2026-08": [f"F{n:03d}" for n in range(11, 21)], "2026-09": [f"F{n:03d}" for n in range(1, 11)]}


def denied(client, path, body=None):
    """Returns the HTTP status for a request that must be refused (403 or 404, never 2xx)."""
    try:
        v.request(client, path, body, expected=403)
        return 403
    except AssertionError as error:
        return error.args[0][1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    v.require_p8_target()
    u1, u2 = v.login("u001"), v.login("u002")
    rules = json.loads(v.request(u1, "/api/enterprises/C001/rules"))
    versions = sorted((r["citation"]["code"], r["citation"]["version"], r["state"]) for r in rules)
    v.check(("R002", "1.0", "retired") in versions and ("R002", "2.0", "published") in versions, "R002 1.0 retired, 2.0 published")
    hits = json.loads(v.request(u1, "/api/enterprises/C001/rules/search?period=2026-09&query=" + quote("发票用途")))
    found = [(h["rule"]["citation"]["code"], h["rule"]["citation"]["version"]) for h in hits]
    v.check(("R002", "1.0") not in found and ("R002", "2.0") in found, "2026-09 search excludes disabled R002 1.0: %s" % found)
    v.check(json.loads(v.request(u1, "/api/enterprises/C002/rules")) != [], "u001 can read C002")
    v.check(len(json.loads(v.request(u2, "/api/enterprises/C001/rules"))) == 4, "u002 can read C001")
    code = denied(u2, "/api/enterprises/C002/rules")
    v.check(code in (403, 404), f"u002 cannot read C002 ({code})")
    code = denied(u2, "/api/enterprises/C001/invoices/F002/proposals", {"purpose": "测试"})
    v.check(code in (403, 404), f"u002 cannot propose a change on C001 ({code})")
    for (enterprise, period), expected in EXPECTED_MISSING.items():
        flagged, versions = set(), set()
        for invoice in IDS[period]:
            result = json.loads(v.request(u1, f"/api/enterprises/{enterprise}/invoices/{invoice}/review", {}))
            assert result["status"] == "ready", (enterprise, invoice, result)
            versions.add(result["rule_version"])
            if "purpose" in result["missing"]:
                flagged.add(invoice)
        v.check(flagged == expected, f"{enterprise} {period} missing purpose {sorted(flagged)} by {sorted(versions)}")
    if "--chat" in sys.argv:
        events = v.turn(u1, "甲企业2026年9月的发票合计、银行收入和银行支出分别是多少？", str(uuid4()), "C001", "2026-09")
        answer = next((e["data"]["message"] for e in events if e["event"] == "answer"), "")
        print("ANSWER:", answer.replace("\n", " "), flush=True)
        print("STATUS:", events[-1]["data"].get("status"), flush=True)
        for label, amount in EXPECTED_C001_2026_09.items():
            v.check(amount in answer or amount.replace(",", "") in answer, f"{label} {amount} in answer")


if __name__ == "__main__":
    main()
