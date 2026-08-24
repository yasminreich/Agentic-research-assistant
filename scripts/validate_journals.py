"""Check every allowlist entry against what OpenAlex actually reports.

The failure mode this guards against is silent: an entry that looks like a real
journal but never matches anything, because OpenAlex spells it differently. That
bug shipped once already — `"dairy science"` was added when OpenAlex reports
`"Journal of Dairy Science"`, and matching is exact after normalization, so the
entry could never fire.

This needs the network, so it is NOT part of the offline test suite. Run it by
hand after editing `app/journals.py`:

    python -m scripts.validate_journals              # every field
    python -m scripts.validate_journals microbiome   # one field

For each entry it asks OpenAlex's /sources endpoint for that name and reports:

    ok        OpenAlex reports a source whose normalized name matches exactly
    MISMATCH  a close source exists under a different name — usually the fix,
              shown so it can be pasted straight into JOURNALS_BY_FIELD
    MISSING   nothing similar found; likely a typo or a defunct title

Exits non-zero if anything is not `ok`, so it can gate a release if wanted.

NOTE ON RATE LIMITS: OpenAlex meters usage and a busy day can exhaust the free
daily budget ("Insufficient budget ... Resets at midnight UTC"). If every lookup
fails that way, wait for the reset rather than retrying harder. Setting
OPENALEX_MAILTO opts into the politer, faster pool.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from app.journals import JOURNALS_BY_FIELD, normalize_journal_name

SOURCES_ENDPOINT = "https://api.openalex.org/sources"
PAUSE_SECONDS = 1.0


def lookup(name: str, *, attempts: int = 4) -> list[dict]:
    """Return the top OpenAlex sources matching `name`, with backoff on 429."""
    params = {"search": name, "per-page": 3, "select": "display_name,works_count"}
    # Opt into the polite pool only if the operator configured an address.
    mailto = os.environ.get("OPENALEX_MAILTO", "").strip()
    if mailto:
        params["mailto"] = mailto

    url = f"{SOURCES_ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response).get("results", [])
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))
    return []


def classify(entry: str, results: list[dict]) -> tuple[str, str]:
    """Return `(status, detail)` for one allowlist entry."""
    if not results:
        return "MISSING", "no OpenAlex source found"
    for source in results:
        if normalize_journal_name(source["display_name"]) == entry:
            return "ok", source["display_name"]
    best = results[0]
    return "MISMATCH", f"OpenAlex says {best['display_name']!r}"


def main() -> int:
    wanted = sys.argv[1] if len(sys.argv) > 1 else None
    if wanted and wanted not in JOURNALS_BY_FIELD:
        print(f"Unknown field {wanted!r}. Valid: {', '.join(sorted(JOURNALS_BY_FIELD))}")
        return 2

    problems: list[str] = []
    for field, entries in sorted(JOURNALS_BY_FIELD.items()):
        if wanted and field != wanted:
            continue
        print(f"\n### {field}")
        for entry in sorted(entries):
            try:
                results = lookup(entry)
            except Exception as exc:  # noqa: BLE001 - report and keep going
                print(f"  ERROR     {entry}  ({exc})")
                problems.append(f"{field}/{entry}: {exc}")
                continue

            status, detail = classify(entry, results)
            print(f"  {status:9} {entry}" + (f"  -> {detail}" if status != "ok" else ""))
            if status != "ok":
                problems.append(f"{field}/{entry}: {detail}")
            time.sleep(PAUSE_SECONDS)

    print(f"\n{'-' * 60}")
    if problems:
        print(f"{len(problems)} entr{'y' if len(problems) == 1 else 'ies'} need attention:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("Every entry matches a real OpenAlex source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
