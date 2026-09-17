# Operating on Render Starter (512 MB)

Start command: `env -u GUNICORN_CMD_ARGS gunicorn app:server -c gunicorn.conf.py --access-logfile -`.
Use the checked-in configuration: one worker, four request threads. Extra
workers each load their own dashboard, provider libraries and background jobs.

Render can inject `--preload` through `GUNICORN_CMD_ARGS`. Clear that inherited
option at startup: this application starts its updater when imported, so
preloading runs the updater in the master instead of the request worker.
That retains provider memory in the master, leaves worker health reporting
`starting`, and prevents worker recycling from recycling the updater.
The explicit access-log option preserves request logging.

## Memory safeguards

- A single three-thread provider pool survives refresh cycles. A timed-out job
  remains tracked; the next cycle reuses it instead of creating another copy.
- News, tariff and port consumers share one five-minute RSS snapshot. Only four
  RSS downloads run at once, with connect/read timeouts, elapsed-time checks
  between chunks, and a 2 MB decoded response limit before parsing XML.
- News and port cache regeneration are serialized. Gemini requests have a
  45-second deadline and no automatic retries.
- Gunicorn recycles its worker after 2,000–2,200 requests as a backstop for
  retained allocations. Versioned news caches survive worker restarts.

## Verification after deployment

The email establishes an out-of-memory restart; it does not identify its cause.
The stalled-worker and duplicate-download paths were found in code and covered
by failure tests. Production causality still needs Render metrics/logs.

Each refresh logs `memory` before and after aggregation. On Linux this contains
`rss_mb` (current resident memory), `peak_rss_mb` (process high-water mark), and
the Python thread count. `/health` also exposes these as `process_memory`.
RSS readings exclude the Gunicorn master and other container memory, so compare
them with Render's service-level Memory metric, not against 512 MB alone.

After deploying, check Render Metrics over 24–48 hours, including a cold start
and the daily AI refresh. Look for a stable baseline and peaks safely below the
instance limit. If healthy bounded workloads still approach 512 MB, a larger
instance or moving refresh jobs out of the web process is the next step; worker
recycling alone cannot fix a workload that exceeds the limit in one request.

References: [Render service metrics](https://render.com/docs/service-metrics)
and [Gunicorn worker recycling](https://docs.gunicorn.org/en/stable/settings.html#max-requests).
