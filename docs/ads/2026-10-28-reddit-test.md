# Reddit ads test, October 2026

Goal: find out what one newsletter signup costs on Reddit before spending more. Budget: $100 over 7 days, approved by Will on 2026-10-28.

## Campaign settings

- Objective: Traffic (clicks to the site). No Reddit pixel; signups are counted from our own database.
- Budget: $14 a day for 7 days ($98). Automatic bidding.
- Locations: United States, Canada, United Kingdom, Australia.
- Devices: all.
- Communities: r/supplychain, r/logistics, r/procurement, r/shipping, r/Freight, r/economics, r/investing, r/stocks, r/semiconductors, r/aerospace.
- One ad group, three ads (below). Each ad links to its own URL so signups can be traced to it.

## Ads

All three sell the daily email (score, tier and a short news briefing, sent once a day at 15:00 UTC). Images: `docs/ads/reddit-square-2026-10-28.png` (1080x1080, mobile feed) and `docs/ads/reddit-wide-2026-10-28.png` (1200x628, desktop). Upload both if Reddit asks for more than one size. They show the real 28 Oct score (46.5, Stressed) and three lines from that day's briefing; redraw with `scripts/make_ad_images.py` for a later run. Call to action button: Sign Up.

**Ad A: "best" claim (Will's pick)**
Headline: The best free daily briefing on global supply chains: a 0 to 100 health score and the day's main news, in your inbox every day.
URL: `https://gscindex.com/briefing?utm_source=reddit&utm_campaign=brief-best`
Risk: "best" has no proof behind it yet, and Reddit ads take comments.

**Ad B: chokepoints hook**
Headline: Red Sea, Hormuz, Panama, tariffs, diesel prices. One free email a day scores how global supply chains are holding up and sums up the news behind it.
URL: `https://gscindex.com/briefing?utm_source=reddit&utm_campaign=brief-chokepoints`

**Ad C: data hook**
Headline: Get global supply chain stress as a number every day: a 0 to 100 score built from NY Fed, IMF and Federal Reserve data, with a short briefing on the news. Free, unsubscribe anytime.
URL: `https://gscindex.com/briefing?utm_source=reddit&utm_campaign=brief-data`

## How we judge it

- After 3 days: pause any ad whose click-through rate is far below the other two.
- After 7 days: cost per signup = Reddit spend / signups with a `reddit/` source.

```sql
SELECT source, COUNT(*) FROM subscribers WHERE source LIKE 'reddit/%' GROUP BY source;
```

- Also check Cloudflare Web Analytics for visits from reddit.com and whether ad visitors return in later days.
- Scale only if the cost per signup is one Will is happy to pay. Any spend beyond the $100 needs his approval first.
