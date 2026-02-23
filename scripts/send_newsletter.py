"""
Daily Email Newsletter Script
=============================
This script fetches the latest global supply chain health index data from the local cache,
constructs an HTML email containing the overall score, health tier, and the AI-generated
daily briefing, and sends it to the configured recipient via SMTP.

Intended to be run via a daily cron job (e.g. Render Cron or Heroku Scheduler).

Configuration via Environment Variables:
- RECIPIENT_EMAIL: The email address to send the newsletter to.
- SMTP_SERVER: The SMTP server address (e.g., smtp.gmail.com).
- SMTP_PORT: The SMTP server port (default 587).
- SMTP_USERNAME: The SMTP username (e.g., your generic sender email).
- SMTP_PASSWORD: The SMTP password or app password.
- WEBSITE_URL: The URL to the live site (default: https://gscindex.com).
"""

import os
import smtplib
import logging
from email.message import EmailMessage
from datetime import datetime

# Adjust Python path if script is run directly from the scripts/ folder
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.cache import get_cached_dashboard
from scoring.engine import compute_composite_index, get_health_tier
from config import COLORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Newsletter")

def load_environment():
    """Load standard .env if present (useful for local testing)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

def generate_html_email(score: float, tier: dict, briefing: str, website_url: str) -> str:
    """Constructs the HTML body for the newsletter."""
    color = tier.get("color", "#ffffff")
    label = tier.get("label", "Unknown")
    
    # Format briefing bullet points
    # Briefing usually comes as a single string with newlines.
    bullet_points = ""
    for line in briefing.strip().split("\n"):
        line = line.strip()
        if line:
            # Strip markdown/unicode bullet characters so we can use real HTML bullets safely
            line = line.lstrip(" -*•").strip()
            bullet_points += f"<li style='margin-bottom: 12px; line-height: 1.6;'>{line}</li>"

    if not bullet_points:
        bullet_points = "<li>No briefing data available today.</li>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Global Supply Chain Daily Briefing</title>
    </head>
    <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #0f1117; color: #e1e4ea; margin: 0; padding: 20px;">
        
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 600px; margin: 0 auto; background-color: #1a1d26; border-radius: 8px; overflow: hidden; border: 1px solid #2a2d3a;">
            <!-- Header -->
            <tr>
                <td style="padding: 30px; border-bottom: 1px solid #2a2d3a; text-align: center;">
                    <h2 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Global Supply Chain Index</h2>
                    <p style="margin: 5px 0 0 0; color: #8a8f9e; font-size: 14px;">Daily Briefing &bull; {datetime.now().strftime('%B %d, %Y')}</p>
                </td>
            </tr>
            
            <!-- Health Score Section -->
            <tr>
                <td style="padding: 30px 30px 10px 30px; text-align: center;">
                    <h4 style="margin: 0 0 10px 0; color: #8a8f9e; text-transform: uppercase; font-size: 12px; letter-spacing: 1px;">Overall Health Score</h4>
                    <div style="font-size: 56px; font-weight: bold; color: {color}; margin: 0;">{score:.1f}</div>
                    <div style="display: inline-block; background-color: {color}; color: #000; padding: 4px 12px; border-radius: 12px; font-weight: bold; font-size: 14px; margin-top: 5px;">
                        {label}
                    </div>
                </td>
            </tr>

            <!-- Briefing Section -->
            <tr>
                <td style="padding: 20px 40px 30px 40px;">
                    <h3 style="color: #ffffff; font-size: 18px; margin-bottom: 15px; border-bottom: 1px solid #2a2d3a; padding-bottom: 10px;">Today's Key Developments</h3>
                    <ul style="padding-left: 20px; color: #d1d5db; font-size: 15px;">
                        {bullet_points}
                    </ul>
                </td>
            </tr>

            <!-- CTA Footer -->
            <tr>
                <td style="padding: 30px; background-color: #15171f; text-align: center; border-top: 1px solid #2a2d3a;">
                    <a href="{website_url}" style="display: inline-block; background-color: #6366f1; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: bold; font-size: 16px;">
                        View Full Dashboard
                    </a>
                    <p style="margin: 15px 0 0 0; color: #6b7280; font-size: 12px;">
                        This is an automated operational intelligence briefing.<br>
                        Data is aggregated and analyzed continuously.
                    </p>
                </td>
            </tr>
        </table>
        
    </body>
    </html>
    """
    return html


def generate_text_email(score: float, tier: dict, briefing: str, website_url: str) -> str:
    """Constructs the plain text fallback version."""
    label = tier.get("label", "Unknown")
    
    text = f"GLOBAL SUPPLY CHAIN INDEX - DAILY BRIEFING\\n"
    text += f"Date: {datetime.now().strftime('%B %d, %Y')}\\n"
    text += f"=========================================\\n\\n"
    
    text += f"Overall Health Score: {score:.1f}/100 ({label})\\n\\n"
    
    text += "TODAY'S KEY DEVELOPMENTS:\\n"
    for line in briefing.strip().split("\n"):
        line = line.strip()
        if line:
            line = line.lstrip(" -*•").strip()
            text += f"- {line}\\n"
                
    text += f"\\nView the full interactive dashboard here: {website_url}\\n"
    return text

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

    logger.info("Loading cached dashboard data...")
    data = get_cached_dashboard()
    
    if not data:
        logger.error("No cached dashboard data found. Cannot send newsletter.")
        return
        
    current_scores = data.get("current_scores", {})
    briefing = data.get("briefing", "")
    
    if not current_scores:
        logger.error("No current scores found in cache.")
        return
        
    # Filter out empty placeholder startup states
    if "loading live supply-chain news analysis" in briefing.lower():
        logger.warning("Briefing is in a placeholder state. The dashboard hasn't fully booted yet. Delaying newsletter.")
        return

    # Calculate overall score and tier
    score = compute_composite_index(current_scores)
    tier = get_health_tier(score)
    
    logger.info(f"Dashboard score computed: {score:.1f} ({tier.get('label')})")
    
    html_content = generate_html_email(score, tier, briefing, website_url)
    text_content = generate_text_email(score, tier, briefing, website_url)
    
    from data.database import get_active_subscribers
    subscribers = get_active_subscribers()
    
    # Always include the hardcoded recipient for testing/admin purposes
    if recipient and recipient not in subscribers:
        subscribers.append(recipient)
        
    if not subscribers:
        logger.info("No active subscribers found. Exiting.")
        return
    
    if args.dry_run:
        logger.info(f"DRY RUN MODE: Skipping actual SMTP dispatch.")
        logger.info(f"Would send to {len(subscribers)} subscribers: {subscribers}")
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
            
            for email in subscribers:
                try:
                    msg = EmailMessage()
                    msg["Subject"] = f"Global Supply Chain Update: {score:.1f}/100 ({tier.get('label')})"
                    msg["From"] = smtp_user if smtp_user else "no-reply@gscindex.com"
                    msg["To"] = email
                    
                    msg.set_content(text_content)
                    msg.add_alternative(html_content, subtype='html')
                    
                    server.send_message(msg)
                    successful_sends += 1
                except Exception as e:
                    logger.error(f"Failed to send to {email}: {e}")
                    failed_emails.append(f"{email} ({e})")
                    
            logger.info(f"Successfully sent {successful_sends}/{len(subscribers)} emails.")
            
            # --- Send Admin Summary Report ---
            if recipient:
                try:
                    admin_msg = EmailMessage()
                    admin_msg["Subject"] = f"GSC Config: Newsletter Dispatch Summary"
                    admin_msg["From"] = smtp_user if smtp_user else "no-reply@gscindex.com"
                    admin_msg["To"] = recipient
                    
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
