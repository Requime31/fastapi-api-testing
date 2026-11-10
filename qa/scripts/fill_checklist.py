"""
Transfers run results (qa/runs/<CL>_<date>.json) into a checklist markdown file:
status column, actual result / note, links to filed issues, run summary table,
defect and question tables.

Usage: python qa/scripts/fill_checklist.py <checklist.md> <run.json> <triage.json>

triage.json:
{
  "executed_by": "...", "run_date": "...", "jira_task": 4,
  "sections": [["CRT", "1. Create"], ["RL-01..RL-12", "1. Limits"], ...],  # prefixes or ID ranges → summary row label
  "defects":   [{"key": "FAT-24", "issue": 24, "checks": ["PAG-13"], "title": "...", "severity": "Major"}],
  "questions": [{"key": "FAT-30", "issue": 30, "checks": ["PAG-24"], "question": "..."}],
  "links": {"CRT-24": [13]}                          # extra issue links per check (issue numbers)
}
Before filing, "issue" may be null — the working key (e.g. "D-01") is shown instead of a link.
"""
import json
import re
import sys
from pathlib import Path

REPO_ISSUES = "https://github.com/Requime31/fastapi-api-testing/issues"
MARK = {"pass": "✅", "fail": "❌", "blocked": "⚠️", "skip": "⏭"}


def ref(key, issue):
    return f"[{key}]({REPO_ISSUES}/{issue})" if issue else key


def esc(s):
    return s.replace("|", "\\|").replace("\n", " ")


def short(s, n=130):
    return s if len(s) <= n else s[: n - 1] + "…"


def in_section(cid, spec):
    for part in spec.split(","):
        if ".." in part:
            lo, hi = part.split("..")
            pre = lo.rsplit("-", 1)[0]
            if cid.startswith(pre + "-") and int(lo.rsplit("-", 1)[1]) <= int(cid.rsplit("-", 1)[1]) <= int(hi.rsplit("-", 1)[1]):
                return True
        elif cid.rsplit("-", 1)[0] == part:
            return True
    return False


def main(md_path, run_path, triage_path):
    md, run, tri = Path(md_path), json.loads(Path(run_path).read_text()), json.loads(Path(triage_path).read_text())
    res = run["results"]
    links: dict[str, list[str]] = {}
    for d in tri.get("defects", []) + tri.get("questions", []):
        for c in d["checks"]:
            links.setdefault(c, []).append(ref(d["key"], d.get("issue")))
    for c, nums in tri.get("links", {}).items():
        links.setdefault(c, []).extend(ref(f"FAT-{n}", n) for n in nums)
    prefixes = "|".join(sorted({x.split("-")[0] for p, _ in tri["sections"] for x in p.split(",")}))
    statuses = {}

    out = []
    for ln in md.read_text().split("\n"):
        m = re.match(rf"^\| ((?:{prefixes})-\d+) \|", ln)
        if m and m.group(1) in res:
            cid, r = m.group(1), res[m.group(1)]
            cells = ln.split(" | ")
            refs = " ".join(re.findall(r"R-\d+", cells[-1]))
            if r["status"] == "pass":
                comment = esc(r["note"]) if r["note"] else ""
            else:
                comment = f"Actual: {esc(short(r['actual']))}"
                if r["note"] and cid not in links:
                    comment += f". {esc(r['note'])}"
            if cid in links:
                comment += (" → " if comment else "") + "**" + ", ".join(dict.fromkeys(links[cid])) + "**"
            comment = " ".join(x for x in (comment, refs) if x)
            cells[-2] = MARK[r["status"]]
            cells[-1] = f"{comment} |" if comment else "|"
            ln = " | ".join(cells)
            statuses[cid] = r["status"]
        out.append(ln)
    t = "\n".join(out)

    t = t.replace("| Executed by | |", f"| Executed by | {tri['executed_by']} |")
    t = t.replace("| Run date | |", f"| Run date | {tri['run_date']} |")

    tot = {k: 0 for k in MARK}
    for prefs, label in tri["sections"]:
        c = {}
        for cid, st in statuses.items():
            if in_section(cid, prefs):
                c[st] = c.get(st, 0) + 1
        for k in tot:
            tot[k] += c.get(k, 0)
        t = re.sub(rf"\| {re.escape(label)} \| (\d+) \| \| \| \| \|",
                   f"| {label} | \\1 | {c.get('pass', 0)} | {c.get('fail', 0)} | {c.get('blocked', 0)} | {c.get('skip', 0)} |", t)
    total = sum(tot.values())
    rate = tot["pass"] / (total - tot["skip"]) * 100
    t = re.sub(r"\| \*\*Total\*\* \| \*\*(\d+)\*\* \| \| \| \| \|",
               f"| **Total** | **{total}** | **{tot['pass']}** | **{tot['fail']}** | **{tot['blocked']}** | **{tot['skip']}** |\n\n"
               f"Pass rate: **{rate:.1f}%** (excluding ⏭). "
               + ("The module meets" if rate >= 95 else "The module does not meet") + " the exit criterion \"≥ 95% passed\".", t)

    if tri.get("defects"):
        rows = "\n".join(f"| {ref(d['key'], d.get('issue'))} | {', '.join(d['checks'])} | {d['title']} | {d['severity']} |" for d in tri["defects"])
        t = t.replace("| Jira / GitHub | Check | Title | Severity |\n|---|---|---|---|\n| | | | |",
                      f"| Jira / GitHub | Check | Title | Severity |\n|---|---|---|---|\n{rows}")
        filed = all(d.get("issue") for d in tri["defects"])
        t = t.replace("**Defects found:**\n", "**Defects found:** " + (
            "filed in Jira (project FAT, parent FAT-1) and mirrored to GitHub Issues — key FAT-N matches issue #N.\n" if filed
            else "D-xx are working IDs until the defects are filed in Jira.\n"), 1)
    if tri.get("questions"):
        rows = "\n".join(f"| {ref(q['key'], q.get('issue'))} | {', '.join(q['checks'])} | {q['question']} | |" for q in tri["questions"])
        t = t.replace("| Jira / GitHub | Check | Question | Answer |\n|---|---|---|---|\n| | | | |",
                      f"| Jira / GitHub | Check | Question | Answer |\n|---|---|---|---|\n{rows}")
    md.write_text(t)
    print(f"{md.name}: {tot} of {total}, pass rate {rate:.1f}%")


if __name__ == "__main__":
    main(*sys.argv[1:4])
