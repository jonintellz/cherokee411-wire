# Cherokee 411 wire

A news wire for the Cherokee Nation reservation and northeast Oklahoma. It polls regional
and Native newsroom feeds, removes duplicates, separates Cherokee and Native coverage from
everything else, and tags every story by topic.

It refreshes itself hourly in GitHub Actions and publishes through GitHub Pages, so the
links below are public, need no login, and keep working when nobody's computer is on.

## The links

| what | url |
|---|---|
| Everything, RSS | https://jonintellz.github.io/cherokee411-wire/cherokee411-all.xml |
| Cherokee and Native only, RSS | https://jonintellz.github.io/cherokee411-wire/cherokee411-native.xml |
| Readable page | https://jonintellz.github.io/cherokee411-wire/ |

Paste either RSS link into any reader. Feedly, Inoreader, NetNewsWire, Thunderbird and
Outlook all take a plain RSS URL.

## What it does and does not claim

The wire reports **what the sources published**, not what is true. It does not verify
stories, and a headline appearing here is not a second source for it.

Topic tags are assigned by keyword matching. They are for sorting a morning's reading, not
for counting. "General" is the fallback when nothing else matched.

Sources that stop publishing are reported as **gone quiet** rather than dropped silently, so
a feed that dies is visible instead of just being absent.

## How it is put together

- `tools/aggregate.py` polls the sources, deduplicates on link and on title, classifies
  Cherokee and Native coverage, and applies topic tags. Pure standard library, on purpose:
  it means the scheduled job needs no install step and cannot break on a dependency update.
- `tools/build_rss.py` writes RSS 2.0 with RFC 822 dates and stable guids.
- `tools/build_share_page.py` writes the readable page.
- `.github/workflows/refresh.yml` runs all three hourly and commits the result. It refuses
  to publish a feed that does not parse or that has no items, because a broken feed shows a
  subscriber nothing at all and gives no reason.

Set `C411_OUT` to change where output is written. It defaults to the workstation path used
in Intellz operations.

## Running it by hand

Actions tab, "Refresh the Cherokee 411 wire", Run workflow. Or locally:

```
python tools/aggregate.py
python tools/build_rss.py "https://jonintellz.github.io/cherokee411-wire"
python tools/build_share_page.py
```

Prepared by Tallmadge Holdings for Cherokee 411.
