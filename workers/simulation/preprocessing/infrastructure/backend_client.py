import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

# Configure a session with automatic retries
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)
session.mount('http://', HTTPAdapter(max_retries=retries))
session.mount('https://', HTTPAdapter(max_retries=retries))

def update_simulation_status(
        simulation_id: str,
        status: str,
        result_path: Optional[str] = None,
        error_message: Optional[str] = None
) -> None:

    url = f"{settings.backend_url}/api/simulation/internal/{simulation_id}"

    headers = {
        "X-Worker-Token": settings.worker_token,
        "Content-Type": "application/json"
    }

    payload = {
        "status": status,
        "resultFilePath": result_path,
        "errorMessage": error_message
    }

    try:
        logger.info(f"Updating Backend Job {simulation_id} -> {status} at {url}")

        response = session.patch(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()

    except requests.exceptions.HTTPError as http_err:
        if http_err.response.status_code == 404:
            logger.warning(f"Simulation {simulation_id} returned 404. It might have been deleted or rolled back. Ignoring.")
        elif http_err.response.status_code == 403:
            logger.critical(f"Worker Token rejected! Check APP_WORKER_TOKEN in env.")
            raise http_err
        else:
            logger.error(f"Failed to update backend status for simulation {simulation_id}: {http_err}")
            raise http_err
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error updating backend status for simulation {simulation_id}: {e}")
        raise e