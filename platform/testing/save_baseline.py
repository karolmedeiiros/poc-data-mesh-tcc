#!/usr/bin/env python3
"""Salva os relatórios atuais como baseline de referência."""

import json
import os
import shutil
from datetime import datetime, timezone

REPORTS_DIR = "reports"
BASELINE_DIR = os.path.join(REPORTS_DIR, "baseline")
META_FILE = os.path.join(BASELINE_DIR, "baseline_metadata.json")


def main():
    os.makedirs(BASELINE_DIR, exist_ok=True)
    for filename in os.listdir(REPORTS_DIR):
        if filename.endswith(".json"):
            src = os.path.join(REPORTS_DIR, filename)
            dst = os.path.join(BASELINE_DIR, filename)
            shutil.copy2(src, dst)

    metadata = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Relatórios de referência do estado verde da arquitetura",
        "files": sorted(os.listdir(BASELINE_DIR)),
    }
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print("✅ Baseline salva em reports/baseline/")
    print(f"📄 Metadados: {META_FILE}")


if __name__ == "__main__":
    main()
