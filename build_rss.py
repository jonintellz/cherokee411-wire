"""Emit a real RSS 2.0 feed from the aggregated items.

WHY THIS EXISTS. Everything shipped so far has been an HTML page: a picture of the news at
one moment. A reader app cannot subscribe to that. This writes an actual feed document, so
the URL is a thing Cara pastes into any reader and it refreshes on its own whenever the file
behind the URL is rewritten. "Auto-updating" is a property of the HOSTING plus the SCHEDULE,
not of the document, so this is one of two halves; the other is a host that serves it and a
job that regenerates it.

CORRECTNESS NOTES, because a feed that a reader silently rejects looks identical to one that
works until somebody tries to subscribe:
  * RFC 822 dates. RSS 2.0 requires them; ISO 8601 is what the aggregator stores, so it is
    converted here rather than passed through.
  * <guid isPermaLink="false"> carries a stable hash, so an item that changes title does not
    reappear as new.
  * Text is XML-escaped and control characters stripped. A raw ampersand in a headline makes
    the whole document unparseable, which is the classic way a feed dies.
  * <atom:link rel="self"> is required by validators and by some readers for discovery.
"""
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from xml.sax.saxutils import escape

NEWS = os.environ.get("C411_OUT") or r"C:\IntellzOps\reports\client\cherokee411\news"
ITEMS = os.path.join(NEWS, "aggregated-items.json")

# Where the feed will live once hosted. Passed in so the self-link is correct for whichever
# host is chosen; a wrong self-link is a validator error and a discovery failure.
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://example.invalid/c411"

RFC822 = "%a, %d %b %Y %H:%M:%S +0000"
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean(s):
    return CTRL.sub("", (s or "")).strip()


def rfc822(iso):
    """ISO 8601 to RFC 822. RSS 2.0 requires RFC 822 and readers do enforce it."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime(RFC822)
    except ValueError:
        return None


def build(items, generated, out_path, title, desc, only=None):
    sel = items
    if only == "native":
        sel = [i for i in items if i.get("native")]
    sel = sorted(sel, key=lambda i: i.get("published") or "", reverse=True)

    now = rfc822(generated) or datetime.now(timezone.utc).strftime(RFC822)
    self_url = BASE.rstrip("/") + "/" + os.path.basename(out_path)

    p = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"'
         ' xmlns:dc="http://purl.org/dc/elements/1.1/">',
         "<channel>",
         "<title>%s</title>" % escape(title),
         "<link>%s</link>" % escape(BASE.rstrip("/") + "/"),
         "<description>%s</description>" % escape(desc),
         "<language>en-us</language>",
         "<lastBuildDate>%s</lastBuildDate>" % now,
         "<pubDate>%s</pubDate>" % now,
         "<ttl>60</ttl>",
         '<atom:link href="%s" rel="self" type="application/rss+xml"/>' % escape(self_url)]

    for i in sel:
        link = clean(i.get("link"))
        t = clean(i.get("title")) or "(untitled)"
        src = clean(i.get("source"))
        tags = [clean(x) for x in (i.get("tags") or []) if clean(x)]
        guid = hashlib.sha1((link or t).encode("utf-8")).hexdigest()
        pub = rfc822(i.get("published"))

        p.append("<item>")
        p.append("<title>%s</title>" % escape(t))
        if link:
            p.append("<link>%s</link>" % escape(link))
        p.append('<guid isPermaLink="false">%s</guid>' % guid)
        if pub:
            p.append("<pubDate>%s</pubDate>" % pub)
        if src:
            p.append("<dc:creator>%s</dc:creator>" % escape(src))
            p.append("<source url=\"%s\">%s</source>"
                     % (escape(BASE.rstrip("/") + "/"), escape(src)))
        for tg in tags:
            p.append("<category>%s</category>" % escape(tg))
        bits = []
        if src:
            bits.append(escape(src))
        if tags:
            bits.append(escape(", ".join(tags)))
        p.append("<description>%s</description>" % escape(" | ".join(bits)))
        p.append("</item>")

    p.append("</channel>")
    p.append("</rss>")

    with io.open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(p))
    return len(sel), os.path.getsize(out_path)


if __name__ == "__main__":
    d = json.load(io.open(ITEMS, encoding="utf-8"))
    items = d.get("items", [])
    generated = d.get("generated")

    jobs = [
        ("cherokee411-all.xml", "Cherokee 411 Wire",
         "Regional and Native news wire for the Cherokee Nation reservation "
         "and northeast Oklahoma.", None),
        ("cherokee411-native.xml", "Cherokee 411 Wire, Cherokee and Native",
         "Cherokee and Native coverage only.", "native"),
    ]
    for fn, title, desc, only in jobs:
        n, size = build(items, generated, os.path.join(NEWS, fn), title, desc, only)
        print("wrote %-26s %4d items  %6d bytes" % (fn, n, size))
    print("self-link base: %s" % BASE)
