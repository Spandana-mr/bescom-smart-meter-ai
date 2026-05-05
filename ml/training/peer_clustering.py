"""
data-pipeline/preprocessing/peer_clustering.py

Monthly batch job: Dynamic peer grouping via Spectral Clustering on DTW distances.
Assigns peer_cluster_id to each meter in meter_registry.

Paper reference: Novel contribution — spectral clustering on DTW distance matrix
provides far better peer groups than static tariff-category grouping.

Usage:
    python peer_clustering.py --n-clusters auto --sample-size 50000
"""

import os
import numpy as np
import pandas as pd
import psycopg2
from loguru import logger
from sklearn.cluster import SpectralClustering
from sklearn.preprocessing import StandardScaler
from tslearn.metrics import cdist_dtw
from tslearn.preprocessing import TimeSeriesScalerMeanVariance
import mlflow
from datetime import datetime, timedelta


# ─── Config ───────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host":     os.getenv("TIMESCALE_HOST", "localhost"),
    "port":     int(os.getenv("TIMESCALE_PORT", 5432)),
    "dbname":   os.getenv("TIMESCALE_DB", "bescom_meters"),
    "user":     os.getenv("TIMESCALE_USER", "bescom"),
    "password": os.getenv("TIMESCALE_PASSWORD", ""),
}

LOOKBACK_DAYS     = 30      # days of profile to use for clustering
N_CLUSTERS_AUTO   = True    # use eigengap heuristic to find k
N_CLUSTERS_FIXED  = 20      # fallback if auto fails
MAX_METERS_SAMPLE = 50_000  # sample for DTW computation (memory bound)
BATCH_SIZE        = 5_000   # process meters in batches for DTW


# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_meter_profiles(conn, end_date: str, lookback_days: int = 30) -> pd.DataFrame:
    """
    Load 30-day daily consumption profiles per meter (96 × 30 = 2880 readings per meter).
    Pivot to wide format: each row = 1 meter, each column = 1 timestamp slot.
    """
    start_date = (datetime.fromisoformat(end_date) - timedelta(days=lookback_days)).date()

    query = f"""
        SELECT
            smr.meter_id,
            mr.tariff_category,
            mr.consumer_type,
            date_trunc('hour', smr.timestamp) AS hour_slot,
            AVG(smr.kwh) AS avg_kwh
        FROM smart_meter_readings smr
        JOIN meter_registry mr ON smr.meter_id = mr.meter_id
        WHERE smr.timestamp >= '{start_date}'
          AND smr.timestamp < '{end_date}'
          AND smr.is_imputed = FALSE
          AND mr.is_active = TRUE
        GROUP BY smr.meter_id, mr.tariff_category, mr.consumer_type, hour_slot
        ORDER BY smr.meter_id, hour_slot
    """

    logger.info(f"Loading meter profiles from {start_date} to {end_date}...")
    df = pd.read_sql(query, conn)
    logger.info(f"Loaded {df['meter_id'].nunique():,} meters, {len(df):,} rows")
    return df


def pivot_to_profiles(df: pd.DataFrame) -> tuple[np.ndarray, list]:
    """Pivot to (n_meters, n_timesteps) matrix. Returns array + ordered meter IDs."""
    pivot = df.pivot_table(
        index="meter_id", columns="hour_slot", values="avg_kwh", aggfunc="mean"
    ).fillna(0)

    meter_ids = list(pivot.index)
    profiles  = pivot.values.astype(np.float32)

    # Normalize per meter (remove scale differences, keep shape)
    scaler = TimeSeriesScalerMeanVariance()
    profiles_3d = profiles.reshape(len(profiles), profiles.shape[1], 1)
    profiles_normalized = scaler.fit_transform(profiles_3d).squeeze(-1)

    logger.info(f"Profile matrix: {profiles_normalized.shape}")
    return profiles_normalized, meter_ids


# ─── Eigengap Heuristic ───────────────────────────────────────────────────────

def find_optimal_k(affinity_matrix: np.ndarray, k_max: int = 40) -> int:
    """
    Eigengap heuristic: find k where eigenvalue gap is largest.
    Robust way to auto-detect number of clusters.
    """
    from scipy.linalg import eigh
    from scipy.sparse.csgraph import laplacian

    L = laplacian(affinity_matrix, normed=True)
    eigenvalues, _ = eigh(L, subset_by_index=[0, k_max])
    eigenvalues = np.sort(eigenvalues)

    gaps = np.diff(eigenvalues)
    k_optimal = int(np.argmax(gaps) + 1)  # +1 because we need n_clusters not index
    k_optimal = max(5, min(k_optimal, k_max))   # clamp to [5, k_max]

    logger.info(f"Eigengap heuristic: optimal k = {k_optimal}")
    logger.info(f"Top gaps: {sorted(enumerate(gaps), key=lambda x: -x[1])[:5]}")
    return k_optimal


# ─── Clustering ───────────────────────────────────────────────────────────────

def compute_dtw_affinity(profiles: np.ndarray, sample_idx: np.ndarray) -> np.ndarray:
    """
    Compute DTW distance matrix for a sample of meters.
    Returns affinity (similarity) matrix: A = exp(-D / gamma).
    Memory note: 50k × 50k float32 = ~10GB. Use batching for large populations.
    """
    logger.info(f"Computing DTW distance matrix for {len(sample_idx)} meters...")

    # Take sample
    sample_profiles = profiles[sample_idx]

    # Batch-compute DTW distances
    dist_matrix = cdist_dtw(
        sample_profiles,
        sample_profiles,
        n_jobs=-1,
        verbose=1
    )

    # Convert to affinity using Gaussian kernel
    sigma = np.percentile(dist_matrix[dist_matrix > 0], 50)  # median non-zero dist
    affinity = np.exp(-dist_matrix ** 2 / (2 * sigma ** 2))

    logger.info(f"DTW affinity matrix computed. Shape: {affinity.shape}")
    return affinity


def run_spectral_clustering(affinity: np.ndarray, n_clusters: int) -> np.ndarray:
    """Fit SpectralClustering on precomputed affinity matrix."""
    logger.info(f"Running SpectralClustering with k={n_clusters}...")
    sc = SpectralClustering(
        n_clusters=n_clusters,
        affinity="precomputed",
        n_init=10,
        random_state=42,
        n_jobs=-1
    )
    labels = sc.fit_predict(affinity)
    logger.info(f"Cluster distribution:\n{np.bincount(labels)}")
    return labels


# ─── Assign Remaining Meters (KNN from cluster centroids) ────────────────────

def assign_all_meters_to_clusters(
    all_profiles: np.ndarray,
    sample_idx: np.ndarray,
    sample_labels: np.ndarray
) -> np.ndarray:
    """
    For meters not in sample, assign to nearest cluster centroid
    using Euclidean distance (DTW too slow for full assignment).
    """
    n_clusters = sample_labels.max() + 1

    # Compute centroids from sampled profiles
    centroids = np.array([
        all_profiles[sample_idx[sample_labels == k]].mean(axis=0)
        for k in range(n_clusters)
    ])

    # Assign all meters to nearest centroid
    all_labels = np.zeros(len(all_profiles), dtype=int)
    for i, profile in enumerate(all_profiles):
        dists = np.linalg.norm(centroids - profile, axis=1)
        all_labels[i] = np.argmin(dists)

    return all_labels


# ─── Write Results ────────────────────────────────────────────────────────────

def update_cluster_assignments(conn, meter_ids: list, labels: np.ndarray):
    """Update peer_cluster_id in meter_registry."""
    with conn.cursor() as cur:
        for meter_id, cluster_id in zip(meter_ids, labels):
            cur.execute(
                "UPDATE meter_registry SET peer_cluster_id = %s, updated_at = NOW() WHERE meter_id = %s",
                (int(cluster_id), meter_id)
            )
    conn.commit()
    logger.info(f"Updated {len(meter_ids):,} meter cluster assignments.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(n_clusters_override: int = None, sample_size: int = MAX_METERS_SAMPLE):
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))

    with mlflow.start_run(run_name=f"peer_clustering_{datetime.now().strftime('%Y%m%d')}"):
        conn = psycopg2.connect(**DB_CONFIG)

        end_date = datetime.now().strftime("%Y-%m-%d")
        df = load_meter_profiles(conn, end_date=end_date)

        profiles, meter_ids = pivot_to_profiles(df)
        n_meters = len(meter_ids)
        mlflow.log_param("n_meters_total", n_meters)
        mlflow.log_param("lookback_days", LOOKBACK_DAYS)

        # Sample for DTW computation
        sample_size = min(sample_size, n_meters)
        rng = np.random.default_rng(seed=42)
        sample_idx = rng.choice(n_meters, size=sample_size, replace=False)

        # Compute affinity matrix on sample
        affinity = compute_dtw_affinity(profiles, sample_idx)

        # Determine k
        if n_clusters_override:
            k = n_clusters_override
        elif N_CLUSTERS_AUTO:
            k = find_optimal_k(affinity, k_max=40)
        else:
            k = N_CLUSTERS_FIXED

        mlflow.log_param("n_clusters", k)

        # Cluster sample
        sample_labels = run_spectral_clustering(affinity, n_clusters=k)

        # Assign all meters
        all_labels = assign_all_meters_to_clusters(profiles, sample_idx, sample_labels)

        # Log cluster stats
        unique, counts = np.unique(all_labels, return_counts=True)
        mlflow.log_metric("n_clusters_actual", len(unique))
        mlflow.log_metric("cluster_size_mean", float(counts.mean()))
        mlflow.log_metric("cluster_size_std",  float(counts.std()))

        # Write to DB
        update_cluster_assignments(conn, meter_ids, all_labels)
        conn.close()

        logger.success(
            f"✓ Peer clustering complete. {n_meters:,} meters → {k} clusters."
        )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-clusters", type=int, default=None, help="Override auto k detection")
    parser.add_argument("--sample-size", type=int, default=MAX_METERS_SAMPLE)
    args = parser.parse_args()

    main(n_clusters_override=args.n_clusters, sample_size=args.sample_size)
