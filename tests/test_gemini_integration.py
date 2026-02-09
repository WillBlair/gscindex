"""
Test Gemini API Integration
============================
Generates and displays data for map points to verify the Gemini API is working.

Run with: python tests/test_gemini_integration.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


def check_gemini_api_key() -> bool:
    """Check if Gemini API key is configured."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        logger.info("✓ GEMINI_API_KEY found (starts with: %s...)", key[:10])
        return True
    logger.error("✗ GEMINI_API_KEY not found in environment")
    return False


def test_port_summaries() -> dict[str, str]:
    """Generate AI-powered port summaries via Gemini."""
    logger.info("=" * 60)
    logger.info("TESTING: Port Summaries via Gemini API")
    logger.info("=" * 60)
    
    from data.port_analyst import generate_port_summaries
    from data.ports_data import MAJOR_PORTS
    
    logger.info("Requesting AI summaries for %d ports...", len(MAJOR_PORTS))
    
    start = datetime.now()
    summaries = generate_port_summaries()
    elapsed = (datetime.now() - start).total_seconds()
    
    if summaries:
        logger.info("✓ Successfully generated %d port summaries in %.2fs", len(summaries), elapsed)
        
        # Display first 5 samples
        logger.info("\n┌─ Sample Port Summaries ─────────────────────────────")
        for i, (port, summary) in enumerate(list(summaries.items())[:5]):
            logger.info("│ %s:", port)
            logger.info("│   → %s", summary)
        logger.info("└─────────────────────────────────────────────────────\n")
        return summaries
    else:
        logger.warning("✗ No port summaries returned (check API key or rate limits)")
        return {}


def test_news_analysis() -> tuple[dict, str]:
    """Test news analysis and briefing generation via Gemini."""
    logger.info("=" * 60)
    logger.info("TESTING: News Analysis via Gemini API")
    logger.info("=" * 60)
    
    from data.providers.geopolitical import fetch_supply_chain_news
    
    start = datetime.now()
    news_score, alerts, briefing = fetch_supply_chain_news()
    elapsed = (datetime.now() - start).total_seconds()
    
    logger.info("✓ News analysis complete in %.2fs", elapsed)
    logger.info("  • Geopolitical score: %.1f", news_score)
    logger.info("  • Articles analyzed: %d", len(alerts))
    
    if briefing:
        logger.info("\n┌─ AI Daily Briefing ─────────────────────────────────")
        for line in briefing.split('\n'):
            if line.strip():
                logger.info("│ %s", line)
        logger.info("└─────────────────────────────────────────────────────\n")
    else:
        logger.warning("  • No briefing generated")
    
    # Show sample alerts
    if alerts:
        logger.info("┌─ Sample Alerts ─────────────────────────────────────")
        for alert in alerts[:3]:
            title = alert.get("title", "No title")[:60]
            severity = alert.get("severity", "unknown")
            sentiment = alert.get("sentiment", 0)
            logger.info("│ [%s] %s (sentiment: %.2f)", severity.upper(), title, sentiment)
        logger.info("└─────────────────────────────────────────────────────\n")
    
    return {"score": news_score, "alerts": len(alerts)}, briefing


def test_map_marker_generation() -> list[dict]:
    """Test full map marker generation with all data sources."""
    logger.info("=" * 60)
    logger.info("TESTING: Full Map Marker Generation")
    logger.info("=" * 60)
    
    from data.aggregator import aggregate_data
    
    start = datetime.now()
    data = aggregate_data()
    elapsed = (datetime.now() - start).total_seconds()
    
    markers = data.get("map_markers", [])
    errors = data.get("provider_errors", {})
    
    logger.info("✓ Full aggregation complete in %.2fs", elapsed)
    logger.info("  • Map markers generated: %d", len(markers))
    logger.info("  • Provider errors: %d", len(errors))
    
    if errors:
        logger.warning("  Provider Errors:")
        for cat, err in errors.items():
            logger.warning("    • %s: %s", cat, err)
    
    # Show marker samples
    if markers:
        logger.info("\n┌─ Sample Map Markers ─────────────────────────────────")
        for marker in markers[:5]:
            name = marker.get("name")
            score = marker.get("score", 0)
            lat, lon = marker.get("lat", 0), marker.get("lon", 0)
            desc_preview = marker.get("description", "")[:80].replace("<br>", " | ")
            
            # Determine health emoji
            if score >= 80:
                emoji = "🟢"
            elif score >= 60:
                emoji = "🟡"
            elif score >= 40:
                emoji = "🟠"
            else:
                emoji = "🔴"
            
            logger.info("│ %s %s (%.2f, %.2f) → Score: %.0f", emoji, name, lat, lon, score)
            logger.info("│   %s...", desc_preview)
        logger.info("└─────────────────────────────────────────────────────\n")
    
    return markers


def save_test_output(port_summaries: dict, markers: list) -> None:
    """Save test output to JSON for inspection."""
    output_path = Path(__file__).parent / "gemini_test_output.json"
    
    output = {
        "generated_at": datetime.now().isoformat(),
        "port_summaries": port_summaries,
        "map_markers_count": len(markers),
        "sample_markers": markers[:10] if markers else [],
    }
    
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    logger.info("✓ Test output saved to: %s", output_path)


def main() -> int:
    """Run all Gemini integration tests."""
    logger.info("╔════════════════════════════════════════════════════════════╗")
    logger.info("║       GEMINI API INTEGRATION TEST                          ║")
    logger.info("║       Global Supply Chain Index Dashboard                  ║")
    logger.info("╚════════════════════════════════════════════════════════════╝\n")
    
    # Check API key first
    if not check_gemini_api_key():
        logger.error("\nCannot proceed without GEMINI_API_KEY.")
        logger.error("Please set it in your .env file.")
        return 1
    
    print()  # Visual separator
    
    # Test 1: Port Summaries
    port_summaries = test_port_summaries()
    
    # Test 2: News Analysis
    news_result, briefing = test_news_analysis()
    
    # Test 3: Full Map Marker Generation
    markers = test_map_marker_generation()
    
    # Save output
    save_test_output(port_summaries, markers)
    
    # Summary
    logger.info("╔════════════════════════════════════════════════════════════╗")
    logger.info("║                    TEST SUMMARY                            ║")
    logger.info("╚════════════════════════════════════════════════════════════╝")
    logger.info("  Port Summaries: %s", "✓ OK" if port_summaries else "✗ FAILED")
    logger.info("  News Analysis:  %s", "✓ OK" if news_result.get("alerts", 0) > 0 else "✗ FAILED")
    logger.info("  Briefing:       %s", "✓ OK" if briefing else "✗ FAILED")
    logger.info("  Map Markers:    %s", "✓ OK" if markers else "✗ FAILED")
    
    all_ok = bool(port_summaries and news_result.get("alerts") and markers)
    
    if all_ok:
        logger.info("\n🎉 All Gemini integrations are working correctly!\n")
        return 0
    else:
        logger.warning("\n⚠️ Some tests failed. Check the logs above for details.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
