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

Image for all three: `docs/ads/reddit-card-2026-10-28.png` (today's share card, 1200x630). Call to action button: Learn More.

**Ad A**
Headline: A free daily 0 to 100 score for global supply chain health, built from NY Fed, IMF and Federal Reserve data. It covers chokepoints, energy, tariffs and freight.
URL: `https://gscindex.com/?utm_source=reddit&utm_campaign=test-a`

**Ad B**
Headline: How are the Red Sea, Hormuz and Panama doing today? We track ship transits through 8 chokepoints every day, along with energy prices, tariffs and freight. The site is free.
URL: `https://gscindex.com/?utm_source=reddit&utm_campaign=test-b`

**Ad C**
Headline: A daily score for supply chain stress, built from published data, with a live map of 37 major ports. There's a free daily briefing by email if you want it.
URL: `https://gscindex.com/?utm_source=reddit&utm_campaign=test-c`

## How we judge it

- After 3 days: pause any ad whose click-through rate is far below the other two.
- After 7 days: cost per signup = Reddit spend / signups with a `reddit/` source.

```sql
SELECT source, COUNT(*) FROM subscribers WHERE source LIKE 'reddit/%' GROUP BY source;
```

- Also check Cloudflare Web Analytics for visits from reddit.com and whether ad visitors return in later days.
- Scale only if the cost per signup is one Will is happy to pay. Any spend beyond the $100 needs his approval first.
