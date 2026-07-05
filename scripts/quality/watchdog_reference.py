"""
Single-process watchdog for reference.aspose.org retranslation.
Runs ONE campaign at a time, commits after each run, restarts on crash.
"""
import subprocess, sys, time, json
from pathlib import Path

HUGO_DIR     = Path("C:/Users/prora/OneDrive/Documents/GitHub/hugo-translator")
ASPOSE_DIR   = Path("C:/Users/prora/OneDrive/Documents/GitHub/aspose.org")
PYTHON       = str(HUGO_DIR / ".venv/Scripts/python.exe")
SCRIPT       = str(HUGO_DIR / "scripts/quality/aspose_org_governed_retranslate.py")
CONTENT_ROOT = str(ASPOSE_DIR / "content/reference.aspose.org")
RUN_ID       = "aspose_org_multisite_20260704_012331"
LOG          = HUGO_DIR / "data/logs/reference_retranslate_single.log"
CP_DIR       = HUGO_DIR / ".local/evidences/reference.aspose.org" / RUN_ID / "checkpoints"

# ar first (43% done, closest to completion), then el, then rest alphabetically
ALL_LOCALES = "ar,el,bg,ca,cs,da,de,es,fa,fi,fr,he,hi,hr,hu,id,it,ja,ko,lt,lv,ms,nl,no,pl,pt,ro,ru,sk,sr,sv,th,tr,uk,vi,zh"

RETRANSLATE_CMD = [
    PYTHON, SCRIPT,
    "--site", "reference.aspose.org",
    "--run-id", RUN_ID,
    "--resume", "--retry-failed",
    "--shard-id", "latin-a",
    "--only-locales", ALL_LOCALES,
    "--model", "nllb_200_1.3b",
    "--content-root", CONTENT_ROOT,
]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def current_item():
    cur = CP_DIR / "current.latin-a.json"
    try:
        d = json.loads(cur.read_text(encoding="utf-8"))
        wi = d.get("work_item", {})
        return f"{wi.get('locale','?')} / {wi.get('relative_path','?')}"
    except Exception:
        return "(unknown)"


def commit_new_files():
    result = subprocess.run(
        ["git", "status", "--short", "--", "content/reference.aspose.org/"],
        capture_output=True, text=True, encoding="utf-8", cwd=ASPOSE_DIR
    )
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        log("No new reference files to commit.")
        return

    subprocess.run(["git", "add", "content/reference.aspose.org/"], cwd=ASPOSE_DIR, check=True)

    from collections import Counter
    lc = Counter()
    for line in lines:
        parts = line.strip().split()[-1].replace("\\", "/").split("/")
        for i, p in enumerate(parts):
            if p == "reference.aspose.org" and i + 1 < len(parts):
                lc[parts[i + 1]] += 1
                break

    n = len(lines)
    lang_summary = ", ".join(f"{k} ({v})" for k, v in sorted(lc.items()))
    locale_keys  = "/".join(sorted(lc.keys()))

    msg = (
        f"chore(reference): translate {n} reference pages {locale_keys}\n\n"
        f"{n} translation files across reference.aspose.org.\n"
        f"- Model: nllb_200_1.3b\n"
        f"- Languages: {lang_summary}\n\n"
        f"Run ID: {RUN_ID}:reference.aspose.org\n"
        f"Site: reference.aspose.org\n\n"
        f"Co-Authored-By: Hugo Translator <hugo-translator@aspose.net>"
    )
    r = subprocess.run(["git", "commit", "-m", msg], cwd=ASPOSE_DIR,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode == 0:
        log(f"Committed {n} files: {lang_summary}")
    else:
        log(f"Commit skipped: {r.stderr.strip()[:120]}")


log("=== reference.aspose.org single-process watchdog starting ===")
log(f"Locales: {ALL_LOCALES}")

run = 0
while True:
    run += 1
    log(f"=== Run #{run} ===")

    result = subprocess.run(RETRANSLATE_CMD, cwd=HUGO_DIR)
    exit_code = result.returncode

    log(f"Run #{run} exited (code={exit_code}). Last item: {current_item()}")
    commit_new_files()

    if exit_code == 0:
        log("Clean exit — sleeping 120s before next run...")
        time.sleep(120)
    else:
        log(f"Non-zero exit ({exit_code}) — restarting in 15s...")
        time.sleep(15)
