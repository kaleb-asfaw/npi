#!/usr/bin/env python3
"""
Scrape every available "Thru Games" NPI leaderboard snapshot for a season
from stats.ncaa.org's selection_rankings/nitty_gritties report.

The report page for any single date has a <select> dropdown listing every
snapshot date available this season, each with its own report id in the
URL (e.g. .../nitty_gritties/46696 for 11/09/2025 (Selections)). This script
reads that dropdown once, then re-fetches the report for every date in it
and saves the full leaderboard table -- one CSV per snapshot date -- so the
schedule data (scripts/scrape_ncaa.py) and NPI-over-time data can be joined
on team_id later.

Usage:
    # discover + scrape every snapshot date for a season (default 25-26)
    .venv/bin/python scripts/scrape_npi.py --season 24-25

    # just one date, for a quick sanity check
    .venv/bin/python scripts/scrape_npi.py --report-id 46696
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page

from scrape_ncaa import (
    DEFAULT_SEASON,
    REPO_ROOT,
    season_paths,
    fetch,
    launch_browser,
    run_with_resilience,
)

TABLE_ID = "selection_rankings_nitty_gritty_data_table"


def get_snapshot_dates(page: Page, nitty_gritty_url: str) -> list[tuple[str, str, str]]:
    """Returns [(report_id, iso_date, label), ...] from the "Thru Games"
    dropdown, e.g. ("46696", "2025-11-09", "selections")."""
    html = fetch(page, nitty_gritty_url)
    soup = BeautifulSoup(html, "lxml")
    select = soup.find("select", id="selection_ranking_id")
    if select is None:
        sys.exit("Couldn't find the 'Thru Games' date dropdown -- page structure may have changed.")

    snapshots = []
    for option in select.find_all("option"):
        report_id = option.get("value", "").strip()
        text = option.get_text(strip=True)
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})\s*(?:\((\w+)\))?$", text)
        if not report_id or not m:
            continue
        mm, dd, yyyy, label = m.groups()
        iso_date = f"{yyyy}-{mm}-{dd}"
        snapshots.append((report_id, iso_date, (label or "").lower()))
    return snapshots


def parse_npi_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id=TABLE_ID)
    if table is None:
        return []

    headers = [th.get_text(" ", strip=True) for th in table.find("thead").find_all("th")]
    # The 4th column's header bakes the snapshot date into its name (e.g.
    # "12/06/2025 Result") -- normalize so every snapshot's CSV has the same
    # column names and can be freely concatenated.
    headers = [re.sub(r"^\d{2}/\d{2}/\d{4}\s+Result$", "Result", h) for h in headers]

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) != len(headers):
            continue
        record = {h: c.get_text(" ", strip=True) for h, c in zip(headers, cells)}
        team_link = cells[0].find("a")
        record["team_id"] = re.search(r"/teams/(\d+)", team_link["href"]).group(1) if team_link else ""
        rows.append(record)
    return rows


def save_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_path.write_text("")
        return
    # dict.fromkeys instead of a set -- a set's iteration order is randomized
    # per-process, which would give every CSV a different, arbitrary column
    # order. This preserves first-seen (i.e. natural table) order instead.
    fieldnames = list(dict.fromkeys(k for row in rows for k in row.keys()))
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def scrape_one_snapshot(page: Page, report_id: str, iso_date: str, label: str, out_dir: Path) -> None:
    url = f"https://stats.ncaa.org/selection_rankings/nitty_gritties/{report_id}"
    html = fetch(page, url)
    rows = parse_npi_table(html)
    for row in rows:
        row["snapshot_date"] = iso_date
        row["snapshot_label"] = label
    suffix = f"_{label}" if label else ""
    out_path = out_dir / f"{iso_date}{suffix}.csv"
    save_csv(rows, out_path)
    print(f"[{iso_date}{suffix}] {len(rows)} teams -> {out_path.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", default=DEFAULT_SEASON, help="Season like 25-26 or 24-25 (sets default URL and output dir)")
    parser.add_argument("--nitty-gritty-url", default=None,
                         help="Any single nitty-gritties report URL for this season -- used to discover all snapshot dates (default: the season's seed report)")
    parser.add_argument("--report-id", default=None, help="Scrape only this one report id (skips date discovery)")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--delay", type=float, default=4.0, help="Base seconds to sleep between requests")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--headful", dest="headless", action="store_false",
                         help="Show the browser window (needed -- headless gets blocked by Akamai)")
    args = parser.parse_args()
    paths = season_paths(args.season)
    args.nitty_gritty_url = args.nitty_gritty_url or paths["url"]
    args.out_dir = args.out_dir or paths["npi"]

    with sync_playwright() as p:
        if args.report_id:
            browser, _, page = launch_browser(p, args.headless)
            html = fetch(page, f"https://stats.ncaa.org/selection_rankings/nitty_gritties/{args.report_id}")
            rows = parse_npi_table(html)
            for row in rows:
                row["snapshot_date"] = ""
                row["snapshot_label"] = ""
            save_csv(rows, args.out_dir / f"{args.report_id}.csv")
            print(f"[{args.report_id}] {len(rows)} teams -> {(args.out_dir / f'{args.report_id}.csv').relative_to(REPO_ROOT)}")
            browser.close()
            return

        browser, _, page = launch_browser(p, args.headless)
        snapshots = get_snapshot_dates(page, args.nitty_gritty_url)
        browser.close()
        print(f"Found {len(snapshots)} snapshot dates")

        pending = [
            (rid, date, label) for rid, date, label in snapshots
            if not (args.out_dir / f"{date}{'_' + label if label else ''}.csv").exists()
        ]
        if len(pending) < len(snapshots):
            print(f"{len(snapshots) - len(pending)} snapshots already scraped, skipping")

        def process(page, item):
            rid, date, label = item
            scrape_one_snapshot(page, rid, date, label, args.out_dir)

        failures = run_with_resilience(
            p, args.headless, pending, process,
            label_fn=lambda it: f"[{it[1]}]", delay=args.delay,
        )
        if failures:
            print(f"\n{len(failures)} snapshots failed: {failures}")


if __name__ == "__main__":
    main()
