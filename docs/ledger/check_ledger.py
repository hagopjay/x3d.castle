#!/usr/bin/env python3
"""Check the numbers the Castle docs state against the files they came from.

usage: python3 -I -B docs/ledger/check_ledger.py [--ledger docs/ledger/claims.jsonl] [--root .]

One JSON object per line in claims.jsonl. Each entry ties a number written in a doc to the file that holds it:

  where        the doc that states the number (path from the repo root)
  where_quote  the exact words in that doc, whitespace folded; the value must be written inside them
  value        the number
  source       the file the number comes from
  op           how the source gives it:
                 quote        `quote` is a run of whole tokens in the source and the value is one of its numbers
                 sum          sum of the numeric field `key` over a JSON array of records
                 count        number of records in a JSON array
                 count_where  number of records where every [key, "==" | ">" | "<", n] in `when` holds
                 lines        number of lines in the source (the doc says "about N": `approx` is the allowed relative gap)

Verdicts: verified (found and the value agrees), check (the doc says something the file does not give). Exit 1 if any entry is check.
No network, no model, standard library only. A verified entry says the doc and the file agree; it does not say the file is right.
"""
import argparse
import json
import re
import sys

sys.dont_write_bytecode = True
TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|-?\d[\d,]*(?:\.\d+)?")


def fold(text):
    return " ".join(text.split())


def tokens(text):
    return [t.replace(",", "") if t[0] in "-0123456789" else t for t in TOKEN.findall(text)]


def numbers_in(text):
    out = []
    for t in TOKEN.findall(text):
        if t[0] in "-0123456789":
            out.append(float(t.replace(",", "")))
    return out


def find_run(needle, hay):
    n = tokens(needle)
    h = tokens(hay)
    if not n:
        return -1
    for i in range(len(h) - len(n) + 1):
        if h[i:i + len(n)] == n:
            return i
    return -1


def read(root, path):
    with open(f"{root}/{path}", encoding="utf-8") as fh:
        return fh.read()


def check(entry, root):
    """Return (verdict, note)."""
    try:
        doc = read(root, entry["where"])
    except OSError as exc:
        return "check", f"cannot read {entry['where']}: {exc.strerror}"
    wq = entry["where_quote"]
    if fold(wq) not in fold(doc):
        return "check", "where_quote is not in the doc (the doc changed, or the quote was copied wrongly)"
    value = entry["value"]
    if float(value) not in numbers_in(wq):
        return "check", f"the value {value} is not written inside where_quote"
    try:
        text = read(root, entry["source"])
    except OSError as exc:
        return "check", f"cannot read {entry['source']}: {exc.strerror}"
    op = entry["op"]
    if op == "quote":
        if find_run(entry["quote"], text) < 0:
            return "check", "quote is not a run of whole tokens in the source"
        if float(value) not in numbers_in(entry["quote"]):
            return "check", "the value is not a number of the quote"
        return "verified", "quote found in the source and holds the value"
    if op == "lines":
        n = len(text.splitlines())
        gap = abs(n - value) / max(n, 1)
        ok = gap <= entry.get("approx", 0.0)
        return ("verified" if ok else "check"), f"source has {n} lines, doc says {value}"
    records = json.loads(text)
    if op == "count":
        got = len(records)
    elif op == "sum":
        got = sum(r[entry["key"]] for r in records)
    elif op == "count_where":
        ops = {"==": lambda a, b: a == b, ">": lambda a, b: a > b, "<": lambda a, b: a < b}
        got = sum(1 for r in records if all(ops[o](r[k], n) for k, o, n in entry["when"]))
    else:
        return "check", f"unknown op {op!r}"
    return ("verified" if got == value else "check"), f"recomputed {got}, doc says {value}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", default="docs/ledger/claims.jsonl")
    ap.add_argument("--root", default=".")
    a = ap.parse_args(argv)
    bad = total = 0
    with open(f"{a.root}/{a.ledger}", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            entry = json.loads(line)
            verdict, note = check(entry, a.root)
            total += 1
            bad += verdict != "verified"
            print(f"{entry['id']:8} {verdict:9} {note}")
    print(f"{total} entries, {total - bad} verified, {bad} check")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
