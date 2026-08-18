r"""Cherokee 411 news aggregator. Stdlib only, no model, no external dependency.

BUILT AGAINST AN EXISTING SPEC, NOT A FRESH DESIGN:
  reports\client\cherokee411\ALERT-PIPELINE-OPS-DESIGN.md  ("DESIGN, NOT BUILT")
  reports\client\cherokee411\CHEROKEE-411-FINDINGS.md      (the feed audit)

THE ONE RULE THE WHOLE THING TURNS ON
    Liveness is the age of the NEWEST ITEM. Nothing else.
    KOSU is the specimen and it settles the argument: its declared feed returns
    HTTP 200, parses as valid RSS, carries a lastBuildDate of TODAY, and contains
    ZERO ARTICLES. Three of those four signals call it healthy. They are all
    measurements of the FEED DOCUMENT. Only newest-item age measures the thing
    anyone actually cares about, which is whether a newsroom is still filing.
    Indianz has published nothing to its feed since September 2020 and The
    Frontier since December 2023, while both sites publish today.

ALARM DISCIPLINE
    A state file is written EVERY run, so the picture is always inspectable
    without waiting for an alarm. Notification fires only on a STATE CHANGE, in
    BOTH directions. A source dead for six days must not page on every poll:
    that is how an alarm gets muted, and a muted alarm is worse than none because
    it still reads as coverage.

DEDUP
    Counted BEFORE and AFTER, with the delta recorded as a field. A dedup check
    cannot see what it consumes; if duplicates collapse before the counter runs,
    the count is of survivors and the collapse is invisible.

    python tools/c411_news/aggregate.py            # one poll
    python tools/c411_news/aggregate.py --dry-run  # no state write, no notify
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

VERSION = "0.1.0"

HERE = os.path.dirname(os.path.abspath(__file__))
# Output directory. C411_OUT lets this run in CI on Linux; the default keeps the
# existing behaviour on this workstation exactly as it was.
OUT_DIR = os.environ.get("C411_OUT") or os.path.join(
    "C:\\", "IntellzOps", "reports", "client", "cherokee411", "news")
STATE_PATH = os.path.join(OUT_DIR, "feed-state.json")
UA = "Cherokee411NewsMonitor/%s (+https://cherokee411.com)" % VERSION
TIMEOUT = 25

# ⚠ THRESHOLDS ARE FIRST PASS AND THE OUTPUT SAYS SO ON EVERY RUN.
# Each is roughly 3x that source's own measured publishing interval, taken from a
# SINGLE observation window on 3 August 2026. They need one revision after a
# fortnight of real data. A provisional number that is never revisited becomes a
# permanent claim, so the report repeats the caveat rather than hiding it here.
#
# tier CONNECTED = machine readable feed we poll.
# tier MANUAL    = publishes actively but its feed cannot be trusted. Named human
#                  check, surfaced with a last checked date so seven connected
#                  sources never read as coverage of ten.
# ⛔⛔ THE THREE "DEAD" SOURCES WERE NEVER DEAD. THE AUDIT TESTED THE WRONG URL,
#     AND SO DID THE FIRST VERSION OF THIS FILE.
#     Verified 17 August 2026 by reading each feed's newest pubDate directly:
#       Indianz      /rss/news.xml   frozen Sept 2020  ->  /News/feed/       LIVE
#       The Frontier /feed/          frozen Dec 2023   ->  /stories/feed/    LIVE
#       KOSU         /index.rss      849 bytes, empty  ->  /news.rss         LIVE
#     Each publisher left a legacy path serving valid RSS at HTTP 200 while the
#     newsroom moved. The Frontier's case is the clearest: its WordPress `post`
#     type stopped at 216 posts in Dec 2023 and current work lives in a `stories`
#     custom type with 2,784 posts.
#     ⭐ AND THE LESSON IS SHARPER THAN "CHECK THE URL". This aggregator agreed
#     with the prior audit on all three, and that agreement was read as
#     confirmation. It was not. Both were reading the same wrong address, so the
#     two instruments shared a blind spot and could only ever agree.
#
# ⛔ NEVER USE FEED AUTODISCOVERY ON THE CNHI/BLOX PAPERS. Cherokee Phoenix,
#    Tahlequah Daily Press, Muskogee Phoenix and Claremore Progress all declare a
#    <link rel="alternate"> feed filtered to keyword #topstory which currently
#    matches NOTHING: HTTP 200, valid RSS 2.0, about 849 bytes, zero items. An
#    aggregator that autodiscovers silently gets nothing from four sources,
#    including the client's closest peer. The c=news URLs below are hardcoded on
#    purpose. Dropping c=news roughly triples volume with AP wire and syndicated
#    filler, so it is also the editorially correct filter.
SOURCES = [
    ("Cherokee Phoenix", "https://www.cherokeephoenix.org/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc", 3, "CONNECTED"),
    ("Tahlequah Daily Press", "https://www.tahlequahdailypress.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc", 2, "CONNECTED"),
    ("Muskogee Phoenix", "https://www.muskogeephoenix.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc", 3, "CONNECTED"),
    ("Claremore Progress", "https://www.claremoreprogress.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc", 4, "CONNECTED"),
    ("ICT", "https://ictnews.org/feed", 3, "CONNECTED"),
    ("Native News Online", "https://nativenewsonline.net/feed", 2, "CONNECTED"),
    ("Oklahoma Watch", "https://oklahomawatch.org/feed/", 6, "CONNECTED"),
    ("NonDoc", "https://nondoc.com/feed/", 5, "CONNECTED"),
    ("Oklahoma Voice", "https://oklahomavoice.com/feed/", 3, "CONNECTED"),
    ("Osage News", "https://osagenews.org/feed/", 5, "CONNECTED"),
    ("Native America Calling", "https://nativeamericacalling.com/feed/", 4, "CONNECTED"),
    ("Indianz", "https://www.indianz.com/News/feed/", 3, "CONNECTED"),
    ("The Frontier", "https://www.readfrontier.org/stories/feed/", 5, "CONNECTED"),
    ("KOSU", "https://www.kosu.org/news.rss", 3, "CONNECTED"),
    # ⚠ OUT OF REGION, kept and TAGGED rather than dropped. Cherokee One Feather
    # is the Eastern Band of Cherokee Indians on the Qualla Boundary in North
    # Carolina. It is a legitimate Cherokee outlet and it is not Cherokee Nation
    # in Oklahoma, so it must not be mixed silently into a local feed.
    ("Cherokee One Feather (Eastern Band, NC)", "https://theonefeather.com/feed/", 5, "OUT-OF-REGION"),
    # ⛔ StateImpact Oklahoma is DEFUNCT AT THE SOURCE, not merely in its feed:
    # the site's newest article is 4 May 2023 and its footer reads 2011-2023.
    # Recorded here so nobody re-adds it after "discovering" the feed responds.
    # ("StateImpact Oklahoma", "https://stateimpact.npr.org/oklahoma/feed/", 3, "CONNECTED"),
]

ALIVE, STALE, EMPTY, UNREACHABLE = "ALIVE", "STALE", "EMPTY", "UNREACHABLE"

# ---------------------------------------------------------------- classification
#
# TWO QUESTIONS, ANSWERED SEPARATELY:
#   1. is this a Cherokee or Native story?
#   2. what is it about?
#
# ⛔ QUESTION 1 IS NOT ANSWERED BY KEYWORDS ALONE, AND THAT IS THE WHOLE DESIGN.
# A keyword rule tags anything that merely MENTIONS Cherokee, so a Tahlequah
# traffic story that names Cherokee County scores the same as a Tribal Council
# ruling. This project already paid for that mistake once: a rule meant to catch
# banned model names fired 20 times on comments discussing the ban and zero times
# on live usage.
#
# ⭐ SOURCE BEAT IS THE STRONGER SIGNAL AND IT IS FREE. Cherokee Phoenix, ICT,
# Native News Online, Osage News, Indianz and Native America Calling cover Native
# affairs as their beat, so their whole output is in scope by provenance. The
# general outlets are where content matching has to do the work, and there the
# match must be a SUBSTANTIVE term, not a place name that happens to contain
# "Cherokee".
NATIVE_BEAT_SOURCES = {
    "Cherokee Phoenix", "ICT", "Native News Online", "Osage News",
    "Indianz", "Native America Calling",
    "Cherokee One Feather (Eastern Band, NC)",
}

# Substantive markers. "Cherokee County" and "Cherokee Street" are deliberately
# NOT here: they are geography, not the Nation.
NATIVE_TERMS = re.compile(
    r"\b(cherokee nation|tribal council|principal chief|deputy principal chief|"
    r"tribal citizen|tribal government|tribal land|trust land|reservation|"
    r"united keetoowah|keetoowah|muscogee|creek nation|osage|choctaw|chickasaw|"
    r"seminole|quapaw|delaware tribe|indigenous|native american|american indian|"
    r"tribes?\b|tribal\b|sovereignty|mcgirt|freedmen|hoskin|indian health|"
    r"bureau of indian affairs|\bbia\b|indian child welfare|\bicwa\b|"
    r"self.governance|treaty rights|allotment|dawes|"
    # ⭐ ADDED after auditing a real run. The strict rule produced 11 content
    # matches with zero false positives and exactly one miss:
    #   "CHIEF CHAT: Ani Art Center invests in Cherokee cultural renaissance"
    # Bare "cherokee" is still excluded, because that is what keeps Cherokee
    # County and Cherokee Street out. Instead the word is paired with a noun that
    # geography never takes, which recovers the miss without reopening the trap.
    r"cherokee (cultural|culture|language|citizens?|people|artists?|art|"
    r"heritage|history|nationals?|speakers?|families|elders?))", re.I)

# ⚠ A place name alone is NOT a Native story. Kept explicit so the exclusion is
# auditable rather than buried in a negative lookahead nobody can read.
GEOGRAPHY_ONLY = re.compile(
    r"\bcherokee (county|street|avenue|road|hills|village|springs)\b", re.I)

# Topic tags. A story may carry several or none. None is a real answer and must
# not be filled in with a guess.
TOPICS = [
    ("Health", r"\b(health|hospital|clinic|medicaid|medicare|wellness|mental "
               r"health|opioid|nursing|patient|physician|W\.?W\.? Hastings|"
               r"public health|vaccin|disease|care center)\b"),
    ("Elections", r"\b(elect(ion|oral)?|ballot|voter|polling|candidate|campaign|"
                  r"precinct|registrar|primary|runoff|incumbent|seat[s]? up)\b"),
    ("Citizenship", r"\b(citizenship|enroll(ment|ed)?|freedmen|blood quantum|"
                    r"tribal citizen|registration card|descendan)\b"),
    ("Education", r"\b(school|student|teacher|educat|university|college|campus|"
                  r"scholarship|head start|immersion|curriculum|graduat|"
                  r"sequoyah high|classroom)\b"),
    ("Housing", r"\b(housing|home ?owner|rent(al|er)?|mortgage|homeless|"
                r"construction of homes|housing authority|shelter)\b"),
    ("Language and Culture", r"\b(language|syllabary|immersion|culture|cultural|"
                             r"artist|art show|powwow|stickball|traditional|"
                             r"heritage|museum|storytell|basket|regalia|"
                             r"holiday|film|music)\b"),
    ("Business and Economy", r"\b(business|econom|jobs?|employ|revenue|casino|"
                             r"gaming|investment|entrepreneur|grant funding|"
                             r"contract award|tax base|data cent(er|re))\b"),
    ("Courts and Law", r"\b(court|judge|justice|lawsuit|sued?|attorney general|"
                       r"ruling|indict|prosecut|appeal|supreme court|"
                       r"legislation|statute|ordinance|impeach)\b"),
    ("Public Safety", r"\b(police|marshal|sheriff|fire department|arrest|crash|"
                      r"burn ban|emergency|storm|tornado|flood|missing|"
                      r"public safety|drug bust)\b"),
    ("Land and Environment", r"\b(land|water|river|environment|conservation|"
                             r"drought|groundwater|pollut|wildlife|habitat|"
                             r"acreage|into trust|utility|energy|electric)\b"),
    ("Government", r"\b(council|commissioner|mayor|city hall|budget|"
                   r"appropriat|department of|secretary of|executive order|"
                   r"administration|policy|task force|audit)\b"),
    ("Veterans", r"\b(veteran|military|army|navy|marine|air force|national "
                 r"guard|deploy|medal of)\b"),
    # ⛔ THE FIRST TWELVE TAGS COVERED GOVERNANCE AND LEFT 57 PERCENT OF A REAL
    # RUN UNTAGGED. Measured on 300 items: the misses were not edge cases, they
    # were most of what a local paper files. Sports, obituaries, festivals,
    # columns, weather, food, crime and national wire had no category at all.
    # ⭐ A taxonomy built from the subjects you care about, rather than from the
    # copy that actually arrives, will always read as mostly empty.
    ("Crime", r"\b(charged|arrest|guilty|sentenc|convict|felony|homicide|"
              r"burglar|theft|assault|fraud|scam|indicted|deferred sentence|"
              r"unlawful|smuggl|traffick)\b"),
    ("Sports", r"\b(football|basketball|baseball|softball|soccer|golf|track|"
               r"wrestl|volleyball|athlet|coach|tournament|playoff|season "
               r"opener|scored|pitcher|quarterback|stickball)\b"),
    ("Arts and Entertainment", r"\b(festival|concert|band|album|film|movie|"
                               r"documentar|theater|theatre|talent show|"
                               r"gallery|exhibit|gospel|fiddl|dance|gala|"
                               r"performance|gaming convention)\b"),
    ("Food and Agriculture", r"\b(farm|ranch|cattle|crop|harvest|garden|"
                             r"restaurant|recipe|food bank|grocer|drought "
                             r"relief|livestock|salmonella|produce|dining|"
                             r"burrito|barbecue)\b"),
    ("Obituaries", r"\b(obituar|funeral|passed away|memorial service|"
                   r"in memoriam|celebration of life|survived by)\b"),
    ("Community", r"\b(volunteer|fundrais|charity|nonprofit|donation|"
                  r"community center|parade|reunion|club|scout|blood drive|"
                  r"awareness|walk to raise|cooling station|senior center|"
                  r"library|church|congregation)\b"),
    ("Opinion", r"\b(opinion|column|editorial|commentary|letter to the editor|"
                r"guest essay|corner:|chat:|viewpoint)\b"),
    ("Weather", r"\b(weather|storm|lightning|tornado|hail|snow|ice storm|"
                r"heat advisory|flash flood|forecast|drought|wildfire)\b"),
    ("National and World", r"\b(congress|senate|white house|president|federal "
                           r"government|supreme court of the united states|"
                           r"pentagon|state department|israel|ukraine|"
                           r"washington|d\.c\.|nationwide|across the country)\b"),
    ("Technology", r"\b(technolog|software|artificial intelligence|\bai\b|"
                   r"broadband|internet|cyber|surveillance|camera system|"
                   r"app\b|online platform|telehealth)\b"),
    ("Transportation", r"\b(highway|road work|bridge|traffic|transit|bus |"
                       r"railroad|airport|trail|route \d|turnpike|crash on)\b"),
]
# ⛔⛔ THE TRAILING \b MUST TOLERATE A SUFFIX, AND I GOT THIS WRONG TWICE IN ONE DAY.
# `\bvoter\b` does not match "voters": the closing boundary needs a non-word
# character and the plural "s" is a word character. The tag table was written with
# `\b` on every term, so Elections missed "Tahlequah voters decide two sales tax
# measures" entirely. This is the same defect, in the same shape, as the banned
# model rule that missed "qwen2.5" earlier today because a digit followed the name.
# ⭐ Knowing the class did not stop me writing it again, which is the argument for
# a control that runs rather than a lesson that is remembered.
# Extra stems the governance-shaped list missed. Each one was taken from a real
# headline that fell to General on the 17 August run, not invented.
TOPICS += [
    ("Elections", r"\b(vot|early voting|state question|nominating cycle|"
                  r"electorate|turnout)"),
    ("Health", r"\b(health|nutrition|yoga|tai chi|aging|wellbeing|well.being|"
               r"sickle cell|cancer|diabet|therapy|fitness)"),
    ("Opinion", r"(corner|chat|column|essay|grammar dog|viewpoint|"
                r"our view|guest opinion)"),
    ("Arts and Entertainment", r"\b(documentar|author|novel|book|podcast|"
                               r"episode|actor|artist|museum|storytell)"),
    ("Business and Economy", r"\b(retire|insurance|market|trading|invest|"
                             r"wage|payroll|industry|commerce|bank)"),
    ("Land and Environment", r"\b(bulldozer|consent decree|acre|habitat|"
                             r"watershed|reservoir|erosion|solar|wind farm)"),
    # Second evidence pass, taken from what was still landing on General.
    ("Features", r"(get to know|smile of the day|what's happening|words from|"
                 r"profile|slice of life|spotlight|meet the|q ?& ?a|"
                 r"day in the life)"),
    ("History and Heritage", r"\b(historical societ|heritage|legacy|"
                             r"anniversar|remember|archive|ancestor|"
                             r"generations|founded in|centennial)"),
    ("Youth", r"\b(\bffa\b|4.h|youth|scout|camp\b|teen|kids|children|"
              r"leadership camp|junior|club member)"),
    ("Media", r"\b(journalis|newspaper|press freedom|fake news|broadcast|"
              r"reporter|newsroom|media\b|editor\b)"),
    ("Events", r"\b(returns to|festival|fair\b|calendar|upcoming|"
               r"to be held|hosts|open house|ribbon cutting|"
               r"grand opening|tournament)"),
    ("Courts and Law", r"\b(indian child welfare|\bicwa\b|petition|statute|"
                       r"guidance|compliance|regulat)"),
]

# ⭐ STEM MATCHING, NOT A LONGER SUFFIX LIST. Allowing (s|es|ed|ing) still missed
# "healthy" from health, "voting" from voter and "nutrition" outright, and every
# miss dropped a story into General. Topic tagging is a SORTING AID: recall
# matters, and a stray match costs a reader one glance. So the trailing word
# boundary is dropped and terms match as prefixes.
# ⚠ The trade is real and accepted: "land" now also matches "landing". That is a
# bad failure in a gate and a fine one on a shelf label.
_compiled = []
for _name, _pat in TOPICS:
    if isinstance(_pat, str):
        if _pat.endswith(r")\b"):
            # Strip the trailing \b ONLY. `pat[:-2]` already leaves the closing
            # paren in place; appending another one broke all 23 patterns at once.
            _pat = _pat[:-2]
        _compiled.append((_name, re.compile(_pat, re.I)))
    else:
        _compiled.append((_name, _pat))
TOPICS = _compiled


def classify(item):
    """Return (is_native, why, [tags]).

    `why` records HOW the native call was made, so a reader can audit a
    surprising placement instead of trusting it.
    """
    text = "%s %s" % (item.get("title") or "", item.get("source") or "")
    if item.get("source") in NATIVE_BEAT_SOURCES:
        native, why = True, "source beat"
    else:
        m = NATIVE_TERMS.search(item.get("title") or "")
        if m and not GEOGRAPHY_ONLY.search(item.get("title") or ""):
            native, why = True, "term: %s" % m.group(0).lower()
        else:
            native, why = False, ""
    tags = [name for name, rx in TOPICS if rx.search(text)]
    # ⛔ EVERY STORY CARRIES AT LEAST ONE TAG. An untagged row is useless to a
    # newsroom: it cannot be filtered, sorted or handed to anyone.
    # ⚠ AND "General" IS A MEASUREMENT, NOT A DUMPING GROUND. If it grows past a
    # small share of a run, the taxonomy is wrong and the fix is a new category,
    # never a wider fallback. The share is printed on every run and shown on the
    # page so it cannot quietly become the biggest tag on the wire.
    if not tags:
        tags = ["General"]
    return native, why, tags


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------- date handling

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_date(text):
    """Parse RFC 822 or ISO 8601. Returns aware datetime or None.

    Returns None rather than a guess. A feed whose dates cannot be read is a
    feed whose liveness is UNKNOWN, and unknown must never render as fresh.
    """
    if not text:
        return None
    t = text.strip()
    # RFC 822: Wed, 13 Aug 2026 14:05:00 +0000
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})"
                  r"(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?", t)
    if m and m.group(2)[:3].lower() in _MONTHS:
        try:
            return datetime.datetime(
                int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1)),
                int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0),
                tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    # ISO 8601
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?", t)
    if m:
        try:
            return datetime.datetime(
                *[int(m.group(i) or 0) for i in range(1, 7)],
                tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return datetime.datetime(int(m.group(1)), int(m.group(2)),
                                     int(m.group(3)),
                                     tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    return None


# --------------------------------------------------------------- feed handling

def strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/rss+xml,"
                                                         "application/xml,text/xml,*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read()


def parse_items(raw):
    """Return a list of {title, link, published, published_raw}. Handles RSS+Atom."""
    root = ET.fromstring(raw)
    items = []
    for node in root.iter():
        if strip_ns(node.tag) not in ("item", "entry"):
            continue
        rec = {"title": "", "link": "", "published": None, "published_raw": ""}
        for child in node:
            name = strip_ns(child.tag)
            if name == "title" and child.text:
                rec["title"] = " ".join(child.text.split())
            elif name == "link":
                rec["link"] = (child.get("href") or child.text or "").strip()
            elif name in ("pubDate", "published", "updated", "date"):
                if child.text and not rec["published_raw"]:
                    rec["published_raw"] = child.text.strip()
        rec["published"] = parse_date(rec["published_raw"])
        if rec["title"] or rec["link"]:
            items.append(rec)
    return items


def poll(name, url, stale_after_days, tier):
    started = now_utc()
    rec = {"source": name, "url": url, "tier": tier,
           "stale_after_days": stale_after_days,
           "checked_at": iso(started), "http_status": None,
           "parsed": False, "item_count": 0, "newest_item": None,
           "newest_item_age_days": None, "verdict": UNREACHABLE, "error": None,
           "items": []}
    try:
        status, raw = fetch(url)
        rec["http_status"] = status
    except Exception as exc:                                   # noqa: BLE001
        rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        return rec

    try:
        items = parse_items(raw)
        rec["parsed"] = True
    except Exception as exc:                                   # noqa: BLE001
        rec["error"] = "parse failed: %s: %s" % (type(exc).__name__,
                                                 str(exc)[:140])
        return rec

    rec["item_count"] = len(items)
    rec["items"] = items

    # ⛔ ZERO ITEMS IS NOT HEALTHY. This is the KOSU case: 200 OK, valid RSS,
    # fresh lastBuildDate, nothing in it.
    if not items:
        rec["verdict"] = EMPTY
        return rec

    dated = [i["published"] for i in items if i["published"]]
    if not dated:
        # Dates unreadable. Liveness is UNKNOWN, and unknown is not fresh.
        rec["verdict"] = EMPTY
        rec["error"] = ("%d items but no readable dates, so newest-item age "
                        "cannot be measured" % len(items))
        return rec

    newest = max(dated)
    age_days = (started - newest).total_seconds() / 86400.0
    rec["newest_item"] = iso(newest)
    rec["newest_item_age_days"] = round(age_days, 2)
    rec["verdict"] = STALE if age_days > stale_after_days else ALIVE
    return rec


# --------------------------------------------------------------- aggregation

def norm_keys(item):
    r"""Return every key under which this item counts as already seen.

    ⛔ KEYING ON LINK ALONE DOES NOT DEDUPE SYNDICATION, AND THAT IS THE CASE
    THAT ACTUALLY OCCURS HERE. The CNHI sister papers run the same story under
    their own domains, so Muskogee Phoenix and Tahlequah Daily Press carry
    byte-identical headlines at the same timestamp on different URLs. Measured
    17 August 2026: 9 of their top 20 items were shared, 45 percent, including
    every Cherokee-relevant one.
    ⭐ The first version of this function returned `link or title`, so a title was
    only consulted when a link was MISSING. Across 407 real items it removed
    exactly zero duplicates while nearly half of two sources overlapped. The
    control that passed it used same-link variants, which is the one shape the
    bug does not cover: the control was weaker than the world.
    """
    keys = []
    link = (item.get("link") or "").strip().lower()
    if link:
        link = re.sub(r"[?#].*$", "", link).rstrip("/")
        keys.append("l:" + link)
    title = re.sub(r"\W+", " ", (item.get("title") or "").lower()).strip()
    if len(title) >= 20:
        # Short headlines collide by chance; long ones do not. 20 characters is a
        # judgement, not a measurement, and it is stated here so it can be revised.
        keys.append("t:" + title)
    return [hashlib.sha1(k.encode("utf-8")).hexdigest() for k in keys]


def merge(records):
    """Merge every connected source. Counts BEFORE and AFTER dedup.

    ⛔ The delta is recorded as a field. A dedup that collapses duplicates before
    anything counts them reports the number of SURVIVORS and hides the collapse.
    """
    raw = []
    for rec in records:
        for it in rec["items"]:
            row = {"source": rec["source"], "title": it["title"],
                   "link": it["link"],
                   "published": iso(it["published"]) if it["published"] else None}
            native, why, tags = classify(row)
            row["native"] = native
            row["native_why"] = why
            row["tags"] = tags
            raw.append(row)
    before = len(raw)
    seen, merged = set(), []
    for it in raw:
        keys = norm_keys(it)
        if any(k in seen for k in keys):
            continue
        seen.update(keys)
        merged.append(it)
    after = len(merged)
    merged.sort(key=lambda i: i["published"] or "", reverse=True)
    return merged, {"items_before_dedup": before, "items_after_dedup": after,
                    "duplicates_removed": before - after}


# --------------------------------------------------------------- state + alarm

def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def transitions(previous, records):
    """State CHANGES only, both directions. Never the standing condition."""
    prev = {s["source"]: s for s in previous.get("sources", [])}
    out = []
    for rec in records:
        was = prev.get(rec["source"], {}).get("verdict")
        now_v = rec["verdict"]
        if was is None or was == now_v:
            continue
        healthy = {ALIVE}
        if (was in healthy) != (now_v in healthy):
            out.append({"source": rec["source"], "from": was, "to": now_v,
                        "newest_item": rec["newest_item"],
                        "age_days": rec["newest_item_age_days"]})
    return out


def render_report(records, stats, trans, started):
    lines = []
    lines.append("# Cherokee 411 news monitor")
    lines.append("")
    lines.append("Polled %s. Aggregator version %s." % (iso(started), VERSION))
    lines.append("")
    lines.append("Liveness is measured as the age of the newest item in each feed.")
    lines.append("A feed that responds, parses and carries a current build date can")
    lines.append("still be dead. Newest item age is the only signal here that can go")
    lines.append("red.")
    lines.append("")
    lines.append("| source | tier | verdict | items | newest item | age (days) | stale after |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in sorted(records, key=lambda x: (x["tier"], x["source"])):
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            r["source"], r["tier"], r["verdict"], r["item_count"],
            r["newest_item"] or "none readable",
            r["newest_item_age_days"] if r["newest_item_age_days"] is not None else "n/a",
            r["stale_after_days"]))
    lines.append("")
    lines.append("Ingest: %d items before dedup, %d after, %d duplicates removed."
                 % (stats["items_before_dedup"], stats["items_after_dedup"],
                    stats["duplicates_removed"]))
    lines.append("")
    lines.append("That is raw ingest. It is not an alert count and must not be")
    lines.append("quoted as one, because what reaches a person depends on match")
    lines.append("rules that are not built yet.")
    lines.append("")
    if trans:
        lines.append("## State changes since the last poll")
        lines.append("")
        for t in trans:
            lines.append("- %s moved %s to %s. Newest item %s."
                         % (t["source"], t["from"], t["to"],
                            t["newest_item"] or "unknown"))
    else:
        lines.append("No state changes since the last poll.")
    lines.append("")
    lines.append("## Thresholds are first pass")
    lines.append("")
    lines.append("Every stale-after figure above came from a single observation")
    lines.append("window on 3 August 2026, set at roughly three times each source's")
    lines.append("own measured publishing interval. They need one revision after a")
    lines.append("fortnight of real data. Until that happens they are provisional,")
    lines.append("and this note stays in the report so a first guess is never read")
    lines.append("as a tuned number.")
    lines.append("")
    manual = [r for r in records if r["tier"] == "MANUAL"]
    if manual:
        lines.append("## Sources that need a human check")
        lines.append("")
        lines.append("These publish actively but their feeds cannot be trusted, so")
        lines.append("they are polled for the record and still need eyes. Seven")
        lines.append("connected sources must never read as coverage of ten.")
        lines.append("")
        for r in manual:
            lines.append("- %s, last checked %s, verdict %s."
                         % (r["source"], r["checked_at"], r["verdict"]))
    return "\n".join(lines) + "\n"


HTML_HEAD = """<meta charset="utf-8">
<title>Cherokee 411 news feed</title>
<style>
:root{--red:#b22d1f;--ink:#1c1c1c;--mute:#6b6b6b;--line:#e2e2e2;--bg:#faf9f7;--card:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.5 "Open Sans",-apple-system,Segoe UI,Roboto,sans-serif}
header{background:var(--red);color:#fff;padding:18px 22px}
header h1{margin:0;font:700 21px/1.2 "Roboto Condensed",Arial,sans-serif;
 letter-spacing:.02em;text-transform:uppercase}
header .sub{opacity:.92;font-size:13px;margin-top:4px}
.wrap{max-width:1180px;margin:0 auto;padding:18px 22px 60px}
.health{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 20px}
.pill{font-size:12px;padding:4px 9px;border-radius:11px;border:1px solid var(--line);
 background:var(--card);white-space:nowrap}
.pill b{font-weight:600}
.ALIVE{border-color:#bcd9bc;background:#f2f8f2}
.STALE{border-color:#e8c98a;background:#fdf6e7}
.EMPTY,.UNREACHABLE{border-color:#e3a9a2;background:#fbeeec}
.OUT{border-color:#c9c9d8;background:#f4f4f8}
.bar{background:var(--card);border:1px solid var(--line);border-radius:8px;
 padding:11px 14px;margin-bottom:20px;font-size:13px;color:var(--mute)}
h2{font:600 13px/1 "Roboto Condensed",Arial,sans-serif;text-transform:uppercase;
 letter-spacing:.09em;color:var(--mute);margin:26px 0 10px;padding-bottom:6px;
 border-bottom:1px solid var(--line)}
ul{list-style:none;margin:0;padding:0}
li{background:var(--card);border:1px solid var(--line);border-radius:8px;
 padding:11px 14px;margin-bottom:7px}
li a{color:var(--ink);text-decoration:none;font-weight:600}
li a:hover{color:var(--red);text-decoration:underline}
.meta{font-size:12px;color:var(--mute);margin-top:3px}
.src{color:var(--red);font-weight:600}
.oor{color:#5a5a7a}
footer{color:var(--mute);font-size:12px;margin-top:34px;border-top:1px solid var(--line);
 padding-top:12px}
@media(prefers-color-scheme:dark){
 :root{--ink:#ececec;--mute:#9a9a9a;--line:#333;--bg:#151515;--card:#1e1e1e}
 li a{color:#ececec}
}
</style>"""


def render_html(records, stats, merged, started):
    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    out = [HTML_HEAD]
    out.append('<header><h1>Cherokee 411 news feed</h1>'
               '<div class="sub">%d stories from %d sources. Updated %s UTC, '
               'refreshed hourly.</div></header><div class="wrap">'
               % (len(merged), len([r for r in records if r["tier"] != "OUT-OF-REGION"]),
                  started.strftime("%d %b %Y %H:%M")))

    out.append('<div class="health">')
    for r in sorted(records, key=lambda x: (x["verdict"] != "ALIVE", x["source"])):
        cls = "OUT" if r["tier"] == "OUT-OF-REGION" else r["verdict"]
        age = ("%.1fd" % r["newest_item_age_days"]) if r["newest_item_age_days"] is not None else "?"
        out.append('<span class="pill %s"><b>%s</b> %s, newest %s</span>'
                   % (cls, esc(r["source"]), r["verdict"].lower(), age))
    out.append("</div>")

    out.append('<div class="bar">Liveness is the age of each feed\'s newest item. '
               'A feed can return 200, parse cleanly and carry a fresh build date '
               'while the newsroom has stopped filing, so nothing else is trusted '
               'here. %d items ingested, %d after removing %d duplicates. That is '
               'raw ingest, not an alert count.</div>'
               % (stats["items_before_dedup"], stats["items_after_dedup"],
                  stats["duplicates_removed"]))

    buckets, today = {}, started.date()
    for it in merged:
        d = (it["published"] or "")[:10]
        try:
            dt = datetime.date(int(d[:4]), int(d[5:7]), int(d[8:10]))
            delta = (today - dt).days
            label = ("Today" if delta <= 0 else "Yesterday" if delta == 1
                     else "This week" if delta <= 7 else "Earlier")
        except (ValueError, TypeError):
            label = "Undated"
        buckets.setdefault(label, []).append(it)

    for label in ("Today", "Yesterday", "This week", "Earlier", "Undated"):
        items = buckets.get(label)
        if not items:
            continue
        out.append("<h2>%s, %d</h2><ul>" % (label, len(items)))
        for it in items[:120]:
            oor = " oor" if "Eastern Band" in it["source"] else ""
            tag = " (out of region)" if oor else ""
            out.append('<li><a href="%s" target="_blank" rel="noopener">%s</a>'
                       '<div class="meta"><span class="src%s">%s%s</span> &middot; %s</div></li>'
                       % (esc(it["link"]), esc(it["title"]) or "(untitled)", oor,
                          esc(it["source"]), tag,
                          esc((it["published"] or "undated").replace("T", " ").rstrip("Z"))))
        out.append("</ul>")

    out.append('<footer>Cherokee 411 news monitor %s. Thresholds are first pass, '
               'derived from a single observation window, and need one revision '
               'after a fortnight of real data.</footer></div>' % VERSION)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="poll and report without writing state")
    args = ap.parse_args()

    started = now_utc()
    os.makedirs(OUT_DIR, exist_ok=True)
    previous = load_state()

    records = []
    print("Cherokee 411 news monitor, version %s" % VERSION)
    print("%-24s %-10s %-12s %6s  %s" % ("source", "tier", "verdict", "items",
                                         "newest item"))
    print("-" * 88)
    for name, url, stale_days, tier in SOURCES:
        rec = poll(name, url, stale_days, tier)
        records.append(rec)
        print("%-24s %-10s %-12s %6d  %s%s" % (
            rec["source"], rec["tier"], rec["verdict"], rec["item_count"],
            rec["newest_item"] or "none readable",
            ("   [%s]" % rec["error"][:44]) if rec["error"] else ""))

    connected = [r for r in records if r["tier"] == "CONNECTED"]
    merged, stats = merge(connected)
    trans = transitions(previous, records)

    print("\nIngest: %d before dedup, %d after, %d duplicates removed."
          % (stats["items_before_dedup"], stats["items_after_dedup"],
             stats["duplicates_removed"]))
    print("Raw ingest only. NOT an alert count.")

    if trans:
        print("\nSTATE CHANGES (this is what would notify):")
        for t in trans:
            print("  %s: %s -> %s" % (t["source"], t["from"], t["to"]))
    else:
        print("\nNo state changes since the last poll. Nothing would notify.")

    if args.dry_run:
        print("\n--dry-run: no state written, nothing notified.")
        return 0

    state = {"polled_at": iso(started), "version": VERSION,
             "sources": [{k: v for k, v in r.items() if k != "items"}
                         for r in records],
             "stats": stats}
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)

    feed_path = os.path.join(OUT_DIR, "aggregated-items.json")
    with open(feed_path, "w", encoding="utf-8") as fh:
        json.dump({"generated": iso(started), "stats": stats,
                   "items": merged[:300]}, fh, indent=2)

    report_path = os.path.join(OUT_DIR, "NEWS-MONITOR.md")
    with open(report_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_report(records, stats, trans, started))

    html_path = os.path.join(OUT_DIR, "index.html")
    with open(html_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_html(records, stats, merged, started))

    print("\nstate  -> %s" % STATE_PATH)
    print("items  -> %s" % feed_path)
    print("report -> %s" % report_path)
    print("PAGE   -> %s" % html_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
