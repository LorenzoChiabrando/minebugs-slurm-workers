import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

logger = logging.getLogger(__name__)

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "")
WORKER_TOKEN = os.environ.get("APP_WORKER_TOKEN", "")

# Configure a session with automatic retries
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)
session.mount('http://', HTTPAdapter(max_retries=retries))
session.mount('https://', HTTPAdapter(max_retries=retries))

def update_job(job_id: str, payload: dict) -> None:
    if not BACKEND_BASE_URL:
        logger.debug(f"BACKEND_BASE_URL not set — skipping callback for job {job_id}")
        return
    url = f"{BACKEND_BASE_URL}/api/mapping/internal/{job_id}"
    headers = {"X-Worker-Token": WORKER_TOKEN, "Content-Type": "application/json"}
    try:
        r = session.patch(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error updating backend job {job_id}: {e}")
        raise e