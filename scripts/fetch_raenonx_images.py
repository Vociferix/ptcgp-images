#!/usr/bin/env python3
"""Download card images for a set from RaenonX, named by set collection number.

RaenonX keys cards by internal IDs (e.g. PK_10_019620_00). The global-master
endpoint maps each card to its (expansion, collection number) pairs, which is
what this script uses to write files as <set>/<num>.png.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GLOBAL_MASTER_URL = "https://ptcgp.raenonx.cc/api/data/global-master"
CDN_BASE = "https://cdn.raenonx.cc/api/image/ptcgp"
USER_AGENT = (
    "ptcgp-images/0.1 (https://github.com/user/ptcgp-images; educational/archival)"
)

MIN_DELAY_S = 0.3
DEFAULT_JOBS = 4
MAX_RETRIES = 3
CACHE_MAX_AGE_S = 24 * 60 * 60

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class RateLimiter:
    """Enforces a minimum gap between the start of successive requests."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_at - now
            self._next_at = max(now, self._next_at) + self._min_interval
        if sleep_for > 0:
            time.sleep(sleep_for)


def http_get(url: str, limiter: RateLimiter | None = None) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        if limiter:
            limiter.wait()
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as err:
            # 4xx other than rate limiting will not improve on retry.
            if err.code != 429 and 400 <= err.code < 500:
                raise
            last_err = err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last_err = err
        if attempt < MAX_RETRIES:
            time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after {MAX_RETRIES} attempts: {last_err}")


def normalize_set_id(raw: str) -> str:
    """RaenonX expansion id -> repo set directory name (PROMO-A -> P-A)."""
    if raw.startswith("PROMO-"):
        return "P-" + raw[len("PROMO-") :]
    return raw


def load_global_master(cache_path: Path, refresh: bool) -> dict:
    if not refresh and cache_path.is_file():
        age = time.time() - cache_path.stat().st_mtime
        if age < CACHE_MAX_AGE_S:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass  # fall through to a fresh fetch

    print(f"Fetching {GLOBAL_MASTER_URL} ...", file=sys.stderr)
    raw = http_get(GLOBAL_MASTER_URL)
    data = json.loads(raw)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(cache_path)
    return data


def index_by_set(master: dict) -> dict[str, dict[int, str]]:
    """set id -> {collection number: card id}."""
    entries = master.get("cardEntryMap")
    if not isinstance(entries, dict):
        raise RuntimeError("cardEntryMap missing from global-master")

    index: dict[str, dict[int, str]] = defaultdict(dict)
    for card_id, entry in entries.items():
        for coll in entry.get("collectionNums") or []:
            expansion = (coll.get("expansion") or {}).get("id")
            num = coll.get("num")
            if not expansion or not isinstance(num, int):
                continue
            set_id = normalize_set_id(expansion)
            existing = index[set_id].get(num)
            if existing and existing != card_id:
                print(
                    f"  warning: {set_id} #{num} maps to both {existing} and "
                    f"{card_id}; keeping {existing}",
                    file=sys.stderr,
                )
                continue
            index[set_id][num] = card_id
    return index


def image_url(card_id: str, locale: str) -> str:
    # Matches the site's own asset loader. The path is intentionally not
    # percent-encoded; the CDN rejects encoded slashes in the `url` param.
    return f"{CDN_BASE}?format=png&url=/images/game/card/full/{locale}/{card_id}.png"


def ensure_png(data: bytes, card_id: str) -> bytes:
    """Return PNG bytes, converting if the CDN handed back another format."""
    if data.startswith(PNG_MAGIC):
        return data

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        pass
    else:
        with Image.open(io.BytesIO(data)) as img:
            out = io.BytesIO()
            img.convert("RGBA").save(out, format="PNG")
            return out.getvalue()

    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        proc = subprocess.run(
            [magick, "-", "png:-"], input=data, capture_output=True, check=False
        )
        if proc.returncode == 0 and proc.stdout.startswith(PNG_MAGIC):
            return proc.stdout
        raise RuntimeError(
            f"{card_id}: PNG conversion failed: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )

    raise RuntimeError(
        f"{card_id}: response was not a PNG and neither Pillow nor ImageMagick "
        "is available to convert it"
    )


def download_card(
    num: int,
    card_id: str,
    dest: Path,
    locale: str,
    limiter: RateLimiter,
    force: bool,
) -> tuple[int, str]:
    """Returns (num, status) where status is one of: ok, skipped, error: ..."""
    out_path = dest / f"{num:03d}.png"
    if out_path.exists() and not force:
        return num, "skipped"

    try:
        data = http_get(image_url(card_id, locale), limiter)
        data = ensure_png(data, card_id)
    except Exception as err:  # noqa: BLE001 - reported per card, not fatal
        return num, f"error: {err}"

    tmp = out_path.with_suffix(".png.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, out_path)
    return num, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download RaenonX card images for a set, named by set number."
    )
    parser.add_argument(
        "sets",
        nargs="*",
        metavar="SET",
        help="Set codes to download, e.g. B4 P-B. Use --list-sets to see options.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "cards",
        help="Root directory holding per-set folders (default: <repo>/cards)",
    )
    parser.add_argument(
        "--locale", default="en", help="Card image locale (default: en)"
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=f"Concurrent downloads (default: {DEFAULT_JOBS})",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Re-download images that already exist",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without writing files",
    )
    parser.add_argument(
        "--list-sets", action="store_true", help="List available sets and exit"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Ignore the cached global-master JSON"
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(__file__).resolve().parent / ".cache" / "global-master.json",
        help="Path to the cached global-master JSON",
    )
    args = parser.parse_args()

    if not args.sets and not args.list_sets:
        parser.error("no sets given (use --list-sets to see available codes)")

    master = load_global_master(args.cache, args.refresh)
    index = index_by_set(master)

    if args.list_sets:
        for set_id in sorted(index):
            nums = index[set_id]
            print(f"{set_id:<8} {len(nums):>4} cards (1-{max(nums)})")
        return 0

    limiter = RateLimiter(MIN_DELAY_S)
    exit_code = 0

    for set_id in args.sets:
        cards = index.get(set_id)
        if not cards:
            print(f"{set_id}: no cards found in global-master", file=sys.stderr)
            exit_code = 1
            continue

        highest = max(cards)
        gaps = [n for n in range(1, highest + 1) if n not in cards]
        print(f"{set_id}: {len(cards)} cards (1-{highest})")
        if gaps:
            print(f"  note: no card entry for numbers {gaps}", file=sys.stderr)

        if args.dry_run:
            for num in sorted(cards):
                print(f"  {num:03d}.png <- {cards[num]}")
            continue

        dest = args.output_dir / set_id
        dest.mkdir(parents=True, exist_ok=True)

        results: list[tuple[int, str]] = []
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [
                pool.submit(
                    download_card, num, cards[num], dest, args.locale, limiter,
                    args.force,
                )
                for num in sorted(cards)
            ]
            for done, future in enumerate(futures, start=1):
                num, status = future.result()
                results.append((num, status))
                if status.startswith("error"):
                    print(f"  {num:03d}.png {status}", file=sys.stderr)
                print(
                    f"\r  {done}/{len(futures)}", end="", file=sys.stderr, flush=True
                )
        print("", file=sys.stderr)

        ok = sum(1 for _, s in results if s == "ok")
        skipped = sum(1 for _, s in results if s == "skipped")
        errors = [n for n, s in results if s.startswith("error")]
        print(f"  downloaded {ok}, skipped {skipped}, failed {len(errors)}")
        if errors:
            print(f"  failed numbers: {sorted(errors)}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
