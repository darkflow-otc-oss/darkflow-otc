"""
DARKFLOW OTC — Project Health Check
Verifica integridade de todos os arquivos e módulos do projeto.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, UTC

ROOT = Path(__file__).parent.parent

EXPECTED_FILES = [
    "main.py",
    "requirements.txt",
    "docker-compose.yml",
    "Dockerfile",
    ".env",
    "README.md",
    "config/settings.py",
    "capture/__init__.py",
    "capture/orchestrator.py",
    "capture/playwright/quotex_browser.py",
    "capture/playwright/websocket_listener.py",
    "capture/recorder/raw_recorder.py",
    "database/postgres/schema.sql",
    "database/postgres/models.py",
    "database/postgres/connection.py",
    "patterns/features/candle_features.py",
    "patterns/features/sequence_encoder.py",
    "patterns/detectors/continuation_detector.py",
    "patterns/detectors/reversal_detector.py",
    "patterns/detectors/fake_break_detector.py",
    "patterns/detectors/pattern_pipeline.py",
    "patterns/probability/probability_engine.py",
    "ai/reasoning/ai_reasoner.py",
    "api/routes/candles.py",
    "api/routes/patterns.py",
]

EXPECTED_DIRS = [
    "ai/embeddings",
    "ai/classifiers",
    "ai/reasoning",
    "capture/playwright",
    "capture/websocket",
    "capture/canvas",
    "capture/recorder",
    "dashboard",
    "database/postgres",
    "database/vectors",
    "database/cache",
    "data",
    "logs/websocket",
    "logs/patterns",
    "logs/ai",
    "logs/errors",
    "logs/sessions",
    "patterns/features",
    "patterns/detectors",
    "patterns/clustering",
    "patterns/probability",
    "api/routes",
    "api/services",
    "config",
    "backtests",
    "notebooks",
    "scripts",
    "tests",
    "skills",
]

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def check():
    print(f"\n{BOLD}{'━'*60}{RESET}")
    print(f"{BOLD}  🔥 DARKFLOW OTC — PROJECT HEALTH CHECK{RESET}")
    print(f"  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{BOLD}{'━'*60}{RESET}\n")

    ok = 0
    missing = 0

    # ── Check Dirs ────────────────────────────────────────────────
    print(f"{BOLD}📁 DIRECTORIES{RESET}")
    for d in EXPECTED_DIRS:
        path = ROOT / d
        if path.is_dir():
            print(f"  {GREEN}✅{RESET} {d}")
            ok += 1
        else:
            print(f"  {RED}❌{RESET} {d}  {YELLOW}← MISSING{RESET}")
            missing += 1

    # ── Check Files ───────────────────────────────────────────────
    print(f"\n{BOLD}📄 FILES{RESET}")
    for f in EXPECTED_FILES:
        path = ROOT / f
        if path.is_file():
            size = path.stat().st_size
            lines = sum(1 for _ in open(path, encoding="utf-8", errors="ignore"))
            print(f"  {GREEN}✅{RESET} {f:<55} {BLUE}{lines} lines{RESET}")
            ok += 1
        else:
            print(f"  {RED}❌{RESET} {f:<55} {YELLOW}← MISSING{RESET}")
            missing += 1

    # ── Summary ───────────────────────────────────────────────────
    total = ok + missing
    pct = round((ok / total) * 100) if total > 0 else 0

    print(f"\n{BOLD}{'━'*60}{RESET}")
    print(f"{BOLD}  SUMMARY{RESET}")
    print(f"  Total   : {total}")
    print(f"  {GREEN}OK      : {ok}{RESET}")
    print(f"  {RED}Missing : {missing}{RESET}")
    print(f"  Coverage: {GREEN if pct >= 80 else YELLOW}{pct}%{RESET}")

    if missing == 0:
        print(f"\n  {GREEN}{BOLD}🚀 PROJECT IS COMPLETE — READY TO RUN{RESET}")
    elif missing <= 5:
        print(f"\n  {YELLOW}{BOLD}⚠️  ALMOST THERE — {missing} file(s) missing{RESET}")
    else:
        print(f"\n  {RED}{BOLD}🔧 IN PROGRESS — {missing} file(s) missing{RESET}")

    print(f"{BOLD}{'━'*60}{RESET}\n")
    return missing == 0


if __name__ == "__main__":
    success = check()
    sys.exit(0 if success else 1)
