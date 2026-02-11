
import logging
from datetime import datetime
from data.ai_analyst import generate_briefing
from dotenv import load_dotenv

load_dotenv()

# Simulate a few articles for testing
articles = [
    {"id": 1, "title": "Port of Rotterdam faces heavy delays due to crane malfunction", "description": "Crane failure causes backlog."},
    {"id": 2, "title": "China-US trade tensions escalate with new tariffs", "description": "New tariffs imposed on steel imports."},
    {"id": 3, "title": "Suez Canal transit smooth after minor incident", "description": "Canal reopened quickly."}
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Starting briefing generation test...")
try:
    result = generate_briefing(articles)
    logger.info(f"Result: {result}")
except Exception as e:
    logger.error(f"Error: {e}")
