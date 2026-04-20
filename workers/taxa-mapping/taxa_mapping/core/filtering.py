import logging
import pandas as pd
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def get_candidates_for_rescue(jaccard_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:

    logger.info("--- Step 01a: Filtering candidates for NCBI Rescue ---")

    if not jaccard_results:
        logger.warning("Input results are empty. Nothing to filter.")
        return []

    df = pd.DataFrame(jaccard_results)

    if "bands" not in df.columns:
        logger.error("Critical: Column 'bands' missing in Jaccard results. Cannot filter.")
        return jaccard_results

    initial_count = len(df)

    mask = df["bands"] != "auto-accept"
    subset_df = df[mask].copy()

    rescue_count = len(subset_df)

    if initial_count > 0:
        pct = (rescue_count / initial_count) * 100
        logger.info(f"Total Taxa: {initial_count}")
        logger.info(f"Auto-Accepted: {initial_count - rescue_count}")
        logger.info(f"Need Rescue: {rescue_count} ({pct:.1f}%)")

    if not subset_df.empty:
        breakdown = subset_df["bands"].value_counts().to_dict()
        logger.info(f"Rescue Breakdown: {breakdown}")

    else:
        logger.info("All taxa were auto-accepted! No NCBI Rescue needed.")

    return subset_df.to_dict(orient='records')