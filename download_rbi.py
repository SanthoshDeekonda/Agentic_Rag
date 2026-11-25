"""Download the official RBI regulatory corpus as UTF-8 text."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from threading import Lock, local
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RBI = "https://www.rbi.org.in/Scripts/"
INDIA_CODE = "https://indiacode.gov.in/server/api/"
OUTPUT = Path(__file__).resolve().parent / "data"
LEGAL = {
    "acts": "Act.aspx",
    "rules": "Rules.aspx",
    "regulations": "Regulations.aspx",
    "schemes": "Schemes.aspx",
}
ACT_FALLBACKS = {
    "banking regulation act 1949": RBI + "PublicationsView.aspx?id=16143",
    "reserve bank of india act 1934": RBI + "PublicationsView.aspx?id=6449",
    "national housing bank act 1987": "https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/NHB-Act.pdf",
    "insolvency and bankruptcy code 2016": INDIA_CODE
    + "core/bitstreams/bf689ae0-08e3-47e2-92f2-1711a774254e/content",
    "prevention of money laundering act 2002": INDIA_CODE
    + "core/bitstreams/e5a7b350-4e52-4a8f-bb47-fe0f186223e5/content",
    "bankers books evidence act 1891": "https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/"
    "The-Bankers-Book-Evidence-Act-1891.pdf",
    "small industries development bank of india act 1989": "https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/SIDBI-act_0_0.pdf",
    "micro small and medium enterprises development act 2006": INDIA_CODE
    + "core/bitstreams/0a6e666f-ea51-4b64-b92c-74fae64c80b7/content",
    "banning of unregulated deposit schemes act 2019": INDIA_CODE
    + "core/bitstreams/f7f485f3-d265-470b-8166-03c8fddbd5e9/content",
    "black money undisclosed foreign income and assets and imposition of tax act 2015": INDIA_CODE
    + "core/bitstreams/8422911b-579d-4898-baf6-9b607cfb7fa3/content",
    "recovery of debts and bankruptcy act 1993": INDIA_CODE
    + "core/bitstreams/fa7a05f7-acd6-444b-8356-e9103fa46b36/content",
    "negotiable instruments act 1881": INDIA_CODE
    + "core/bitstreams/82bf1927-5e52-4aab-a876-50552c5952cd/content",
}
RULE_FALLBACKS = {
    "registration of assignment of receivables rules 2012": INDIA_CODE
    + "core/bitstreams/b0253596-8008-4796-ae36-bf5f26e90607/content",
    "national board for micro small and medium enterprises rules 2006": INDIA_CODE
    + "core/bitstreams/ab7b87b0-b092-4215-b690-52e6c1a6edf5/content",
}
LEGAL_RULE_COPIES = {
    "banking regulation co operative societies rules 1966": "https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/"
    "Banking-Regulations--Co-Operative-Societies--Rules--1966.pdf",
    "co operative banks nomination rules 1985": "https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/"
    "Co-Operative-Banks--Nomination--Rules--1985..pdf",
    "co operative banks period of preservation of records rules 1985": "https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/"
    "Co--Operative-Banks--Period-of-Preservation-of-Records--Rules--1985..pdf",
    "procedure for selection of members of monetary policy committee and terms and conditions "
    "of their appointment rules 2016": "https://dea.gov.in/files/rules_documents/MPC_Rule.pdf",
}
LEGAL_PACKETS = {
    "dicgc_act.pdf": "Deposit Insurance and Credit Guarantee Corporation Act and General Regulations, 1961",
    "cic_rules_and_regulations_2006_21032024.pdf": "Credit Information Companies Rules and Regulations, 2006",
}
ARCHIVES = {
    "notifications": "NotificationUser.aspx",
    "circulars": "BS_CircularIndexDisplay.aspx",
    "master_circulars": "BS_ViewMasterCirculardetails.aspx",
    "press_releases": "BS_PressReleaseDisplay.aspx",
}
DOCUMENT_PATHS = {
    "notificationuser.aspx": "rbi",
    "bs_circularindexdisplay.aspx": "rbi",
    "bs_viewmascirculardetails.aspx": "rbi",
    "bs_viewmasdirections.aspx": "rbi",
    "bs_pressreleasedisplay.aspx": "press",
    "bs_pressrelease-display.aspx": "press",
    "faqdisplay.aspx": "faq",
    "bs_viewcontent.aspx": "content",
}
DATE = re.compile(
    r"\b(?:[A-Z][a-z]{2,8} \d{1,2},? \d{4}|\d{1,2} [A-Z][a-z]{2,8},? \d{4}|"
    r"\d{1,2}\.\d{1,2}\.\d{4})\b"
)
REFERENCE = re.compile(
    r"\bRBI\s*/\s*(?:[A-Z]+/)?\s*\d{4}\s*[-–]\s*\d{2,4}\s*/\s*[\w….-]+"
    r"|\b(?:DOR|DOS|DBR|DBOD|DPSS|FIDD|FMOD|FMRD|FED|DNBR|DCM|DGBA|CO|IDMD)"
    r"[.][A-Za-z0-9. /()-]{0,60}?/\d{4}[-–]\d{2}\b",
)
PRESS_INCLUDE = re.compile(
    r"monetary policy|developmental and regulatory policies|\b(?:directions?|regulations?|"
    r"guidelines?|framework|clarifications?|advisory|advisories|cautions?|warns?|ombudsman|"
    r"consumer awareness|public awareness|public notice|legal tender|customer protection|"
    r"consumer protection|public consultation|frequently asked questions|"
    r"systemically important|digital lending|digital payments|domestic money transfer|"
    r"deposit insurance|banking services|exchange of notes|withdrawal from circulation|"
    r"unclaimed deposits|know your customer|payment systems?)\b",
    re.I,
)
PRESS_EXCLUDE = re.compile(
    r"\bdraft\b|\bauction\b|money market operations|imposes? (?:a )?monetary penalty|"
    r"cancels? (?:the )?(?:licen[cs]e|certificate)|(?<!legal )\btenders?\b|redemption price",
    re.I,
)


def plain(node):
    return " ".join(node.get_text(" ", strip=True).split())


def parse_date(text):
    for match in DATE.finditer(text):
        for fmt in ("%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(match[0].replace(",", ""), fmt).date()
            except ValueError:
                continue
    return None


def official_url(base, href):
    parts = urlsplit(urljoin(base, href))
    host = parts.hostname or ""
    if parts.scheme not in {"http", "https"} or not (
        host == "rbi.org.in"
        or host.endswith(".rbi.org.in")
        or host
        in {
            "indiacode.nic.in",
            "www.indiacode.nic.in",
            "indiacode.gov.in",
            "www.indiacode.gov.in",
            "financialservices.gov.in",
            "www.financialservices.gov.in",
            "dea.gov.in",
            "www.dea.gov.in",
        }
    ):
        return None
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def is_pdf(url):
    return urlsplit(url).path.lower().endswith(".pdf")


def identity(url):
    parts = urlsplit(url)
    endpoint = parts.path.lower().rsplit("/", 1)[-1]
    params = dict(parse_qsl(parts.query.lower()))
    namespace = DOCUMENT_PATHS.get(endpoint)
    number = params.get("prid") if namespace == "press" else params.get("id")
    if namespace and number and number.isdigit():
        return f"{namespace}-{number}"
    if is_pdf(url) and parts.hostname == "rbidocs.rbi.org.in":
        url = url.lower()
    return "source-" + hashlib.sha256(url.encode()).hexdigest()[:20]


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Client:
    def __init__(self):
        self.thread = local()
        self.lock = Lock()
        self.next_request = {}

    def session(self):
        if not hasattr(self.thread, "session"):
            session = requests.Session()
            retry = Retry(
                total=2,
                backoff_factor=0.7,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods={"GET", "POST"},
                raise_on_status=False,
            )
            session.mount("https://", HTTPAdapter(max_retries=retry))
            session.mount("https://www.indiacode.nic.in/", HTTPAdapter(max_retries=0))
            session.mount("https://indiacode.nic.in/", HTTPAdapter(max_retries=0))
            self.thread.session = session
        return self.thread.session

    def fetch(self, url, *, data=None, headers=None):
        for _ in range(6):
            host = urlsplit(url).hostname
            with self.lock:
                now = time.monotonic()
                slot = max(now, self.next_request.get(host, now))
                self.next_request[host] = slot + 0.2
            time.sleep(max(0, slot - time.monotonic()))
            legacy = host in {"indiacode.nic.in", "www.indiacode.nic.in"}
            response = self.session().request(
                "POST" if data is not None else "GET",
                url,
                data=data,
                headers=headers,
                timeout=(5, 10) if legacy else (10, 35),
                allow_redirects=False,
            )
            if response.is_redirect:
                target = official_url(url, response.headers["Location"])
                if target is None:
                    raise ValueError("Redirect to a source outside the official hosts")
                data = data if response.status_code in {307, 308} else None
                url = target
                continue
            response.raise_for_status()
            return response
        raise ValueError("Too many redirects")

    def html(self, url, **kwargs):
        return BeautifulSoup(self.fetch(url, **kwargs).content, "lxml")

    @lru_cache(maxsize=128)
    def pdf(self, url, ocr):
        return pdf_text(self.fetch(url).content, ocr)


@dataclass
class Document:
    key: str
    title: str
    kind: str
    published: str = ""
    reference: str = ""
    urls: list[str] = field(default_factory=list)
    listings: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    withdrawn: bool = False


class Catalog:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.documents = {}
        self.aliases = {}
        self.report = []
        self.withdrawn_keys = set()
        self.withdrawn_titles = set()
        self.excluded = {}
        self.lock = Lock()

    def note(self, source, status, **details):
        with self.lock:
            self.report.append(dict(source=source, status=status, **details))

    def add(
        self,
        kind,
        title,
        url,
        listing,
        published=None,
        pdf=None,
        reference="",
        standing=False,
    ):
        if not standing and (
            published is None or not self.start <= published <= self.end
        ):
            return False
        if kind == "press_releases" and (
            not PRESS_INCLUDE.search(title) or PRESS_EXCLUDE.search(title)
        ):
            with self.lock:
                self.excluded[identity(url)] = title
            return False
        legal_packet = LEGAL_PACKETS.get(urlsplit(url).path.rsplit("/", 1)[-1].lower())
        if kind in LEGAL and legal_packet:
            title = legal_packet
        with self.lock:
            key = identity(url)
            # A shared PDF in the legal index may explicitly represent two separate entries.
            merge_pdf = pdf and kind not in LEGAL
            if merge_pdf:
                key = self.aliases.get(identity(pdf), key)
                self.aliases[identity(pdf)] = key
            key = self.aliases.get(key, key)
            if kind in LEGAL and is_pdf(url) and key in self.documents:
                previous = self.documents[key]
                if normalized_title(previous.title) != normalized_title(title):
                    key += "-" + text_hash(title)[:10]
            doc = self.documents.setdefault(key, Document(key, title, kind))
            if kind not in doc.categories:
                doc.categories.append(kind)
            if published:
                doc.published = doc.published or published.isoformat()
            doc.reference = doc.reference or reference
            doc.listings = sorted(set(doc.listings) | {listing})
            doc.urls = sorted(
                set(doc.urls) | ({url, pdf} if pdf else {url}), key=url_preference
            )
        return True


def url_preference(url):
    path = urlsplit(url).path.lower()
    if is_pdf(url):
        return 4, url
    if path.endswith(("bs_viewmasdirections.aspx", "bs_viewmascirculardetails.aspx")):
        return 0, url
    if path.endswith("bs_circularindexdisplay.aspx"):
        return 3, url
    return 1, url


def link_url(a, base):
    href = a.get("href", "")
    if href and not href.startswith(("#", "javascript:", "mailto:")):
        return official_url(base, href)
    return None


def row_list(soup):
    table = soup.select_one("table.tablebg")
    if table is None:
        raise ValueError("RBI listing table missing")
    return [row for row in table.find_all("tr") if row.find_parent("table") is table]


def read_rows(soup, kind, url, catalog, standing=False):
    matched = accepted = 0
    heading_date = None
    for row in row_list(soup):
        cells = row.find_all("td", recursive=False)
        if not cells:
            continue
        if len(cells) == 1 and "tableheader" in cells[0].get("class", []):
            heading_date = parse_date(plain(cells[0])) or heading_date
            continue
        anchors = [(a, link_url(a, url)) for a in cells[0].select("a[href]")]
        links = [
            (a, link)
            for a, link in anchors
            if link and plain(a) and not DATE.fullmatch(plain(a))
        ]
        if not links:
            continue
        anchor, target = links[-1] if kind == "faqs" else links[0]
        title = plain(anchor)
        published = heading_date
        reference = ""
        if kind == "circulars" and len(cells) >= 4:
            published = parse_date(plain(cells[1]))
            reference, title = title, plain(cells[3])
        if kind == "faqs":
            published = parse_date(plain(cells[0]))
            title = DATE.sub("", title, count=1).strip() if DATE.match(title) else title
        pdf = next(
            (
                link
                for a in row.select("a[href]")
                if (link := link_url(a, url)) and is_pdf(link) and link != target
            ),
            None,
        )
        matched += 1
        if not standing and published is None:
            catalog.note(url, "undated", document=title, document_url=target)
            continue
        accepted += catalog.add(
            kind, title, target, url, published, pdf, reference, standing
        )
    return matched, accepted


def archive_page(client, url, year, month=None):
    page = client.html(url)
    form = page.find("form")
    submit = page.select_one("input[id=btn][name]")
    if form is None or submit is None:
        raise ValueError("RBI archive form unavailable")
    fields = {
        node["name"]: node.get("value", "")
        for node in form.select("input[type=hidden][name]")
    }
    if "hdnYear" not in fields:
        raise ValueError("RBI archive year field unavailable")
    fields.update(hdnYear=str(year))
    if month is not None:
        fields["hdnMonth"] = str(month)
    fields[submit["name"]] = submit.get("value", "")
    result = client.html(url, data=fields, headers={"Referer": url})
    selected = result.select_one("#hdnYear")
    if not selected or selected.get("value") != str(year):
        raise ValueError(f"RBI did not return the requested archive year {year}")
    if month is not None:
        selected_month = result.select_one("#hdnMonth")
        if not selected_month or selected_month.get("value") != str(month):
            raise ValueError(f"RBI did not return the requested archive month {month}")
    return result


def archive_job(client, catalog, kind, path, year, month=None):
    url = RBI + path
    label = f"{year}-{month:02d}" if month else str(year)
    try:
        page = archive_page(client, url, year, month)
        matched, accepted = read_rows(page, kind, url, catalog)
        if not matched:
            text = plain(page.select_one("table.tablebg"))
            if not re.search(
                r"no (?:data|records|results)|not available|^\s*$", text, re.I
            ):
                raise ValueError("No identifiable publication rows in archive response")
        catalog.note(url, "listed", period=label, rows=matched, accepted=accepted)
    except (requests.RequestException, ValueError) as error:
        catalog.note(url, "failed", period=label, error=str(error))


def list_directions(client, catalog):
    url = RBI + "BS_ViewMasterDirections.aspx"
    root = client.html(url)
    categories = {
        link
        for anchor in root.select("a[href]")
        if (link := link_url(anchor, url))
        and re.search(r"bs_viewmasterdirections\.aspx\?did=\d+", link, re.I)
    }
    for target in [url, *sorted(categories)]:
        try:
            matched, accepted = read_rows(
                root if target == url else client.html(target),
                "master_directions",
                target,
                catalog,
                standing=True,
            )
            if matched == 0:
                raise ValueError("No Master Direction rows found")
            catalog.note(target, "listed", rows=matched, accepted=accepted)
        except (requests.RequestException, ValueError) as error:
            catalog.note(target, "failed", error=str(error))


def list_legal(client, catalog, kind, path):
    url = RBI + path
    main = client.html(url).select_one("[role=main], main")
    if main is None:
        raise ValueError("RBI Legal Framework content missing")
    matched = accepted = 0
    for item in main.select("li"):
        if item.find_parent(class_="breadcrumbs") or item.find("li"):
            continue
        title = plain(item)
        if (
            not title
            or title in {"Home", "LEGAL FRAMEWORK"}
            or title.startswith("Legal Framework")
        ):
            continue
        anchor = item.find("a", href=True)
        target = link_url(anchor, url) if anchor else None
        title = re.sub(r"\s*\([\d,.]+\s*kb\)$", "", title, flags=re.I)
        if kind == "rules" and target and "/handle/123456789/2057" in target:
            matched += 1
            catalog.note(
                url,
                "mismatched",
                document=title,
                document_url=target,
                error="India Code links to the Credit Information Companies (Regulation) Act, 2005",
            )
            continue
        if target is None and kind == "rules":
            target = LEGAL_RULE_COPIES.get(normalized_title(title))
        matched += 1
        if target:
            accepted += catalog.add(kind, title, target, url, standing=True)
        else:
            catalog.note(url, "unlinked", document=title)
    if not matched:
        raise ValueError("No legal document entries found")
    catalog.note(url, "listed", rows=matched, accepted=accepted)


def normalized_title(title):
    return re.sub(r"[^\w]+", " ", title.casefold()).strip()


def list_standalone(client, catalog, withdrawn=False):
    path = (
        "NotificationUserWithdrawnCircular.aspx"
        if withdrawn
        else "BS_ViewListofstandalonecirculars.aspx"
    )
    url = RBI + path
    page = client.html(url)
    root = page.select_one(".content_area" if withdrawn else ".grid_12.omega")
    if root is None:
        raise ValueError("RBI circular table missing")
    matched = accepted = 0
    for row in root.select("tr"):
        cells = row.find_all("td", recursive=False)
        if (withdrawn and len(cells) < 3) or (not withdrawn and len(cells) != 4):
            continue
        published = parse_date(plain(cells[0 if withdrawn else 3]))
        if published is None:
            continue
        title = plain(cells[1 if withdrawn else 2])
        anchors = row.select("a[href]")
        links = [target for a in anchors if (target := link_url(a, url))]
        matched += 1
        if withdrawn:
            with catalog.lock:
                catalog.withdrawn_keys.update(map(identity, links))
                if title:
                    catalog.withdrawn_titles.add(
                        (published.isoformat(), normalized_title(title))
                    )
        elif links:
            accepted += catalog.add(
                "standalone_circulars",
                title,
                links[0],
                url,
                published,
                reference=plain(cells[1]),
            )
        elif catalog.start <= published <= catalog.end:
            catalog.note(url, "unlinked", document=title)
    if not withdrawn:
        for a in root.select("a[href]"):
            if (target := link_url(a, url)) and plain(a).startswith("Guidance Note"):
                matched += 1
                accepted += catalog.add(
                    "guidance_notes", plain(a), target, url, standing=True
                )
    if not matched:
        raise ValueError("No circular rows found")
    catalog.note(url, "listed", rows=matched, accepted=accepted)


def list_faqs(client, catalog):
    url = RBI + "FAQDisplay.aspx"
    root = client.html(url)
    categories = {
        link
        for anchor in root.select("a[href]")
        if (link := link_url(anchor, url))
        and re.search(r"faqdisplay\.aspx\?did=\d+", link, re.I)
    }
    for target in [url, *sorted(categories)]:
        try:
            page = root if target == url else client.html(target)
            matched, accepted = read_rows(page, "faqs", target, catalog, standing=True)
            if not matched and "No FAQs Found" not in plain(page):
                raise ValueError("No FAQ rows found")
            catalog.note(target, "listed", rows=matched, accepted=accepted)
        except (requests.RequestException, ValueError) as error:
            catalog.note(target, "failed", error=str(error))


def list_feed(client, catalog, kind, filename):
    url = "https://rbi.org.in/" + filename
    root = ElementTree.fromstring(client.fetch(url).content)
    items = root.findall("./channel/item")
    matched = accepted = 0
    for item in items:
        target = official_url(url, (item.findtext("link") or "").strip())
        published = parse_date(item.findtext("pubDate") or "")
        title = " ".join((item.findtext("title") or "").split())
        if target and title and published:
            matched += 1
            accepted += catalog.add(kind, title, target, url, published)
    if not matched:
        raise ValueError("No dated entries in RBI RSS feed")
    catalog.note(url, "listed", rows=matched, accepted=accepted)


def discover(client, catalog, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {}
        for kind, path in ARCHIVES.items():
            if kind == "master_circulars":
                first_year = catalog.start.year + (catalog.start.month >= 4)
                last_year = catalog.end.year + (catalog.end.month >= 4)
                for year in range(first_year, last_year + 1):
                    jobs[
                        pool.submit(archive_job, client, catalog, kind, path, year)
                    ] = path
                continue
            for year in range(catalog.start.year, catalog.end.year + 1):
                first = catalog.start.month if year == catalog.start.year else 1
                last = catalog.end.month if year == catalog.end.year else 12
                for month in range(first, last + 1):
                    jobs[
                        pool.submit(
                            archive_job, client, catalog, kind, path, year, month
                        )
                    ] = path
        for kind, path in LEGAL.items():
            jobs[pool.submit(list_legal, client, catalog, kind, path)] = RBI + path
        for function, filename, args in (
            (list_directions, "BS_ViewMasterDirections.aspx", ()),
            (list_faqs, "FAQDisplay.aspx", ()),
            (list_standalone, "BS_ViewListofstandalonecirculars.aspx", ()),
            (list_standalone, "NotificationUserWithdrawnCircular.aspx", (True,)),
            (
                list_feed,
                "notifications_rss.xml",
                ("notifications", "notifications_rss.xml"),
            ),
            (
                list_feed,
                "pressreleases_rss.xml",
                ("press_releases", "pressreleases_rss.xml"),
            ),
        ):
            jobs[pool.submit(function, client, catalog, *args)] = filename
        for future in as_completed(jobs):
            try:
                future.result()
            except (
                requests.RequestException,
                ValueError,
                ElementTree.ParseError,
            ) as error:
                catalog.note(jobs[future], "failed", error=str(error))
    priority = [
        *LEGAL,
        "master_directions",
        "master_circulars",
        "notifications",
        "circulars",
        "standalone_circulars",
        "guidance_notes",
        "faqs",
        "press_releases",
    ]
    for doc in catalog.documents.values():
        doc.categories.sort(key=priority.index)
        doc.kind = doc.categories[0]
        doc.withdrawn = (
            doc.key in catalog.withdrawn_keys
            or (doc.published, normalized_title(doc.title)) in catalog.withdrawn_titles
        )


BLOCKS = {
    "article",
    "div",
    "section",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "p",
    "li",
    "tr",
    "br",
    "ul",
    "ol",
    "table",
    "blockquote",
    "pre",
    "hr",
}
ANNEX = re.compile(r"\b(?:annex(?:ure|es)?|appendix|enclosure|attachment)\b", re.I)
UPDATED = re.compile(
    r"(?:last updated|updated as (?:on|of)|updated on)\s*[:–-]?\s*([^\n)]{4,45})", re.I
)


def publication_text(node):
    for tag in node.select(
        "script, style, noscript, nav, form input, .breadcrumbs, .archives, .noprint"
    ):
        if tag.parent:
            tag.decompose()
    for tag in node.find_all(list(BLOCKS | {"td", "th"})):
        if tag.name in {"td", "th"}:
            if tag.find_next_sibling(["td", "th"]):
                tag.insert_after("\t")
        else:
            tag.insert_before("\n")
            tag.insert_after("\n")
    lines = []
    for raw in node.get_text().replace("\xa0", " ").splitlines():
        line = "\t".join(" ".join(cell.split()) for cell in raw.split("\t")).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def count_letters(text):
    return sum(character.isalpha() for character in text)


def command(*args, timeout=90):
    result = subprocess.run(args, capture_output=True, check=True, timeout=timeout)
    return result.stdout.decode("utf-8", errors="replace")


def pdf_text(data, ocr):
    if not data.startswith(b"%PDF-"):
        raise ValueError("Source returned a non-PDF response")
    with tempfile.TemporaryDirectory(prefix="rbi-pdf-") as directory:
        pdf = Path(directory) / "source.pdf"
        pdf.write_bytes(data)
        extracted = command("pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-")
        pages = extracted.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        warnings = []
        used_ocr = []
        for index, page in enumerate(pages, start=1):
            if count_letters(page) >= 12:
                continue
            if index == len(pages) and len(pages) > 1 and not page.strip() and not ocr:
                warnings.append(f"Page {index} has no extractable text")
                continue
            if not ocr or not shutil.which("pdftoppm"):
                warnings.append(f"Page {index} needs OCR")
                continue
            prefix = Path(directory) / f"page-{index}"
            try:
                command(
                    "pdftoppm",
                    "-f",
                    str(index),
                    "-l",
                    str(index),
                    "-r",
                    "240",
                    "-gray",
                    "-png",
                    "-singlefile",
                    str(pdf),
                    str(prefix),
                )
                image = str(prefix.with_suffix(".png"))
                scanned = command(ocr, image, "stdout", "-l", "eng")
                if count_letters(scanned) < 12 and page.strip():
                    scanned = command(ocr, image, "stdout", "-l", "eng", "--psm", "11")
                if count_letters(scanned) >= 12:
                    pages[index - 1] = scanned
                    used_ocr.append(index)
                elif page.strip():
                    warnings.append(f"Page {index} produced insufficient OCR text")
            except (OSError, subprocess.SubprocessError) as error:
                warnings.append(f"Page {index} OCR failed: {error}")
        text = "\n\n".join(page.strip("\n") for page in pages if page.strip())
        if count_letters(text) < 20:
            raise ValueError("PDF contains no usable text after extraction")
        return text, warnings, used_ocr


def rbi_html(response, url):
    soup = BeautifulSoup(response.content, "lxml")
    body = soup.select_one("#NotificationUser") or soup.select_one(
        ".right_blue_border .tablebg, #pnlDetails .tablebg"
    )
    if body is None:
        body = soup.select_one(
            "[role=main] .tablebg, main .tablebg, [role=main] .content_area, main .content_area"
        )
    if body is None:
        raise ValueError("RBI document body missing")
    primary = None
    attachments = {}
    for anchor in body.select("a[href]"):
        link = link_url(anchor, url)
        if not link or not is_pdf(link):
            continue
        label = plain(anchor)
        image = anchor.find("img")
        if primary is None and (
            not label or (image and "pdf" in image.get("alt", "").lower())
        ):
            primary = link
        elif ANNEX.search(label) or (label and "/content/pdfs/" in link.lower()):
            attachments[link] = label
    return publication_text(body), primary, attachments


def india_pdf_links(response):
    soup = BeautifulSoup(response.content, "lxml")
    for anchor in soup.select("a[href]"):
        target = link_url(anchor, response.url)
        if target and (is_pdf(target) or "/bitstream/" in target):
            yield anchor, target


def india_extract(client, response, doc, ocr):
    ranked = []
    wanted = set(normalized_title(doc.title).split())
    for anchor, target in india_pdf_links(response):
        parent = anchor.find_parent("tr")
        label = normalized_title(plain(parent if parent else anchor))
        if "simple-search" in response.url:
            overlap = len(wanted.intersection(label.split()))
            if overlap < max(2, len(wanted) - 2):
                continue
            rank = -overlap
        else:
            rank = 0 if "act file" in label or "view" in label else 1
        ranked.append((rank, target))
    errors = []
    for _, target in sorted(set(ranked))[:3]:
        try:
            pdf = client.fetch(target)
            text, warnings, ocr_pages = pdf_text(pdf.content, ocr)
            return text, str(pdf.url), warnings, ocr_pages
        except (
            requests.RequestException,
            ValueError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            errors.append(str(error))
    raise ValueError(
        "India Code page has no usable matching full-text PDF"
        + (f": {'; '.join(errors)}" if errors else "")
    )


def india_code_document(client, url, doc, ocr):
    def api(path):
        return client.fetch(INDIA_CODE + path).json()

    def embedded(payload, key):
        return payload.get("_embedded", {}).get(key)

    match = re.search(r"/act/([a-f0-9-]{36})(?:/|$)", urlsplit(url).path)
    if match:
        item_id = match[1]
    else:
        query = normalized_title(doc.title).removeprefix("the ")
        search = api(
            "discover/search/objects?" + urlencode({"query": query, "size": 20})
        )
        hits = embedded(embedded(search, "searchResult") or {}, "objects") or []
        candidates = []
        for hit in hits:
            item = embedded(hit, "indexableObject") or {}
            if item.get("type") != "item":
                continue
            name = normalized_title(item["name"]).removeprefix("the ")
            years = re.findall(r"\b\d{4}\b", query)
            if years and not all(year in name.split() for year in years):
                continue
            score = SequenceMatcher(None, query, name).ratio()
            if score >= 0.84:
                candidates.append((score, item["uuid"]))
        candidates.sort(reverse=True)
        if not candidates or (
            len(candidates) > 1 and candidates[0][0] == candidates[1][0]
        ):
            raise ValueError(
                "India Code search returned no unambiguous matching legal document"
            )
        item_id = candidates[0][1]
    files = []
    for bundle in embedded(api(f"core/items/{item_id}/bundles"), "bundles") or []:
        if bundle["name"] != "ORIGINAL":
            continue
        for item in (
            embedded(api(f"core/bundles/{bundle['uuid']}/bitstreams"), "bitstreams")
            or []
        ):
            name = item["name"].lower()
            target = official_url(INDIA_CODE, item["_links"]["content"]["href"])
            if target and name.endswith(".pdf"):
                if re.match(r"h\d|hindi|hi[-_]", name):
                    continue
                files.append((not bool(re.match(r"a\d|english|en[-_]", name)), target))
    for _, target in sorted(files):
        response = client.fetch(target)
        if response.content.startswith(b"%PDF-"):
            text, warnings, pages = pdf_text(response.content, ocr)
            return text, str(response.url), warnings, pages
    raise ValueError("India Code item has no downloadable English PDF")


def extract(client, response, doc, ocr):
    url = str(response.url)
    if response.content.startswith(b"%PDF-"):
        text, warnings, pages = pdf_text(response.content, ocr)
        return text, url, warnings, pages
    if "indiacode." in (urlsplit(url).hostname or ""):
        return india_extract(client, response, doc, ocr)
    body, primary, attachments = rbi_html(response, url)
    warnings = []
    pages = []
    if count_letters(body) < 120 and primary:
        pdf = client.fetch(primary)
        body, warnings, pages = pdf_text(pdf.content, ocr)
        url = str(pdf.url)
    if count_letters(body) < 20:
        raise ValueError("Document body contains no usable text")
    for target, label in attachments.items():
        try:
            annex, problems, annex_pages = client.pdf(target, ocr)
            body += f"\n\n{label}\nSource URL: {target}\n\n{annex}"
            warnings.extend(f"{label}: {problem}" for problem in problems)
            if annex_pages:
                warnings.append(
                    f"{label}: OCR pages {', '.join(map(str, annex_pages))}"
                )
        except (
            requests.RequestException,
            ValueError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            warnings.append(f"Could not extract {label} at {target}: {error}")
    return body, url, warnings, pages


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def document_status(doc):
    if doc.withdrawn:
        return "Listed by RBI as withdrawn"
    if (
        doc.kind == "acts"
        and normalized_title(doc.title) == "bankers books evidence act 1891"
    ):
        return (
            "Replaced by the Bankers’ Books Evidence Act, 2026, effective 2026-10-01. "
            "Source: https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2309122"
        )
    return ""


def metadata_text(doc, body, source, warnings, ocr_pages):
    revision = UPDATED.search(f"{doc.title}\n{body[:5000]}")
    revised = parse_date(revision[1]) if revision else None
    reference = doc.reference or "\n".join(
        dict.fromkeys(REFERENCE.findall(body[:1500]))
    )
    published = doc.published
    if not published:
        official_date = re.search(r"\bDate\s*:\s*([^\n]+)", body[:900], re.I)
        scanned_date = (
            official_date[1]
            if official_date
            else (body[:900] if doc.kind not in LEGAL else "")
        )
        detected = parse_date(scanned_date)
        published = detected.isoformat() if detected else ""
    source_host = urlsplit(source).hostname or ""
    publisher = "Reserve Bank of India"
    if "indiacode." in source_host:
        publisher = "India Code, Government of India"
    if source_host.removeprefix("www.") in {"financialservices.gov.in", "dea.gov.in"}:
        publisher = "Ministry of Finance, Government of India"
    fields = [
        ("Title", doc.title),
        ("Document type", doc.kind.replace("_", " ")),
        ("Publisher / official source", publisher),
        ("Published", published),
        ("Updated", revised.isoformat() if revised else ""),
        ("Reference", reference.replace("\n", " | ")),
        ("Official URL", doc.urls[0]),
        ("Text source URL", source),
        ("Status", document_status(doc)),
        ("OCR pages", ", ".join(map(str, ocr_pages))),
        ("Extraction notes", " | ".join(warnings)),
    ]
    header = "\n".join(f"{label}: {value}" for label, value in fields if value)
    return f"{header}\n\n{body.strip()}\n"


def download(client, output, doc, old, ocr):
    path = output / (doc.key + ".txt")
    status = document_status(doc)
    record = asdict(doc) | {"file": path.name, "source_status": status}
    errors = []
    unchanged_metadata = (
        old
        and old.get("source_status", "") == status
        and all(old.get(key) == value for key, value in asdict(doc).items())
    )
    title = normalized_title(doc.title).removeprefix("the ")
    fallbacks = {"acts": ACT_FALLBACKS, "rules": RULE_FALLBACKS}
    fallback = fallbacks.get(doc.kind, {}).get(title)
    targets = [*doc.urls, fallback] if fallback else doc.urls
    for url in targets:
        try:
            headers = {}
            if (
                unchanged_metadata
                and old.get("fetched_url") == url
                and path.is_file()
                and old.get("status") in {"saved", "unchanged"}
                and "/indiacode" not in url
                and not old.get("attachments")
            ):
                for key, header in (
                    ("etag", "If-None-Match"),
                    ("last_modified", "If-Modified-Since"),
                ):
                    if old.get(key):
                        headers[header] = old[key]
            if (
                "indiacode." in urlsplit(url).netloc
                and not is_pdf(url)
                and "/bitstreams/" not in url
            ):
                try:
                    body, source, warnings, ocr_pages = india_code_document(
                        client, url, doc, ocr
                    )
                    response = None
                except (
                    requests.RequestException,
                    ValueError,
                    OSError,
                    subprocess.SubprocessError,
                ) as error:
                    errors.append(f"{url} (current India Code): {error}")
                    response = client.fetch(url, headers=headers)
            else:
                response = client.fetch(url, headers=headers)
            if response is not None and response.status_code == 304:
                return old | {"status": "unchanged"}
            if response is not None:
                body, source, warnings, ocr_pages = extract(client, response, doc, ocr)
            content = metadata_text(doc, body, source, warnings, ocr_pages)
            checksum = text_hash(content)
            partial = any(": OCR pages " not in note for note in warnings)
            if (
                partial
                and path.is_file()
                and old
                and old.get("status") in {"saved", "unchanged"}
            ):
                return old | {"status": "retained", "errors": warnings}
            atomic_write(path, content)
            return record | {
                "status": (
                    "partial"
                    if partial
                    else (
                        "unchanged"
                        if old and old.get("sha256") == checksum
                        else "saved"
                    )
                ),
                "source_url": source,
                "fetched_url": url,
                "sha256": checksum,
                "bytes": len(content.encode()),
                "ocr_pages": ocr_pages,
                "warnings": warnings,
                "attachments": "\nSource URL: https://" in body,
                "etag": response.headers.get("ETag") if response is not None else None,
                "last_modified": (
                    response.headers.get("Last-Modified")
                    if response is not None
                    else None
                ),
            }
        except (
            requests.RequestException,
            ValueError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            errors.append(f"{url}: {error}")
    if path.is_file() and old:
        return old | {"status": "retained", "errors": errors}
    return record | {"status": "failed", "file": None, "errors": errors}


def save_manifest(path, records):
    atomic_write(
        path,
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
            for _, value in sorted(records.items())
        ),
    )


def main():
    india_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat, default=india_today)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--retry-incomplete",
        action="store_true",
        help="reuse verified files and retry failed or partial extractions",
    )
    args = parser.parse_args()
    if args.since is None:
        try:
            args.since = args.until.replace(year=args.until.year - 3)
        except ValueError:
            args.since = args.until.replace(year=args.until.year - 3, day=28)
    if args.since > args.until or not 1 <= args.workers <= 24:
        parser.error("choose an ordered date range and 1 to 24 workers")
    if not shutil.which("pdftotext"):
        parser.error("pdftotext is required (Debian package: poppler-utils)")
    ocr = shutil.which("tesseract")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    directory = os.open(OUTPUT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("another downloader is already writing to data/")
        return run(args, ocr)
    finally:
        os.close(directory)


def run(args, ocr):
    catalog = Catalog(args.since, args.until)
    client = Client()
    print(
        f"Discovering RBI publications for {args.since} through {args.until}",
        flush=True,
    )
    discover(client, catalog, args.workers)
    print(f"Discovered {len(catalog.documents)} unique documents", flush=True)
    path = OUTPUT / "manifest.jsonl"
    previous = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            previous[record["key"]] = record
    records = previous.copy()
    pending = []
    for key, doc in sorted(catalog.documents.items()):
        old = previous.get(key)
        if (
            args.retry_incomplete
            and old
            and old["status"] in {"saved", "unchanged"}
            and old["file"]
            and (OUTPUT / old["file"]).is_file()
        ):
            records[key] = old | {
                "status": "unchanged",
                "categories": doc.categories,
                "listings": doc.listings,
                "urls": doc.urls,
            }
        else:
            pending.append((doc, old))
    print(f"Fetching {len(pending)} documents", flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            tasks = [
                pool.submit(download, client, OUTPUT, doc, old, ocr)
                for doc, old in pending
            ]
            for index, future in enumerate(as_completed(tasks), start=1):
                record = future.result()
                records[record["key"]] = record
                if index % 100 == 0:
                    save_manifest(path, records)
                    print(f"Processed {index}/{len(tasks)} documents", flush=True)
    finally:
        save_manifest(path, records)
    current = [records[key] for key in catalog.documents]
    statuses = Counter(record["status"] for record in current)
    categories = Counter(record["kind"] for record in current if record["file"])
    report = {
        "since": args.since.isoformat(),
        "until": args.until.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "documents": len(current),
        "by_status": statuses,
        "files_by_category": categories,
        "ocr_documents": sum(
            bool(record.get("ocr_pages"))
            or any("OCR pages" in warning for warning in record.get("warnings", []))
            for record in current
        ),
        "press_releases_excluded": len(catalog.excluded),
        "excluded_press_releases": [
            catalog.excluded[key] for key in sorted(catalog.excluded)
        ],
        "listing_checks": sorted(
            catalog.report,
            key=lambda row: (
                row["source"],
                row.get("period", ""),
                row.get("document", ""),
            ),
        ),
    }
    atomic_write(
        OUTPUT / "download_report.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    print(f"{dict(statuses)}. Report: {OUTPUT / 'download_report.json'}", flush=True)
    return int(
        any(statuses[status] for status in ("failed", "partial", "retained"))
        or any(row["status"] != "listed" for row in catalog.report)
    )


if __name__ == "__main__":
    raise SystemExit(main())
