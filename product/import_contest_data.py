"""Idempotent loader for the official v1.1.0 competition sample data (赛题二 02_示例数据.xlsx + 03_业务规则.docx).

Loads into a dedicated tenant `contest` so the synthetic alpha/beta fixtures used by the verify_* scripts stay intact:
  - enterprises C001 甲企业（比赛模拟）, C002 乙企业（比赛模拟）
  - accounts u001 (editor on C001+C002) and u002 (viewer on C001 only); passwords come from product/.env
    PRODUCT_U001_PASSWORD / PRODUCT_U002_PASSWORD and are generated and appended there when missing (never printed)
  - 40 invoices, 48 bank transactions, rules R001-R004 with versions; R002 1.0 is stored as `retired`
Re-running inserts only missing rows (ON CONFLICT DO NOTHING) and never overwrites purpose/note edits.
Afterwards the DB is read back and per company-month counts and totals are compared with the workbook.

Usage (isolated P8 copy):
  python product/import_contest_data.py --project tax-product-p8
  python product/import_contest_data.py --project tax-product-p8 --check-only
  (--xlsx <path> overrides the bundled product/data/contest/02_示例数据.xlsx)

start.ps1 / start.sh run it inside the importer image (Python + openpyxl + psycopg), so the host needs only Docker:
  docker compose ... run --rm --no-deps -T -v <product>:/work --entrypoint python importer \
      /work/import_contest_data.py --direct-db --allow-main [--check-only]
--direct-db connects to the compose service `db` with PRODUCT_DB_PASSWORD from the mounted .env instead of
`docker compose exec db psql`.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
# Official 赛题二 v1.1.0 sample workbook, bundled unmodified (see data/contest/README.md).
DEFAULT_XLSX = ROOT / "data" / "contest" / "02_示例数据.xlsx"
TENANT = "contest"
ROLES = {("u001", "C001"): "editor", ("u001", "C002"): "editor", ("u002", "C001"): "viewer"}
DIRECTIONS = {"收入": "income", "支出": "expense"}
EXPECTED_INVOICES, EXPECTED_BANK = 40, 48
EMPTY = {"invoices": 0, "bank": 0, "invoice_cents": 0, "expense_cents": 0, "income_cents": 0}

R001 = ("1. 发票金额表示价税合计。发票总额为所选企业、月份的全部发票金额之和；是否填写用途不影响金额查询。"
        "2. 银行收入和支出按收支方向分别相加，不把收入计入支出，不用收入减支出来代替支出总额。"
        "3. 金额单位为元，保留两位小数。程序使用十进制金额或整数分计算，不要求拆分税额、计算税率或生成会计分录。"
        "4. 月份按发票日期或银行交易日期确定。用户没说清月份且前文没有明确月份时，应先追问，不能默认替换为当前月份。"
        "5. 发票总额和银行支出可以不同。本题不要求逐条匹配，不能因金额不同就判断错误、欠款或已经付款。"
        "6. 成功查询但没有记录时，合计为 0.00 元，并说明没有记录。查询失败或无权限不等于没有记录，不能回答为零。"
        "金额与保存状态以学生系统当前保存的数据为准。规则文档和 Excel 中的核对金额用于解释和检查，不能代替实际查询。")
R002_V1 = ("旧版要求：单张发票金额大于或等于 1000.00 元时必须填写用途；低于此金额可以不填。空白或只有空格视为未填写。"
           "本版保留用于检查版本管理。2026 年 9 月的用途检查应使用 2.0 版，不能继续使用本版的金额门槛。初赛不考历史规则恢复。")
R002_V2 = ("从 2026 年 9 月起，甲企业每张发票都必须填写用途，不设置金额门槛。空白或只有空格视为未填写，备注不能代替用途。"
           "检查时查询当前发票，列出未填用途的编号。用户补充用途时，应确认企业、发票和内容，检查修改权限，保存后再查询核对。"
           "企业编号和发票编号共同确定一张发票，不能修改其他企业的同编号记录。只查询或询问规则不代表授权修改。"
           "本版取代已停用的 1.0 版。回答可注明“依据《甲企业发票用途规则》2.0 版”。")
R003 = ("单张发票金额大于或等于 1000.00 元时必须填写用途，等于 1000 元也在范围内；低于此金额可以不填。"
        "空白或只有空格视为未填写，备注不能代替用途。检查应使用当前金额和用途。不能套用甲企业“每张必填”的规则，"
        "也不能把允许不填的发票列为不符合要求。用户可以主动补充低于门槛发票的用途，但仍须具备修改权限，并明确要修改的企业、发票和内容。"
        "回答可注明“依据《乙企业发票用途规则》1.0 版”。")
R004 = ("企业编号和银行记录编号共同确定一条记录，相同编号可以出现在不同企业中。交易日期用于确定查询年份和月份。"
        "收支方向分为收入和支出，金额均为正数；支出不再另外减一次负号。对方名称和备注仅说明该条记录，不能据此推断某张发票已经付款。"
        "银行资料全部只读，不允许新增、删除或修改。查询必须检查用户权限和企业范围。银行记录与发票没有逐条对应关系。"
        "需要汇总时，按 R001 1.0 版分别统计。")
# (enterprise, code, version, source, content, required_fields, effective_from, effective_until, state, min_amount_cents)
# Guidance rules carry no required fields; the business service never selects them for purpose/note review.
# min_amount_cents (V9): required fields apply only when amount_cents >= threshold. 03_业务规则.docx R003 1.0 (and the
# retired R002 1.0): "单张发票金额大于或等于 1000.00 元时必须填写用途，等于 1000 元也在范围内" -> 100000, inclusive.
THRESHOLD_1000 = 100000
RULES = [(e, "R001", "1.0", "《金额统计说明》", R001, [], "2026-01-01", None, "published", None) for e in ("C001", "C002")] + [
    ("C001", "R002", "1.0", "《甲企业发票用途规则》", R002_V1, ["purpose"], "2026-08-01", "2026-09-01", "retired", THRESHOLD_1000),
    ("C001", "R002", "2.0", "《甲企业发票用途规则》", R002_V2, ["purpose"], "2026-09-01", None, "published", None),
    ("C002", "R003", "1.0", "《乙企业发票用途规则》", R003, ["purpose"], "2026-08-01", None, "published", THRESHOLD_1000),
] + [(e, "R004", "1.0", "《银行资料说明》", R004, [], "2026-01-01", None, "published", None) for e in ("C001", "C002")]


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def text(value):
    return None if value is None or str(value).strip() == "" else str(value)


def as_date(value):
    return value.date() if isinstance(value, dt.datetime) else dt.date.fromisoformat(str(value)[:10])


def _table(sheet, second_header):
    rows = list(sheet.iter_rows(values_only=True))
    start = next(i for i, r in enumerate(rows) if r and r[0] == "企业编号" and r[1] == second_header)
    out = []
    for r in rows[start + 1:]:
        if not r or r[0] is None or not str(r[0]).startswith("C"):
            break
        out.append(r)
    return out


def load_workbook_data(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    names = {r[0]: r[1] for r in wb["企业与用户"].iter_rows(values_only=True) if r and r[0] in ("C001", "C002")}
    invoices = []
    for r in _table(wb["发票"], "发票编号"):
        day = as_date(r[2])
        invoices.append({"enterprise_id": r[0], "invoice_id": str(r[1]), "date": day, "period": day.replace(day=1),
                         "seller": str(r[3]), "item_name": str(r[4]), "amount_cents": cents(r[5]),
                         "purpose": text(r[6]), "note": text(r[7])})
    bank = []
    for r in _table(wb["银行流水"], "流水编号"):
        day = as_date(r[2])
        bank.append({"enterprise_id": r[0], "transaction_id": str(r[1]), "date": day, "period": day.replace(day=1),
                     "direction": DIRECTIONS[r[3]], "amount_cents": cents(r[4]), "counterparty": str(r[5]), "note": text(r[6])})
    published = {}
    for r in _table(wb["说明"], "月份"):
        published[(r[0], as_date(r[1]).strftime("%Y-%m"))] = {"invoices": r[2], "bank": r[3], "invoice_cents": cents(r[4]),
                                                               "expense_cents": cents(r[5]), "income_cents": cents(r[6])}
    return names, invoices, bank, published


def summarize(invoices, bank):
    out = {}
    for i in invoices:
        s = out.setdefault((i["enterprise_id"], i["period"].strftime("%Y-%m")), dict(EMPTY))
        s["invoices"] += 1
        s["invoice_cents"] += i["amount_cents"]
    for b in bank:
        s = out.setdefault((b["enterprise_id"], b["period"].strftime("%Y-%m")), dict(EMPTY))
        s["bank"] += 1
        s[b["direction"] + "_cents"] += b["amount_cents"]
    return out


def lit(value):
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def password_hash(password):
    """Same format as Accounts.java: base64(salt):base64(PBKDF2-HMAC-SHA256, 600000 iterations, 256 bit)."""
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000, 32)
    return base64.b64encode(salt).decode() + ":" + base64.b64encode(derived).decode()


def read_env(env_path):
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    return lines, dict(l.split("=", 1) for l in lines if "=" in l and not l.startswith("#"))


def ensure_passwords(env_path):
    lines, config = read_env(env_path)
    added = []
    for user in ("u001", "u002"):
        key = f"PRODUCT_{user.upper()}_PASSWORD"
        if not config.get(key):
            config[key] = secrets.token_urlsafe(18)
            added.append(f"{key}={config[key]}")
    if added:
        with env_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(("\n" if lines and lines[-1] != "" else "") + "\n".join(added) + "\n")
    return {u: config[f"PRODUCT_{u.upper()}_PASSWORD"] for u in ("u001", "u002")}, [a.split("=", 1)[0] for a in added]


def build_sql(names, invoices, bank, passwords):
    q = ["SET client_encoding = 'UTF8';", "BEGIN;", f"INSERT INTO tenant VALUES ({lit(TENANT)}) ON CONFLICT DO NOTHING;"]
    for e in ("C001", "C002"):
        q.append(f"INSERT INTO enterprise VALUES ({lit(TENANT)},{lit(e)},{lit(names[e])}) ON CONFLICT DO NOTHING;")
    for user in ("u001", "u002"):
        q.append("INSERT INTO product_account (account_id, username, password_hash, enabled) VALUES "
                 f"(gen_random_uuid(),{lit(user)},{lit(password_hash(passwords[user]))},true) ON CONFLICT (username) DO NOTHING;")
        q.append(f"INSERT INTO tenant_membership SELECT {lit(TENANT)}, account_id FROM product_account WHERE username={lit(user)} "
                 "ON CONFLICT DO NOTHING;")
    for (user, e), role in ROLES.items():
        q.append(f"INSERT INTO enterprise_grant SELECT {lit(TENANT)},{lit(e)},account_id,{lit(role)} FROM product_account "
                 f"WHERE username={lit(user)} ON CONFLICT DO NOTHING;")
    for i in invoices:
        q.append("INSERT INTO product_invoice (tenant_id,enterprise_id,invoice_id,purpose,note,accounting_period,amount_cents,seller,item_name) "
                 f"VALUES ({lit(TENANT)},{lit(i['enterprise_id'])},{lit(i['invoice_id'])},{lit(i['purpose'])},{lit(i['note'])},"
                 f"{lit(i['period'].isoformat())},{i['amount_cents']},{lit(i['seller'])},{lit(i['item_name'])}) ON CONFLICT DO NOTHING;")
    # Bank data stays read-only for every application path; only this loader lifts the trigger inside its own transaction.
    q.append("ALTER TABLE product_bank_transaction DISABLE TRIGGER product_bank_transaction_read_only;")
    for b in bank:
        q.append("INSERT INTO product_bank_transaction VALUES "
                 f"({lit(TENANT)},{lit(b['enterprise_id'])},{lit(b['transaction_id'])},{lit(b['period'].isoformat())},"
                 f"{lit(b['date'].isoformat())},{lit(b['direction'])},{b['amount_cents']},{lit(b['counterparty'])},{lit(b['note'])}) "
                 "ON CONFLICT DO NOTHING;")
    q.append("ALTER TABLE product_bank_transaction ENABLE TRIGGER product_bank_transaction_read_only;")
    for e, code, version, source, content, fields, start, until, state, minimum in RULES:
        # Re-runs repair the threshold on rows imported before V9 existed; other rule columns are left as they are.
        q.append("INSERT INTO invoice_rule (tenant_id,enterprise_id,code,version,source,clause,content,required_fields,"
                 f"effective_from,effective_until,state,min_amount_cents) VALUES ({lit(TENANT)},{lit(e)},{lit(code)},{lit(version)},"
                 f"{lit(source)},'全文',{lit(content)},{lit(json.dumps(fields))}::jsonb,{lit(start)},{lit(until)},{lit(state)},{lit(minimum)}) "
                 "ON CONFLICT (tenant_id,enterprise_id,code,version,clause) DO UPDATE SET min_amount_cents = EXCLUDED.min_amount_cents "
                 "WHERE invoice_rule.min_amount_cents IS DISTINCT FROM EXCLUDED.min_amount_cents;")
    q.append("COMMIT;")
    return "\n".join(q) + "\n"


DIRECT_DB = None  # (host, password) when --direct-db is used


def psql(project, sql, csv=False):
    if DIRECT_DB:
        return _direct(sql, csv)
    cmd = ["docker", "compose", "--project-directory", str(ROOT), "-p", project, "exec", "-T", "db",
           "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "tax_product", "-d", "tax_product"] + (["-At", "-F", "|"] if csv else [])
    result = subprocess.run(cmd, input=sql.encode("utf-8"), capture_output=True)
    if result.returncode:
        sys.stderr.write(result.stderr.decode("utf-8", "replace"))
        raise SystemExit("psql failed")
    return result.stdout.decode("utf-8")


def _direct(sql, csv):
    """Same contract as psql(): csv=True returns rows joined like `psql -At -F '|'`."""
    import psycopg
    host, password = DIRECT_DB
    with psycopg.connect(host=host, port=5432, user="tax_product", dbname="tax_product", password=password,
                         autocommit=True, connect_timeout=10) as conn:
        cursor = conn.execute(sql)  # no parameters: multiple statements are allowed
        if not csv:
            return ""
        return "\n".join("|".join("" if v is None else str(v) for v in row) for row in cursor.fetchall())


def read_back(project):
    rows = psql(project, f"""
      SELECT 'inv', enterprise_id, to_char(accounting_period,'YYYY-MM'), count(*), sum(amount_cents), 0
        FROM product_invoice WHERE tenant_id='{TENANT}' GROUP BY 2,3
      UNION ALL
      SELECT 'bank', enterprise_id, to_char(accounting_period,'YYYY-MM'), count(*),
             coalesce(sum(amount_cents) FILTER (WHERE direction='expense'),0),
             coalesce(sum(amount_cents) FILTER (WHERE direction='income'),0)
        FROM product_bank_transaction WHERE tenant_id='{TENANT}' GROUP BY 2,3;
    """, csv=True)
    out = {}
    for line in rows.splitlines():
        kind, e, p, n, a, b = line.split("|")
        s = out.setdefault((e, p), dict(EMPTY))
        if kind == "inv":
            s.update(invoices=int(n), invoice_cents=int(a))
        else:
            s.update(bank=int(n), expense_cents=int(a), income_cents=int(b))
    rules = psql(project, "SELECT enterprise_id, code, version, state, effective_from, coalesce(effective_until::text,'-'), "
                          f"required_fields::text, coalesce(min_amount_cents::text,'-') FROM invoice_rule WHERE tenant_id='{TENANT}' ORDER BY 1,2,3;", csv=True).splitlines()
    grants = psql(project, "SELECT a.username, g.enterprise_id, g.role FROM enterprise_grant g JOIN product_account a USING (account_id) "
                           f"WHERE g.tenant_id='{TENANT}' ORDER BY 1,2;", csv=True).splitlines()
    return out, rules, grants


def yuan(c):
    return f"{c // 100}.{c % 100:02d}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="Compose project name, e.g. tax-product-p8 (not needed with --direct-db)")
    parser.add_argument("--direct-db", action="store_true",
                        help="connect to the compose `db` service directly (used by start.ps1/start.sh inside the importer image)")
    parser.add_argument("--db-host", default="db")
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX,
                        help="official 02_示例数据.xlsx (default: bundled product/data/contest/02_示例数据.xlsx)")
    parser.add_argument("--check-only", action="store_true", help="only read back and compare, write nothing")
    parser.add_argument("--allow-main", action="store_true", help="required to write outside a tax-product-p8* project")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    global DIRECT_DB
    if args.direct_db:
        password = read_env(ROOT / ".env")[1].get("PRODUCT_DB_PASSWORD")
        if not password:
            raise SystemExit("PRODUCT_DB_PASSWORD missing in .env")
        DIRECT_DB = (args.db_host, password)
        args.project = args.project or "direct"
    elif not args.project:
        parser.error("--project is required unless --direct-db is used")
    if not args.project.startswith("tax-product-p8") and not args.allow_main and not args.check_only:
        raise SystemExit("Refusing to write outside an isolated tax-product-p8* project without --allow-main")
    names, invoices, bank, published = load_workbook_data(args.xlsx)
    assert len(invoices) == EXPECTED_INVOICES and len(bank) == EXPECTED_BANK, (len(invoices), len(bank))
    computed = summarize(invoices, bank)
    for key, value in published.items():
        assert computed.get(key, EMPTY) == value, ("workbook summary differs from its detail rows", key, value, computed.get(key))
    if not args.check_only:
        passwords, added = ensure_passwords(ROOT / ".env")
        psql(args.project, build_sql(names, invoices, bank, passwords))
        print("imported; new .env keys:", ", ".join(added) or "none")
    db, rules, grants = read_back(args.project)
    ok = True
    print("enterprise period  invoices bank  invoice_total  expense_total  income_total  match")
    for key in sorted(published):
        expected, actual = published[key], db.get(key, EMPTY)
        match = actual == expected
        ok &= match
        print(f"{key[0]:10} {key[1]:7} {actual['invoices']:8} {actual['bank']:4} {yuan(actual['invoice_cents']):>14} "
              f"{yuan(actual['expense_cents']):>14} {yuan(actual['income_cents']):>13}  {'OK' if match else 'MISMATCH ' + str(expected)}")
    total_inv, total_bank = sum(v["invoices"] for v in db.values()), sum(v["bank"] for v in db.values())
    print(f"totals: invoices={total_inv} bank={total_bank}")
    print("rules:", *rules, sep="\n  ")
    print("grants:", *grants, sep="\n  ")
    ok &= total_inv == EXPECTED_INVOICES and total_bank == EXPECTED_BANK
    print("RESULT", "PASS" if ok else "FAIL", flush=True)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
