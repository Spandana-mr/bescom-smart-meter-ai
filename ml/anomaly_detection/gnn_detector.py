"""
ml/anomaly_detection/gnn_detector.py

EnergyGNN — Graph Attention Network for topology-aware Non-Technical Loss detection.
P3 reference: Pereira et al., IEEE Transactions on Smart Grid, 2022.
  "Non-Technical Loss Detection in Power Grids Using Graph Neural Networks"
  Shows 15-20% F1 improvement over meter-level detection alone.

Architecture:
  - Nodes: meters (features = 32-dim embedding from VAE encoder)
  - Edges: physical feeder connections (meter → transformer → feeder)
  - GAT with 2 layers → dual heads: node-level anomaly + feeder balance violation

Training signal: SELF-SUPERVISED using feeder energy balance physics.
  No theft labels needed initially. Feeder loss > 8% = positive supervision.

CRITICAL: Deploy ONLY after topology audit completion (3-month delay from Phase 1).
"""

import os
import json
import pickle
from typing import Optional
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import mlflow
from loguru import logger

try:
    import torch_geometric as pyg
    from torch_geometric.data import Data, DataLoader as GeoDataLoader
    from torch_geometric.nn import GATConv, global_mean_pool
    PYGEOMETRIC_AVAILABLE = True
except ImportError:
    logger.warning("torch-geometric not installed. GNN detector unavailable.")
    PYGEOMETRIC_AVAILABLE = False


# ─── Model Architecture ───────────────────────────────────────────────────────

class EnergyGNN(nn.Module):
    """
    Dual-head Graph Attention Network for electricity theft detection.
    - node_anomaly_head: is this specific meter anomalous?
    - balance_head: does the feeder energy balance hold? (Kirchhoff check)
    """

    def __init__(self, node_feat_dim: int = 32, hidden: int = 64):
        super().__init__()
        if not PYGEOMETRIC_AVAILABLE:
            raise ImportError("pip install torch-geometric")

        # Two GATConv layers
        self.conv1 = GATConv(node_feat_dim, hidden, heads=4, concat=True, dropout=0.1)
        self.conv2 = GATConv(hidden * 4, hidden, heads=1, concat=False, dropout=0.1)

        # Batch norm
        self.bn1 = nn.BatchNorm1d(hidden * 4)
        self.bn2 = nn.BatchNorm1d(hidden)

        # Prediction heads
        self.node_anomaly_head = nn.Sequential(
            nn.Linear(hidden, 32), nn.ReLU(), nn.Linear(32, 1), nn.Sigmoid()
        )
        self.balance_head = nn.Sequential(
            nn.Linear(hidden, 32), nn.ReLU(), nn.Linear(32, 1), nn.Sigmoid()
        )

    def forward(self, data: "Data"):
        x, edge_index, batch = data.x, data.edge_index, data.batch

        # GATConv layer 1
        x = self.conv1(x, edge_index)
        x = self.bn1(x)
        x = F.relu(x)
        x = F.dropout(x, p=0.1, training=self.training)

        # GATConv layer 2
        x = self.conv2(x, edge_index)
        x = self.bn2(x)
        x = F.relu(x)

        # Node-level: anomaly score per meter
        node_scores = self.node_anomaly_head(x).squeeze(-1)

        # Graph-level: feeder energy balance score
        feeder_agg    = global_mean_pool(x, batch)
        balance_scores = self.balance_head(feeder_agg).squeeze(-1)

        return node_scores, balance_scores


# ─── Graph Builder ────────────────────────────────────────────────────────────

def build_feeder_graph(
    meter_embeddings: dict[str, np.ndarray],
    topology_df: pd.DataFrame,
    feeder_id: str,
) -> Optional["Data"]:
    """
    Build a PyTorch Geometric Data object for one feeder sub-graph.

    Args:
        meter_embeddings: {meter_id: 32-dim embedding vector}
        topology_df: grid_topology table rows for this feeder
        feeder_id: feeder to build graph for

    Returns:
        pyg.Data with x, edge_index, feeder_loss_label
    """
    if not PYGEOMETRIC_AVAILABLE:
        return None

    feeder_rows = topology_df[topology_df["feeder_id"] == feeder_id]
    meter_ids   = [m for m in feeder_rows["meter_id"].tolist() if m in meter_embeddings]

    if len(meter_ids) < 2:
        return None

    # Node features: stacked embeddings
    x = torch.FloatTensor(
        np.vstack([meter_embeddings[m] for m in meter_ids])
    )

    # Edges: meter → transformer (DT) connections
    # Build index mapping
    meter_idx = {m: i for i, m in enumerate(meter_ids)}
    dt_groups = feeder_rows.groupby("transformer_id")["meter_id"].apply(list)

    edge_src, edge_dst = [], []
    for dt_id, dt_meters in dt_groups.items():
        dt_in_graph = [m for m in dt_meters if m in meter_idx]
        for i, m1 in enumerate(dt_in_graph):
            for m2 in dt_in_graph[i+1:]:
                # Bidirectional edges for meters on same DT
                edge_src += [meter_idx[m1], meter_idx[m2]]
                edge_dst += [meter_idx[m2], meter_idx[m1]]

    if not edge_src:
        return None

    edge_index = torch.LongTensor([edge_src, edge_dst])

    return Data(x=x, edge_index=edge_index, meter_ids=meter_ids)


# ─── Loss Function with Physics Constraint ────────────────────────────────────

def gnn_loss(
    node_scores: torch.Tensor,
    balance_scores: torch.Tensor,
    node_labels: torch.Tensor,     # 1=theft, 0=normal (per node)
    balance_labels: torch.Tensor,  # 1=loss violation, 0=balanced (per graph)
    feeder_input_kwh: torch.Tensor,
    meter_kwh_sum: torch.Tensor,
    lambda_physics: float = 0.5,
) -> torch.Tensor:
    """
    Combined loss:
    1. BCE on node anomaly prediction
    2. BCE on feeder balance prediction
    3. Physics constraint: meters can't consume MORE than feeder input
    """
    node_bce    = F.binary_cross_entropy(node_scores, node_labels.float())
    balance_bce = F.binary_cross_entropy(balance_scores, balance_labels.float())

    # Physics: penalize if sum(meter_kwh) > feeder_input_kwh
    physics_violation = torch.clamp(meter_kwh_sum - feeder_input_kwh, min=0)
    physics_loss = physics_violation.mean() / (feeder_input_kwh.mean() + 1e-8)

    total = node_bce + balance_bce + lambda_physics * physics_loss
    return total, {"node_bce": node_bce.item(), "balance_bce": balance_bce.item(),
                   "physics_loss": physics_loss.item()}


# ─── GNN Detector Class ───────────────────────────────────────────────────────

class GNNDetector:
    """
    High-level wrapper for EnergyGNN training and inference.

    IMPORTANT: Requires accurate feeder topology data.
    Do not deploy until topology audit is complete.
    """

    def __init__(self, node_feat_dim: int = 32, hidden: int = 64,
                 lr: float = 1e-3, lambda_physics: float = 0.5,
                 feeder_loss_threshold: float = 0.08,
                 device: str = "auto"):
        if not PYGEOMETRIC_AVAILABLE:
            raise ImportError("pip install torch-geometric")

        self.node_feat_dim      = node_feat_dim
        self.hidden             = hidden
        self.lr                 = lr
        self.lambda_physics     = lambda_physics
        self.feeder_loss_threshold = feeder_loss_threshold
        self.device = (
            torch.device("cuda" if torch.cuda.is_available() else "cpu")
            if device == "auto" else torch.device(device)
        )
        self.model = EnergyGNN(node_feat_dim=node_feat_dim, hidden=hidden).to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=lr, weight_decay=1e-5)

    def fit(self, graph_dataset: list, epochs: int = 50):
        """
        Train GNN on list of PyG Data objects (one per feeder snapshot).
        Self-supervised: feeder_loss_ratio > threshold = positive label.
        """
        loader = GeoDataLoader(graph_dataset, batch_size=16, shuffle=True)
        self.model.train()

        with mlflow.start_run(run_name="gnn_training", nested=True):
            for epoch in range(epochs):
                epoch_loss = 0.0
                for batch in loader:
                    batch = batch.to(self.device)
                    self.optimizer.zero_grad()

                    node_scores, balance_scores = self.model(batch)

                    # Self-supervised labels from physics
                    balance_labels = batch.balance_label.float()

                    # Proxy node labels: propagate feeder label to nodes
                    node_labels = torch.zeros(node_scores.shape, device=self.device)
                    for i, (start, end) in enumerate(self._get_graph_ranges(batch)):
                        if balance_labels[i] > 0.5:
                            node_labels[start:end] = 1.0

                    # Physics constraint inputs
                    feeder_input = batch.feeder_input_kwh.float()
                    meter_sum    = global_mean_pool(
                        batch.x[:, 0:1], batch.batch
                    ).squeeze()  # use first feature as kwh proxy

                    loss, _ = gnn_loss(
                        node_scores, balance_scores, node_labels, balance_labels,
                        feeder_input, meter_sum, self.lambda_physics
                    )
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                    self.optimizer.step()
                    epoch_loss += loss.item()

                if (epoch + 1) % 10 == 0:
                    avg_loss = epoch_loss / len(loader)
                    logger.info(f"GNN Epoch {epoch+1}/{epochs} | Loss: {avg_loss:.4f}")
                    mlflow.log_metric("gnn_train_loss", avg_loss, step=epoch)

    def _get_graph_ranges(self, batch):
        """Helper to get node index ranges per graph in batch."""
        sizes = batch.ptr[1:] - batch.ptr[:-1]
        ranges = []
        start = 0
        for size in sizes:
            ranges.append((start, start + size.item()))
            start += size.item()
        return ranges

    @torch.no_grad()
    def predict(self, graph_data: "Data") -> dict:
        """
        Predict anomaly scores for a single feeder graph.
        Returns dict with node_scores (per meter) and balance_score (per feeder).
        """
        self.model.eval()
        data = graph_data.to(self.device)
        node_scores, balance_scores = self.model(data)
        return {
            "node_scores":    node_scores.cpu().numpy(),
            "balance_score":  float(balance_scores.cpu().numpy()[0]),
            "meter_ids":      data.meter_ids,
        }

    def save(self, path: str):
        os.makedirs(path, exist_ok=True)
        torch.save(self.model.state_dict(), os.path.join(path, "gnn.pt"))
        with open(os.path.join(path, "gnn_config.json"), "w") as f:
            json.dump({
                "node_feat_dim": self.node_feat_dim,
                "hidden": self.hidden,
                "feeder_loss_threshold": self.feeder_loss_threshold,
            }, f)

    @classmethod
    def load(cls, path: str) -> "GNNDetector":
        with open(os.path.join(path, "gnn_config.json")) as f:
            cfg = json.load(f)
        instance = cls(**cfg)
        instance.model.load_state_dict(
            torch.load(os.path.join(path, "gnn.pt"), map_location="cpu")
        )
        instance.model.eval()
        return instance
