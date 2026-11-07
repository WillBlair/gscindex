"""
Daily Email Newsletter Script
=============================
This script fetches the index from the live site, writes the morning news briefing from fresh
public articles, and emails it to every active subscriber via SMTP. The email is the briefing
only; the subject carries the index and the button leads to the dashboard for everything else.

Intended to be run via a daily cron job (e.g. Render Cron or Heroku Scheduler).

Configuration via Environment Variables:
- RECIPIENT_EMAIL: The email address to send the newsletter to.
- SMTP_SERVER: The SMTP server address (e.g., smtp.gmail.com).
- SMTP_PORT: The SMTP server port (default 587).
- SMTP_USERNAME: The SMTP username (e.g., your generic sender email).
- SMTP_PASSWORD: The SMTP password or app password.
- WEBSITE_URL: The URL to the live site (default: https://gscindex.com).
- ADMIN_TOKEN: Bearer token for /api/v1/newsletter-data.
- NEWSLETTER_SECRET: Signs unsubscribe links (falls back to ADMIN_TOKEN).
- NEWSLETTER_POSTAL_ADDRESS: Sender postal address for the footer. CAN-SPAM
  requires one in commercial email; the run warns when it is missing.
"""

import os
import smtplib
import logging
import time
import html as html_utils
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

# Human-readable sender name shown in inbox previews.
SENDER_DISPLAY_NAME = "Global Supply Chain Index"

# Adjust Python path if script is run directly from the scripts/ folder
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.terminal_data import tier_for
from data.ai_analyst import generate_newsletter_stories
from data.cache import get_cached, set_cached
from data.news_selection import select_fresh_articles
from data.rss_fetcher import fetch_rss_articles
from data.unsubscribe import make_token

# The web service returns 503 for about a minute after a deploy or restart.
_API_ATTEMPTS = 5
_API_RETRY_SECONDS = 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Newsletter")

def load_environment():
    """Load standard .env if present (useful for local testing)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _fetch_dashboard_data(website_url: str, admin_token: str) -> dict | None:
    """Fetch dashboard data from the live web service API.

    The cron job runs as a separate Render service with its own empty
    filesystem, so it cannot read the web service's disk cache.  Instead
    we hit the ``/api/v1/newsletter-data`` endpoint which returns
    ``current_scores``, ``briefing``, and ``composite_index``.

    Falls back to local disk cache for local development / testing.
    """
    import json
    from urllib.error import HTTPError

    api_url = f"{website_url.rstrip('/')}/api/v1/newsletter-data"
    headers = {
        "User-Agent": "GSCIndex-Newsletter/1.0",
        "Authorization": f"Bearer {admin_token}",
    }
    for attempt in range(1, _API_ATTEMPTS + 1):
        logger.info("Fetching dashboard data from %s (attempt %d) ...", website_url, attempt)
        try:
            with urlopen(Request(api_url, headers=headers), timeout=30) as resp:
                data = json.loads(resp.read().decode())
            if "current_scores" in data:
                logger.info("Successfully fetched data from live API.")
                return data
            logger.warning("API returned unexpected payload: %s", list(data.keys()))
            break
        except HTTPError as e:
            if e.code != 503 or attempt == _API_ATTEMPTS:
                logger.warning("API fetch failed (HTTP %s).", e.code)
                break
            logger.info("Service warming up (503); retrying in %ds.", _API_RETRY_SECONDS)
            time.sleep(_API_RETRY_SECONDS)
        except URLError as e:
            logger.warning("Could not reach live API (%s).", e)
            break
        except Exception as e:
            logger.warning("API fetch failed (%s).", e)
            break
    logger.info("Trying local cache...")

    # Fallback: local disk cache (works in development)
    try:
        from data.cache import get_cached_dashboard
        from scoring.engine import snapshot_composite
        local_data = get_cached_dashboard()
        if local_data:
            from components.terminal_data import index_summary
            scores = local_data.get("current_scores", {})
            composite = snapshot_composite(local_data)
            change = index_summary(local_data, "global")["change"]
            return {
                "current_scores": scores,
                "briefing": local_data.get("briefing", ""),
                "composite_index": round(composite, 1) if composite is not None else None,
                "index_change": round(change, 1) if change is not None else None,
            }
    except Exception as e:
        logger.warning("Local cache fallback failed: %s", e)

    return None

def _daily_newsletter_cache_key(today: datetime) -> str:
    """Cache key scoped to one newsletter date so SMTP retries reuse the same stories."""
    run_date = today
    if run_date.tzinfo is None:
        run_date = run_date.replace(tzinfo=timezone.utc)
    return f"newsletter_stories_v1_{run_date.astimezone(timezone.utc).strftime('%Y_%m_%d')}"


def _stories_from_briefing(briefing: str) -> list[dict]:
    """The dashboard's briefing bullets as headline-less stories (fallback only)."""
    lines = [line.strip().lstrip(" -*•").strip() for line in str(briefing or "").splitlines()]
    return [{"headline": "", "summary": line, "source": "", "url": ""} for line in lines if line]


def _build_daily_stories(*, fallback_briefing: str, today: datetime | None = None) -> list[dict]:
    """The morning briefing's stories from fresh public articles, with a same-day retry cache."""
    run_date = today or datetime.now(timezone.utc)
    if run_date.tzinfo is None:
        run_date = run_date.replace(tzinfo=timezone.utc)
    run_date = run_date.astimezone(timezone.utc)

    cache_key = _daily_newsletter_cache_key(run_date)
    cached = get_cached(cache_key, ttl=36 * 3600)
    if cached and cached.get("stories"):
        logger.info("Using cached daily newsletter stories: %s", cache_key)
        return list(cached["stories"])

    try:
        articles = fetch_rss_articles(max_items=80)
        selected = select_fresh_articles(
            articles,
            now=run_date,
            max_items=24,
            fresh_hours=36,
            fallback_hours=72,
        )
        stories = generate_newsletter_stories(selected)
        if stories:
            set_cached(cache_key, {"stories": stories, "article_count": len(selected)})
        logger.info("Built %d newsletter stories from %d articles.", len(stories), len(selected))
        return stories or _stories_from_briefing(fallback_briefing)
    except Exception as exc:
        logger.warning("Fresh newsletter stories failed; using dashboard briefing: %s", exc)
        return _stories_from_briefing(fallback_briefing)


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


def _unsubscribe_url(website_url: str, email: str) -> str:
    return f"{website_url.rstrip('/')}/unsubscribe?t={make_token(email)}"


def _dashboard_url(website_url: str) -> str:
    """The email's dashboard link. utm_source=newsletter tells the site the visitor already
    subscribed (assets/terminal.js hides the sign-up bar) and tags the visit in analytics."""
    return f"{website_url.rstrip('/')}/?utm_source=newsletter&utm_campaign=daily"


MINUS = "−"
# Email palette: the site's Terminal colors (assets/terminal.css). Gmail ignores web fonts,
# so numbers use the system monospace stack.
PAGE, CARD, RULE, TEXT, DIM, AMBER = "#000000", "#07090C", "#1D232B", "#F2F4F7", "#8A94A3", "#FFB020"
MONO = "Menlo, Consolas, 'Courier New', monospace"
SANS = "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif"


def _signed(value: float) -> str:
    return "0.0" if round(value, 1) == 0 else f"{value:+.1f}".replace("-", MINUS)


def email_subject(score: float, tier: dict, change: float | None, stories: list[dict]) -> str:
    """Lead story first, then the index, so the subject changes every day."""
    index = f"Index {score:.1f} {tier.get('label', '')}".strip()
    if change is not None:
        index += f" ({_signed(change)})"
    lead = next((s["headline"] for s in stories or [] if s.get("headline")), "")
    return f"{lead} | {index}" if lead else f"Global Supply Chain Index: {index}"


def email_preheader(stories: list[dict]) -> str:
    """Inbox preview text: the next two headlines after the one in the subject."""
    headlines = [s["headline"] for s in stories or [] if s.get("headline")]
    return ". ".join(headlines[1:3]) + ("." if len(headlines) > 1 else "")


def _label(text: str) -> str:
    return (f'<div style="font-family:{MONO};font-size:11px;letter-spacing:1.5px;'
            f'text-transform:uppercase;color:{AMBER};margin:0 0 16px 0;">{text}</div>')


def _section(inner: str, pad: str = "24px 28px") -> str:
    return f'<tr><td style="padding:{pad};border-top:1px solid {RULE};">{inner}</td></tr>'


def _stories_html(stories: list[dict]) -> str:
    if not stories:
        return f'<p style="margin:0;font-size:15px;color:{DIM};">No fresh supply chain news cleared our filters this morning.</p>'
    out = ""
    for i, story in enumerate(stories):
        gap = "0" if i == len(stories) - 1 else "22px"
        headline = html_utils.escape(story.get("headline") or "")
        summary = html_utils.escape(story.get("summary") or "")
        url, source = story.get("url") or "", html_utils.escape(story.get("source") or "")
        link = (f' <a href="{html_utils.escape(url)}" style="color:{AMBER};text-decoration:underline;white-space:nowrap;">{source or "Source"}</a>'
                if url.startswith(("https://", "http://")) else "")
        head = (f'<div style="font-size:17px;line-height:1.35;font-weight:bold;color:{TEXT};margin:0 0 6px 0;">{headline}</div>'
                if headline else "")
        out += (f'<div style="margin:0 0 {gap} 0;">{head}'
                f'<div style="font-size:15px;line-height:1.6;color:#C9CED6;">{summary}{link}</div></div>')
    return out


def generate_html_email(
    stories: list[dict],
    website_url: str,
    unsubscribe_url: str = "",
    postal_address: str = "",
) -> str:
    """The email is the news briefing; the button leads to the dashboard for the index."""
    site = website_url.split("?")[0].rstrip("/")
    footer = [
        f'Forwarded this? <a href="{site}/?utm_source=forward" style="color:{TEXT};">Sign up free</a> for the daily email.',
    ]
    last = []
    if unsubscribe_url:
        last.append(f'<a href="{html_utils.escape(unsubscribe_url)}" style="color:{DIM};">Unsubscribe</a>')
    if postal_address:
        last.append(html_utils.escape(postal_address))
    if last:
        footer.append(" · ".join(last))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><title>Global Supply Chain Index</title></head>
<body style="margin:0;padding:0;background:{PAGE};" bgcolor="{PAGE}">
<div style="display:none;max-height:0;overflow:hidden;">{html_utils.escape(email_preheader(stories))}</div>
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAGE}" style="background:{PAGE};"><tr><td align="center" style="padding:24px 12px;">
<table width="600" cellpadding="0" cellspacing="0" border="0" bgcolor="{CARD}" style="width:100%;max-width:600px;background:{CARD};border:1px solid {RULE};font-family:{SANS};">
  <tr><td style="padding:18px 28px;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="font-family:{MONO};font-size:12px;letter-spacing:1.5px;font-weight:bold;color:{AMBER};">GLOBAL SUPPLY CHAIN INDEX</td>
      <td align="right" style="font-size:12px;color:{DIM};white-space:nowrap;">{datetime.now(timezone.utc).strftime('%b %-d, %Y')}</td>
    </tr></table>
  </td></tr>
  {_section(_label("Today's briefing") + _stories_html(stories), "26px 28px")}
  <tr><td align="center" style="padding:24px 28px 28px 28px;border-top:1px solid {RULE};">
    <a href="{html_utils.escape(website_url)}" style="display:inline-block;background:{AMBER};color:#000000;font-family:{MONO};font-size:14px;font-weight:bold;letter-spacing:1px;text-decoration:none;padding:14px 28px;">SEE TODAY'S INDEX</a>
  </td></tr>
  <tr><td style="padding:20px 28px;border-top:1px solid {RULE};font-size:12px;line-height:1.6;color:{DIM};">{"<br>".join(footer)}</td></tr>
</table>
</td></tr></table>
</body></html>"""


def generate_text_email(
    stories: list[dict],
    website_url: str,
    unsubscribe_url: str = "",
    postal_address: str = "",
) -> str:
    """Plain text version of the briefing."""
    site = website_url.split("?")[0].rstrip("/")
    lines = [f"GLOBAL SUPPLY CHAIN INDEX, {datetime.now(timezone.utc).strftime('%b %-d, %Y')}", "", "TODAY'S BRIEFING", ""]
    for story in stories or []:
        if story.get("headline"):
            lines.append(story["headline"])
        lines.append(story.get("summary", ""))
        if story.get("url"):
            lines.append(f"{story.get('source') or 'Source'}: {story['url']}")
        lines.append("")
    if not stories:
        lines += ["No fresh supply chain news cleared our filters this morning.", ""]
    lines += [f"See today's index: {website_url}", "",
              f"Forwarded this? Sign up free: {site}/?utm_source=forward"]
    if unsubscribe_url:
        lines.append(f"Unsubscribe: {unsubscribe_url}")
    if postal_address:
        lines.append(postal_address)
    return "\n".join(lines) + "\n"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Send Daily Supply Chain Newsletter")
    parser.add_argument("--dry-run", action="store_true", help="Print the email content instead of sending")
    args = parser.parse_args()

    load_environment()
    
    recipient = os.environ.get("RECIPIENT_EMAIL")
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = os.environ.get("SMTP_PORT", 587)
    smtp_user = os.environ.get("SMTP_USERNAME")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    website_url = os.environ.get("WEBSITE_URL", "https://gscindex.com")

    if not args.dry_run and not all([smtp_server, smtp_user, smtp_pass]):
        logger.error("Missing required SMTP environment variables. Please check .env or deployment vars.")
        logger.error(f"Provided: server={bool(smtp_server)}, user={bool(smtp_user)}, pass={bool(smtp_pass)}")
        logger.error("Optional: recipient=%s (admin fallback)", bool(recipient))
        return

    from data.database import init_db
    init_db()

    admin_token = os.environ.get("ADMIN_TOKEN", "")
    data = _fetch_dashboard_data(website_url, admin_token)

    if not data:
        logger.error("Could not fetch dashboard data from API or local cache. Cannot send newsletter.")
        return

    current_scores = data.get("current_scores", {})
    briefing = data.get("briefing", "")

    if not current_scores:
        logger.error("No current scores found in data.")
        return

    # Filter out empty placeholder startup states
    if "loading live supply-chain news analysis" in briefing.lower():
        logger.warning("Briefing is in a placeholder state. The dashboard hasn't fully booted yet. Delaying newsletter.")
        return

    # Use pre-computed score from API if available, otherwise compute locally
    score = data.get("composite_index")
    if score is None:
        from scoring.engine import snapshot_composite
        score = snapshot_composite({"current_scores": current_scores})
    if score is None:
        logger.error("No composite available (a weighted category is missing). Not sending.")
        return
    tier = tier_for(score)
    change = data.get("index_change")

    logger.info(f"Dashboard score: {score:.1f} ({tier.get('label')})")
    stories = _build_daily_stories(fallback_briefing=briefing)

    postal_address = os.environ.get("NEWSLETTER_POSTAL_ADDRESS", "").strip()
    if not postal_address:
        logger.warning(
            "NEWSLETTER_POSTAL_ADDRESS is not set. CAN-SPAM requires a postal address "
            "in commercial email; set it in the cron service's environment."
        )

    from data.database import (
        get_active_subscribers,
        get_db_type,
        get_sent_today,
        record_newsletter_send,
    )
    subscribers = get_active_subscribers()
    logger.info(
        "Database backend: %s | Active subscribers from DB: %d",
        get_db_type(),
        len(subscribers),
    )
    
    # Always include the hardcoded recipient for testing/admin purposes
    if recipient and recipient not in subscribers:
        subscribers.append(recipient)
        
    if not subscribers:
        logger.warning(
            "No active subscribers found (DB returned 0 and no RECIPIENT_EMAIL set). "
            "Verify that DATABASE_URL points to Neon and contains subscriber rows."
        )
        return
    
    send_date = datetime.now(timezone.utc).date()
    already_sent = get_sent_today(send_date)
    if already_sent:
        logger.info("Skipping %d subscriber(s) already sent today.", len(already_sent))
    subscribers = [email for email in subscribers if email not in already_sent]
    if not subscribers:
        logger.info("Everyone has already received today's newsletter.")
        return

    if args.dry_run:
        sample = subscribers[0]
        text_content = generate_text_email(
            stories, _dashboard_url(website_url), _unsubscribe_url(website_url, sample), postal_address
        )
        html_content = generate_html_email(
            stories, _dashboard_url(website_url), _unsubscribe_url(website_url, sample), postal_address
        )
        logger.info("DRY RUN MODE: Skipping actual SMTP dispatch.")
        print("Subject:", email_subject(score, tier, change, stories))
        logger.info(
            "Would send to %d subscribers: %s",
            len(subscribers),
            ", ".join(_mask_email(e) for e in subscribers),
        )
        print("-" * 50)
        print("--- Text Version ---")
        print(text_content)
        print("--- HTML Version (truncate 500 chars) ---")
        print(html_content[:500] + "...\n")
        return

    try:
        logger.info(f"Connecting to SMTP server at {smtp_server}:{smtp_port}...")
        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            
            logger.info(f"Dispatching emails to {len(subscribers)} subscribers...")
            successful_sends = 0
            failed_emails = []
            
            sender_addr = smtp_user or "no-reply@gscindex.com"
            from_header = formataddr((SENDER_DISPLAY_NAME, sender_addr))

            for email in subscribers:
                try:
                    unsubscribe_url = _unsubscribe_url(website_url, email)
                    text_content = generate_text_email(
                        stories, _dashboard_url(website_url), unsubscribe_url, postal_address
                    )
                    html_content = generate_html_email(
                        stories, _dashboard_url(website_url), unsubscribe_url, postal_address
                    )
                    msg = EmailMessage()
                    msg["Subject"] = email_subject(score, tier, change, stories)
                    msg["From"] = from_header
                    msg["To"] = email

                    # ── Deliverability headers ──────────────────────
                    # Unique ID prevents duplicate-detection filters.
                    msg["Message-ID"] = make_msgid(domain="gscindex.com")
                    # Gmail and Yahoo require one-click unsubscribe (RFC 8058).
                    msg["List-Unsubscribe"] = (
                        f"<{unsubscribe_url}>, <mailto:{sender_addr}?subject=unsubscribe>"
                    )
                    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
                    # Signals legitimate bulk mail to receiving servers.
                    msg["Precedence"] = "bulk"

                    msg.set_content(text_content)
                    msg.add_alternative(html_content, subtype='html')
                    
                    server.send_message(msg)
                    record_newsletter_send(send_date, email)
                    successful_sends += 1
                except Exception as e:
                    logger.error("Failed to send to %s: %s", _mask_email(email), e)
                    failed_emails.append(f"{email} ({e})")
                    
            logger.info(f"Successfully sent {successful_sends}/{len(subscribers)} emails.")
            
            # --- Send Admin Summary Report ---
            if recipient:
                try:
                    admin_msg = EmailMessage()
                    admin_msg["Subject"] = "GSC Config: Newsletter Dispatch Summary"
                    admin_msg["From"] = from_header
                    admin_msg["To"] = recipient
                    admin_msg["Message-ID"] = make_msgid(domain="gscindex.com")
                    
                    summary_text = (
                        f"Newsletter Dispatch Summary\n"
                        f"===========================\n\n"
                        f"Total Subscribers Attempted: {len(subscribers)}\n"
                        f"Successful Sends: {successful_sends}\n"
                        f"Failed Sends: {len(failed_emails)}\n\n"
                    )
                    
                    if failed_emails:
                        summary_text += "Failures:\n"
                    for f in failed_emails:
                        summary_text += f"- {f}\n"
                        
                    admin_msg.set_content(summary_text)
                    server.send_message(admin_msg)
                    logger.info("Admin summary report sent successfully.")
                except Exception as e:
                    logger.error(f"Failed to send admin summary report: {e}")
                    
    except Exception as e:
        logger.error(f"Failed to connect or configure SMTP session: {e}")

if __name__ == "__main__":
    main()
