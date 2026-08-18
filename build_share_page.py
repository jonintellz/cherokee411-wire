r"""Build the shareable snapshot page for Cherokee 411 staff.

⛔ THIS PAGE CANNOT REFRESH ITSELF. A published artifact has no capability to
fetch the feeds, so it is a POINT IN TIME SNAPSHOT. The stamp sits in the
masthead, not in a footnote, and it names the moment in words a reader cannot
mistake for "now". A page that looks live and is not is the exact failure this
monitor exists to catch in other people's feeds.
"""

import datetime
import io
import json
import os

NEWS = os.environ.get("C411_OUT") or os.path.join(
    "C:\\", "IntellzOps", "reports", "client", "cherokee411", "news")
OUT = os.path.join(NEWS, "share.html")

with io.open(os.path.join(NEWS, "feed-state.json"), encoding="utf-8") as fh:
    state = json.load(fh)
with io.open(os.path.join(NEWS, "aggregated-items.json"), encoding="utf-8") as fh:
    feed = json.load(fh)

sources = state["sources"]
items = feed["items"]
stats = feed["stats"]
taken = state["polled_at"]


def esc(s):
    return ((s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def stamp_words(iso_s):
    d = datetime.datetime.strptime(iso_s, "%Y-%m-%dT%H:%M:%SZ")
    return d.strftime("%A %d %B %Y at %H:%M UTC")


live = [s for s in sources if s["verdict"] == "ALIVE"]
quiet = [s for s in sources if s["verdict"] != "ALIVE"]
in_region = [s for s in sources if s["tier"] != "OUT-OF-REGION"]

native = [i for i in items if i.get("native")]
other = [i for i in items if not i.get("native")]

tag_counts = {}
for i in items:
    for t in i.get("tags", []):
        tag_counts[t] = tag_counts.get(t, 0) + 1

taken_date = datetime.datetime.strptime(taken, "%Y-%m-%dT%H:%M:%SZ").date()


def bucket(rows):
    out = {}
    for it in rows:
        d = (it.get("published") or "")[:10]
        try:
            dt = datetime.date(int(d[:4]), int(d[5:7]), int(d[8:10]))
            delta = (taken_date - dt).days
            key = ("Today" if delta <= 0 else "Yesterday" if delta == 1
                   else "Earlier this week" if delta <= 7 else "Older")
        except (ValueError, TypeError):
            key = "Undated"
        out.setdefault(key, []).append(it)
    return out


ORDER = ["Today", "Yesterday", "Earlier this week", "Older", "Undated"]

CSS = """
:root{
  --ink:#1a1614; --ink-soft:#5b514c; --ink-faint:#8a7d76;
  --paper:#f7f4f1; --card:#fffdfc; --rule:#e3dbd5;
  --crimson:#b22d1f; --crimson-soft:#f3e3e0;
  --live:#3f6f4a; --live-bg:#e9f1ea;
  --quiet:#8a6414; --quiet-bg:#f7efdd;
  --tag-bg:#efe9e5; --tag-ink:#5b514c;
  --shadow:0 1px 2px rgba(26,22,20,.05);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ink:#efe9e6; --ink-soft:#b3a8a2; --ink-faint:#877b75;
    --paper:#16130f; --card:#211c19; --rule:#352d29;
    --crimson:#e0705f; --crimson-soft:#3a231f;
    --live:#7fb389; --live-bg:#1e2a20;
    --quiet:#d0a44a; --quiet-bg:#2c2416;
    --tag-bg:#2b2421; --tag-ink:#b3a8a2;
    --shadow:none;
  }
}
:root[data-theme="dark"]{
  --ink:#efe9e6; --ink-soft:#b3a8a2; --ink-faint:#877b75;
  --paper:#16130f; --card:#211c19; --rule:#352d29;
  --crimson:#e0705f; --crimson-soft:#3a231f;
  --live:#7fb389; --live-bg:#1e2a20;
  --quiet:#d0a44a; --quiet-bg:#2c2416;
  --tag-bg:#2b2421; --tag-ink:#b3a8a2;
  --shadow:none;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
 font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
.masthead{border-bottom:2px solid var(--crimson);background:var(--card)}
.masthead .inner{max-width:1080px;margin:0 auto;padding:26px 24px 20px}
.kicker{font:600 11px/1 system-ui,sans-serif;letter-spacing:.16em;
 text-transform:uppercase;color:var(--crimson);margin:0 0 10px}
h1{margin:0;font:400 34px/1.1 Georgia,"Iowan Old Style","Times New Roman",serif;
 letter-spacing:-.01em;text-wrap:balance}
.snapshot{margin:16px 0 0;padding:11px 14px;border-radius:7px;
 background:var(--crimson-soft);border:1px solid var(--crimson);
 color:var(--ink);font-size:14px;line-height:1.5}
.snapshot b{font-weight:650}
.wrap{max-width:1080px;margin:0 auto;padding:24px}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
 gap:12px;margin:0 0 26px}
.stat{background:var(--card);border:1px solid var(--rule);border-radius:8px;
 padding:13px 15px;box-shadow:var(--shadow)}
.stat .n{font:600 26px/1 system-ui,sans-serif;font-variant-numeric:tabular-nums;
 display:block;margin-bottom:3px}
.stat .l{font-size:12px;color:var(--ink-soft);letter-spacing:.03em}
.band{margin:34px 0 0;padding:15px 18px;border-radius:9px;
 background:var(--card);border:1px solid var(--rule);border-left:5px solid var(--crimson)}
.band.plain{border-left-color:var(--ink-faint)}
.band h3{margin:0;font:400 23px/1.2 Georgia,"Times New Roman",serif}
.band p{margin:5px 0 0;font-size:13.5px;color:var(--ink-soft)}
h2{font:600 12px/1 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;
 color:var(--ink-faint);margin:24px 0 11px;padding-bottom:7px;
 border-bottom:1px solid var(--rule)}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chip{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;
 padding:5px 11px;border-radius:20px;border:1px solid var(--rule);background:var(--card)}
.chip .dot{width:7px;height:7px;border-radius:50%;flex:none}
.chip.live{background:var(--live-bg);border-color:var(--live)}
.chip.live .dot{background:var(--live)}
.chip.quiet{background:var(--quiet-bg);border-color:var(--quiet)}
.chip.quiet .dot{background:var(--quiet)}
.chip .age{color:var(--ink-soft);font-variant-numeric:tabular-nums}
.chip.region{border-style:dashed}
.chip.count{background:var(--tag-bg);border-color:transparent;color:var(--tag-ink)}
.chip.count b{color:var(--ink);font-variant-numeric:tabular-nums}
ul.wire{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
ul.wire li{background:var(--card);border:1px solid var(--rule);border-radius:8px;
 padding:12px 15px;box-shadow:var(--shadow)}
ul.wire a{color:var(--ink);text-decoration:none;font-weight:600;font-size:16px;
 line-height:1.35;display:inline-block;text-wrap:pretty}
ul.wire a:hover{color:var(--crimson);text-decoration:underline}
ul.wire a:focus-visible{outline:2px solid var(--crimson);outline-offset:3px;border-radius:3px}
.meta{margin-top:5px;font-size:12.5px;color:var(--ink-soft);font-variant-numeric:tabular-nums}
.meta .src{color:var(--crimson);font-weight:600}
.meta .oor{color:var(--ink-faint);font-style:italic}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.tag{font-size:11px;letter-spacing:.04em;padding:3px 8px;border-radius:4px;
 background:var(--tag-bg);color:var(--tag-ink);font-weight:600}
.untagged{font-size:11px;color:var(--ink-faint);font-style:italic;margin-top:7px}
footer{max-width:1080px;margin:34px auto 0;padding:26px 24px 60px;
 color:var(--ink-faint);font-size:12.5px;border-top:1px solid var(--rule)}
footer p{margin:0 0 8px}
@media (max-width:600px){
  h1{font-size:26px}
  .wrap,.masthead .inner,footer{padding-left:16px;padding-right:16px}
}
"""


def render_rows(rows, limit=80):
    out = []
    for it in rows[:limit]:
        oor = "Eastern Band" in it["source"]
        src = it["source"].replace(" (Eastern Band, NC)", "")
        tail = ('<span class="oor"> outside the reservation, North Carolina</span>'
                if oor else "")
        when = (it.get("published") or "undated").replace("T", " ").rstrip("Z")
        tags = it.get("tags") or []
        tagbits = "".join('<span class="tag">%s</span>' % esc(t) for t in tags)
        tagline = ('<div class="tags">%s</div>' % tagbits if tags else
                   '<div class="untagged">no topic matched</div>')
        out.append('<li><a href="%s" target="_blank" rel="noopener">%s</a>'
                   '<div class="meta"><span class="src">%s</span>%s &middot; %s</div>'
                   "%s</li>"
                   % (esc(it["link"]), esc(it["title"]) or "Untitled",
                      esc(src), tail, esc(when), tagline))
    return "".join(out)


out = ['<meta name="viewport" content="width=device-width,initial-scale=1">',
       "<title>Cherokee 411 Wire Monitor</title>",
       "<style>%s</style>" % CSS]

out.append('<div class="masthead"><div class="inner">')
out.append('<p class="kicker">Newsroom monitor</p>')
out.append("<h1>What the wire carried</h1>")
out.append('<div class="snapshot">This is a <b>fixed snapshot</b>, taken %s. '
           "It does not update on its own, and reopening this link will not "
           "bring in newer stories. Ask for a fresh one whenever you need it."
           "</div>" % stamp_words(taken))
out.append("</div></div>")

out.append('<div class="wrap">')
out.append('<div class="summary">')
for n, label in ((len(native), "Cherokee and Native"),
                 (len(other), "regional and other"),
                 (len(in_region), "sources in region"),
                 (len(quiet), "gone quiet"),
                 (stats["duplicates_removed"], "duplicates removed")):
    out.append('<div class="stat"><span class="n">%d</span>'
               '<span class="l">%s</span></div>' % (n, label))
out.append("</div>")

out.append("<h2>Topics across everything carried</h2><div class=\"chips\">")
for t, n in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
    out.append('<span class="chip count">%s <b>%d</b></span>' % (esc(t), n))
out.append("</div>")

out.append("<h2>Where the stories came from</h2><div class=\"chips\">")
for s in sorted(sources, key=lambda x: (x["verdict"] != "ALIVE", x["source"])):
    oor = s["tier"] == "OUT-OF-REGION"
    cls = "live" if s["verdict"] == "ALIVE" else "quiet"
    age = ("%.1f days" % s["newest_item_age_days"]) if s["newest_item_age_days"] is not None else "unknown"
    name = s["source"].replace(" (Eastern Band, NC)", "")
    out.append('<span class="chip %s%s"><span class="dot"></span>%s'
               '<span class="age">%s</span></span>'
               % (cls, " region" if oor else "", esc(name), age))
out.append("</div>")

out.append('<div class="band"><h3>Cherokee and Native news</h3>'
           "<p>%d stories. A story lands here because it came from a newsroom "
           "whose beat is Native affairs, or because its headline carries a "
           "substantive term such as Cherokee Nation, Tribal Council or "
           "sovereignty. A place name on its own does not qualify, so Cherokee "
           "County road works stay out.</p></div>" % len(native))
nb = bucket(native)
for key in ORDER:
    if nb.get(key):
        out.append("<h2>%s, %d</h2><ul class=\"wire\">%s</ul>"
                   % (key, len(nb[key]), render_rows(nb[key])))

out.append('<div class="band plain"><h3>Regional and other news</h3>'
           "<p>%d stories from the same sources that did not meet the test "
           "above. Worth scanning: the split is deliberately strict, so a "
           "Cherokee story written without any of those terms in its headline "
           "will sit here.</p></div>" % len(other))
ob = bucket(other)
for key in ORDER:
    if ob.get(key):
        out.append("<h2>%s, %d</h2><ul class=\"wire\">%s</ul>"
                   % (key, len(ob[key]), render_rows(ob[key], limit=60)))
out.append("</div>")

out.append("<footer>")
out.append("<p>Sources are judged live or quiet by one measure only: how old "
           "their newest story is. A feed can answer correctly, be perfectly "
           "formed, and carry a current date stamp while the newsroom behind it "
           "has stopped filing.</p>")
out.append("<p>Topic tags are keyword matches on the headline, so they are a "
           "sorting aid and not an editorial judgement. A story can carry "
           "several, and one that matches nothing is marked rather than forced "
           "into a category it does not belong in.</p>")
out.append("<p>Quiet thresholds are a first pass, set at roughly three times "
           "each source's own publishing rhythm from a single week of "
           "observation. They need one revision once a fortnight of real data "
           "sits behind them.</p>")
out.append("</footer>")

with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(out))

print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
print("Cherokee and Native: %d   regional and other: %d" % (len(native), len(other)))
print("topics: %s" % ", ".join("%s %d" % (k, v) for k, v in
                               sorted(tag_counts.items(), key=lambda kv: -kv[1])))
