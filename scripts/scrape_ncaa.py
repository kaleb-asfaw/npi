#!/usr/bin/env python3
"""
This template will scrape NCAA DIII {insert sport} schedule/results data 
from stats.ncaa.org.

Basic algorithm using Playwright Webscraping goes as follows:
    1. Collect all team urls by looping through the "Team" column
    in the default page (see global variable 'DEFAULT_NITTY_GRITTY_URL')

    2. Loop through each "Team"'s url and scrape the "Schedule/Results"
    (see the parse_schedule_table functionality)

   3. Save schedule table as CSV in research/data/wsoc/<season>/schedule/

Usage:
    # one-off sanity check against a single team (default: WashU, 603722)
    .venv/bin/python scripts/scrape_ncaa.py --team-id 603722

    # once the single-team output looks right, pull every team found on the
    # nitty gritties report
    .venv/bin/python scripts/scrape_ncaa.py --all

        ***  Script to pull all data is orchestrated in Main()  ***

"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import random
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEASON = "25-26"
# Any one nitty-gritties report id per season (the season's final/latest one).
# Used to discover the team list and, for NPI, every snapshot date. Find new
# seasons via stats.ncaa.org/selection_rankings/season_divisions/<id>/nitty_gritties
# (the year dropdown there lists every season; WSOC D-III: 25-26 = 18605, 24-25 = 18348).
SEASON_SEED_REPORTS = {
    "25-26": "47443",
    "24-25": "40158",
    "22-23": "48429",  # only 1 snapshot published (11/06/2022 Selections)
    "21-22": "48449",  # only 2 snapshots published (11/07/2021 Selections, 11/11/2021)
    # 23-24: no NPI report is exposed on the site's year dropdown; schedules
    # still work via the per-team year dropdown (see team_list_from_year_links).
    "23-24": None,
}
# Seasons whose team list is also derived from another season's saved raw team
# pages (each page has a year dropdown mapping that team to its id in every season).
YEAR_LINK_SOURCE_SEASON = "24-25"


def season_paths(season: str) -> dict[str, "Path | str"]:
    """Per-season default locations: research/data/wsoc/<season>/{schedule,npi,raw_html}."""
    if season not in SEASON_SEED_REPORTS:
        sys.exit(f"Unknown season {season!r}; add its seed report id to SEASON_SEED_REPORTS "
                 f"(known: {', '.join(SEASON_SEED_REPORTS)})")
    base = REPO_ROOT / "research" / "data" / "wsoc" / season
    return {
        "schedule": base / "schedule",
        "npi": base / "npi",
        "raw_html": base / "raw_html",
        "url": (f"https://stats.ncaa.org/selection_rankings/nitty_gritties/{SEASON_SEED_REPORTS[season]}"
                if SEASON_SEED_REPORTS[season] else None),
    }
WASHU_TEAM_ID = "603722"

BLOCKED_MARKERS = ("bm-verify", "Access Denied", "<title>&nbsp;</title>", "queue full")


def is_blocked(html: str) -> bool:
    if len(html) < 2000:
        return True
    return any(marker in html for marker in BLOCKED_MARKERS)


def accept_terms(page: Page) -> None:
    """stats.ncaa.org gates the site behind a "Continue to NCAA Statistics?"
    Terms and Conditions checkbox. The server only accepts the checkbox if the
    Terms link was opened first (otherwise it re-renders the form with
    "Please review the Terms and Conditions before continuing"), so open the
    link in a popup, close it, then tick the box and continue."""
    time.sleep(2)
    with page.context.expect_page() as popup:
        page.click("a[href*='terms-of-service']")
    popup.value.wait_for_load_state("domcontentloaded")
    time.sleep(4)  # closing the Terms tab immediately is not counted as a review
    popup.value.close()
    page.click("label.stats-checkbox-wrapper .stats-custom-checkbox")
    page.click("#stats-access-button")
    page.wait_for_load_state("networkidle")


def fetch(page: Page, url: str, retries: int = 3) -> str:
    last_html = ""
    for attempt in range(1, retries + 1):
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if page.query_selector("#terms_accepted") is not None:
            accept_terms(page)
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
        html = page.content()
        if not is_blocked(html):
            return html
        last_html = html
        if attempt < retries:
            time.sleep(5 + random.uniform(0, 3))
    raise RuntimeError(f"Blocked or bad response fetching {url} after {retries} attempts")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unknown"


def parse_team_name(soup: BeautifulSoup) -> str:
    card_header = soup.select_one(".card-header")
    if card_header is None:
        return "unknown-team"
    link = card_header.select_one("a[target='ATHLETICS_URL']")
    if link is not None:
        text = link.get_text(strip=True)
    else:
        # Some teams have no linked athletics site -- the header is plain
        # text like "MUW Owls (1-13-4)"; strip the trailing W-L-T record.
        text = card_header.get_text(" ", strip=True)
        text = re.sub(r"\s*\([^()]*\)\s*$", "", text).strip()
    return text or "unknown-team"


def find_schedule_table(soup: BeautifulSoup):
    """Locate the schedule/results table by scoring header rows against
    expected column keywords, rather than relying on a specific id/class
    (which we haven't been able to inspect directly yet)."""
    keywords = {"date", "opponent", "result", "score"}
    best, best_score = None, 0
    for table in soup.find_all("table"):
        header_cells = table.find_all(["th", "td"], limit=20)
        header_text = " ".join(c.get_text(strip=True).lower() for c in header_cells[:10])
        score = sum(1 for kw in keywords if kw in header_text)
        if score > best_score:
            best, best_score = table, score
    return best if best_score >= 2 else None


def parse_result_cell(text: str) -> dict:
    """Extract W/L/T, scores, and OT flag from a result cell like
    'W 3-0', 'L 1-2 (OT)', 'T 1-1'. Falls back to blanks if unparseable
    (e.g. game not yet played) so the raw text is never lost."""
    m = re.search(r"\b([WLT])\b\D*(\d+)\D+(\d+)", text)
    if not m:
        return {"outcome": "", "team_score": "", "opp_score": "", "overtime": ""}
    outcome, s1, s2 = m.groups()
    return {
        "outcome": outcome,
        "team_score": s1,
        "opp_score": s2,
        "overtime": "OT" in text.upper(),
    }


def parse_opponent_cell(cell) -> dict:
    """stats.ncaa.org encodes home/away/neutral structurally, not just by
    text prefix. A <br> in the cell can mean two different things, so it's
    not enough to key off its mere presence:
      - home:                <a>Opponent</a>
      - away:                "@" text node, then <a>Opponent</a>
      - neutral (tournament): <a>Opponent</a><br>@Location, ST
      - home (tournament):    <a>Opponent</a><br>Round Name  (no "@" -> still home/away
                               per the normal prefix rule; the <br> line is just a label)
    """
    link = cell.find("a")
    opponent = link.get_text(strip=True) if link else cell.get_text(" ", strip=True)
    opponent = re.sub(r"^\s*#?\d+\s+", "", opponent).strip()  # strip leading rank

    prefix = ""
    if link is not None:
        prev = link.previous_sibling
        while prev is not None and not str(prev).strip():
            prev = prev.previous_sibling
        prefix = str(prev).strip() if prev is not None else ""
    home_away = "away" if prefix.startswith("@") else "home"

    br = cell.find("br")
    if br is not None:
        after = "".join(
            s if isinstance(s, str) else s.get_text() for s in br.next_siblings
        ).strip()
        if after.startswith("@"):
            home_away = "neutral"

    return {"opponent": opponent, "home_away": home_away}


def parse_schedule_table(table) -> list[dict]:
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    headers_lower = [h.lower() for h in headers]

    out = []
    for tr in rows[1:]:
        cell_tags = tr.find_all(["td", "th"])
        cells = [c.get_text(" ", strip=True) for c in cell_tags]
        if not cells or len(cells) != len(headers):
            continue
        raw = dict(zip(headers, cells))

        record = dict(raw)  # keep every raw column as-is for validation
        if "date" in headers_lower:
            record["date_parsed"] = raw[headers[headers_lower.index("date")]]
        if "opponent" in headers_lower:
            record.update(parse_opponent_cell(cell_tags[headers_lower.index("opponent")]))
        if "result" in headers_lower:
            record.update(parse_result_cell(raw[headers[headers_lower.index("result")]]))
        out.append(record)
    return out


def parse_team_page(html: str) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html, "lxml")
    team_name = parse_team_name(soup)
    table = find_schedule_table(soup)
    if table is None:
        return team_name, []
    return team_name, parse_schedule_table(table)


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


def get_team_list(page: Page, nitty_gritty_url: str) -> list[tuple[str, str]]:
    html = fetch(page, nitty_gritty_url)
    soup = BeautifulSoup(html, "lxml")
    seen, teams = set(), []
    for a in soup.find_all("a", href=re.compile(r"^/teams/\d+$")):
        team_id = re.search(r"/teams/(\d+)", a["href"]).group(1)
        name = a.get_text(strip=True)
        if team_id not in seen and name:
            seen.add(team_id)
            teams.append((team_id, name))
    return teams


def team_list_from_year_links(season: str) -> list[tuple[str, str]]:
    """Team ids for `season`, read from the year dropdown (#year_list) of the
    raw team pages saved for YEAR_LINK_SOURCE_SEASON. Only covers teams that
    existed in the source season."""
    label = f"20{season[:2]}-{season[3:]}"
    raw_dir = season_paths(YEAR_LINK_SOURCE_SEASON)["raw_html"]
    teams = []
    for f in sorted(Path(raw_dir).glob("*.html")):
        soup = BeautifulSoup(f.read_text(), "lxml")
        select = soup.find("select", id="year_list")
        if select is None:
            continue
        for o in select.find_all("option"):
            if o.get_text(strip=True) == label:
                teams.append((o["value"].strip(), parse_team_name(soup)))
    return teams


def scrape_one_team(
    page: Page,
    team_id: str,
    out_dir: Path,
    raw_html_dir: Path | None,
) -> None:
    url = f"https://stats.ncaa.org/teams/{team_id}"
    html = fetch(page, url)
    if raw_html_dir is not None:
        raw_html_dir.mkdir(parents=True, exist_ok=True)
        (raw_html_dir / f"{team_id}.html").write_text(html)

    team_name, rows = parse_team_page(html)
    out_path = out_dir / f"{team_id}_{slugify(team_name)}.csv"
    save_csv(rows, out_path)
    print(f"[{team_id}] {team_name}: {len(rows)} games -> {out_path.relative_to(REPO_ROOT)}")


def launch_browser(p, headless: bool):
    browser = p.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return browser, context, context.new_page()


def run_with_resilience(p, headless, items, process_item, label_fn=str, delay=4.0):
    """Call process_item(page, item) for each item. On failure, relaunch a
    fresh browser (clears a dead browser *and* can shake loose an Akamai
    rate-limit flag on the old session) and retry once before giving up.
    After 3 failures in a row, cool down for 2 minutes before continuing.
    Returns the list of items that failed both attempts.
    """
    browser, context, page = launch_browser(p, headless)
    failures = []
    consecutive_failures = 0
    for i, item in enumerate(items, 1):
        label = label_fn(item)
        for attempt in (1, 2):
            try:
                process_item(page, item)
                consecutive_failures = 0
                break
            except Exception as e:
                if attempt == 2:
                    print(f"{label}: FAILED - {e}")
                    failures.append(item)
                    consecutive_failures += 1
                    break
                cooldown = 8 if "closed" in str(e).lower() else 25
                print(f"{label}: {e} - relaunching (cooldown {cooldown}s) and retrying")
                for obj in (context, browser):
                    try:
                        obj.close()
                    except Exception:
                        pass
                time.sleep(cooldown)
                browser, context, page = launch_browser(p, headless)
        if consecutive_failures >= 3:
            print(f"{consecutive_failures} failures in a row -- cooling down 120s before continuing")
            time.sleep(120)
            consecutive_failures = 0
        if i < len(items):
            time.sleep(delay + random.uniform(0, 1.5))
    browser.close()
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team-id", default=WASHU_TEAM_ID, help="Single NCAA team id to scrape (default: WashU)")
    parser.add_argument("--limit", type=int, default=None, help="With --all, only scrape the first N pending teams (for testing)")
    parser.add_argument("--all", action="store_true", help="Scrape every team listed on the nitty gritties report")
    parser.add_argument("--season", default=DEFAULT_SEASON, help="Season like 25-26 or 24-25 (sets default URL and output dirs)")
    parser.add_argument("--nitty-gritty-url", default=None, help="Override the season's seed report URL")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--dump-html", action="store_true", default=True,
                         help="Save raw HTML to research/data/wsoc/<season>/raw_html/ for inspection (default on while we validate parsing)")
    parser.add_argument("--no-dump-html", dest="dump_html", action="store_false")
    parser.add_argument("--delay", type=float, default=4.0, help="Base seconds to sleep between requests when --all")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--headful", dest="headless", action="store_false",
                         help="Show the browser window (useful for debugging)")
    args = parser.parse_args()

    paths = season_paths(args.season)
    args.nitty_gritty_url = args.nitty_gritty_url or paths["url"]
    args.out_dir = args.out_dir or paths["schedule"]
    raw_html_dir = paths["raw_html"] if args.dump_html else None

    with sync_playwright() as p:
        if args.all:
            teams = []
            if args.nitty_gritty_url:
                browser, _, page = launch_browser(p, args.headless)
                teams = get_team_list(page, args.nitty_gritty_url)
                browser.close()
                print(f"Found {len(teams)} teams on nitty gritties report")
            if args.season != YEAR_LINK_SOURCE_SEASON:
                have = {tid for tid, _ in teams}
                derived = [t for t in team_list_from_year_links(args.season) if t[0] not in have]
                print(f"Found {len(derived)} additional teams via {YEAR_LINK_SOURCE_SEASON} year links")
                teams += derived

            pending = [(tid, name) for tid, name in teams if not any(args.out_dir.glob(f"{tid}_*.csv"))]
            if len(pending) < len(teams):
                print(f"{len(teams) - len(pending)} teams already scraped, skipping")

            if args.limit:
                pending = pending[:args.limit]

            def process(page, item):
                scrape_one_team(page, item[0], args.out_dir, raw_html_dir)

            failures = run_with_resilience(
                p, args.headless, pending, process,
                label_fn=lambda it: f"[{it[0]}] {it[1]}", delay=args.delay,
            )
            if failures:
                print(f"\n{len(failures)} teams failed: {failures}")
        else:
            browser, _, page = launch_browser(p, args.headless)
            scrape_one_team(page, args.team_id, args.out_dir, raw_html_dir)
            browser.close()


if __name__ == "__main__":
    main()
