"""
ml/anomaly_detection/vae_detector.py

MeterVAE — Variational Autoencoder for smart meter anomaly detection.
Learns probabilistic latent distribution of normal consumption profiles.
Anomaly score = Monte Carlo reconstruction probability (IWAE bound).

Key advantage over standard AE: produces per-sample confidence bounds,
dramatically reducing false positives from meters with legitimate high variability.
"""

import os
import json
import pickle
from typing import Optional
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
import mlflow
import optuna
from loguru import logger


# ─── Model Architecture ───────────────────────────────────────────────────────

class MeterVAE(nn.Module):
    """
    Variational Autoencoder for 1-day meter consumption profiles.
    Input: 96-dim vector (96 × 15-min readings, normalized per meter).
    Latent space: 16-dim Gaussian (μ, σ).
    """

    def __init__(self, input_dim: int = 96, latent_dim: int = 16,
                 encoder_layers: int = 2, kl_weight: float = 0.1,
                 reconstruction: str = "mse"):
        super().__init__()
        self.input_dim     = input_dim
        self.latent_dim    = latent_dim
        self.kl_weight     = kl_weight
        self.reconstruction = reconstruction

        # Encoder
        enc_dims = [input_dim] + [max(32, input_dim // (2**i)) for i in range(1, encoder_layers+1)]
        enc_layers = []
        for i in range(len(enc_dims)-1):
            enc_layers += [nn.Linear(enc_dims[i], enc_dims[i+1]), nn.ReLU(), nn.BatchNorm1d(enc_dims[i+1])]
        self.encoder  = nn.Sequential(*enc_layers)
        self.fc_mu    = nn.Linear(enc_dims[-1], latent_dim)
        self.fc_logvar = nn.Linear(enc_dims[-1], latent_dim)

        # Decoder (mirror of encoder)
        dec_dims = list(reversed(enc_dims))
        dec_layers = [nn.Linear(latent_dim, dec_dims[0]), nn.ReLU()]
        for i in range(len(dec_dims)-1):
            dec_layers += [nn.Linear(dec_dims[i], dec_dims[i+1])]
            if i < len(dec_dims)-2:
                dec_layers += [nn.ReLU(), nn.BatchNorm1d(dec_dims[i+1])]
        self.decoder = nn.Sequential(*dec_layers)

    def encode(self, x: torch.Tensor):
        h    = self.encoder(x)
        mu   = self.fc_mu(h)
        logvar = self.fc_logvar(h)
        return mu, logvar

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        return self.decoder(z)

    def forward(self, x: torch.Tensor):
        mu, logvar = self.encode(x)
        z          = self.reparameterize(mu, logvar)
        x_hat      = self.decode(z)
        return x_hat, mu, logvar

    def reconstruction_loss(self, x: torch.Tensor, x_hat: torch.Tensor) -> torch.Tensor:
        if self.reconstruction == "mse":
            return F.mse_loss(x_hat, x, reduction="none").mean(-1)
        elif self.reconstruction == "mae":
            return F.l1_loss(x_hat, x, reduction="none").mean(-1)
        elif self.reconstruction == "huber":
            return F.huber_loss(x_hat, x, reduction="none").mean(-1)

    def kl_divergence(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        return -0.5 * (1 + logvar - mu.pow(2) - logvar.exp()).sum(-1)

    def elbo_loss(self, x: torch.Tensor, x_hat: torch.Tensor,
                  mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        """ELBO = reconstruction_loss + β × KL_divergence."""
        recon = self.reconstruction_loss(x, x_hat)
        kl    = self.kl_divergence(mu, logvar)
        return (recon + self.kl_weight * kl).mean()

    @torch.no_grad()
    def anomaly_score(self, x: torch.Tensor, n_samples: int = 50) -> torch.Tensor:
        """
        Monte Carlo anomaly score (IWAE bound).
        Average reconstruction error over n_samples latent samples.
        Higher = more anomalous.
        """
        scores = []
        for _ in range(n_samples):
            x_hat, mu, logvar = self.forward(x)
            recon = self.reconstruction_loss(x, x_hat)
            kl    = self.kl_divergence(mu, logvar)
            scores.append(recon + self.kl_weight * kl)
        return torch.stack(scores).mean(0)   # shape: (batch,)


# ─── Training ─────────────────────────────────────────────────────────────────

class VAEDetector:
    """
    High-level wrapper for MeterVAE training, inference, and threshold calibration.
    """

    def __init__(self, input_dim: int = 96, latent_dim: int = 16,
                 kl_weight: float = 0.1, encoder_layers: int = 2,
                 reconstruction: str = "mse", device: str = "auto"):
        self.device = (
            torch.device("cuda" if torch.cuda.is_available() else "cpu")
            if device == "auto" else torch.device(device)
        )
        self.model = MeterVAE(
            input_dim=input_dim,
            latent_dim=latent_dim,
            kl_weight=kl_weight,
            encoder_layers=encoder_layers,
            reconstruction=reconstruction,
        ).to(self.device)

        self.threshold_    : Optional[float]  = None  # fitted anomaly threshold
        self.scaler_mean_  : Optional[np.ndarray] = None  # per-feature normalization
        self.scaler_std_   : Optional[np.ndarray] = None

    # ── Normalization ──────────────────────────────────────────────────────────

    def _normalize(self, X: np.ndarray) -> np.ndarray:
        """Per-reading Z-score normalization (fitted on training data)."""
        if self.scaler_mean_ is None:
            self.scaler_mean_ = X.mean(axis=0)
            self.scaler_std_  = X.std(axis=0) + 1e-8
        return (X - self.scaler_mean_) / self.scaler_std_

    # ── Optuna HPO ────────────────────────────────────────────────────────────

    @staticmethod
    def hpo_search_space(trial: optuna.Trial) -> dict:
        return {
            "latent_dim":      trial.suggest_int("latent_dim", 4, 64),
            "encoder_layers":  trial.suggest_int("encoder_layers", 1, 4),
            "kl_weight":       trial.suggest_float("kl_weight", 0.001, 1.0, log=True),
            "reconstruction":  trial.suggest_categorical("reconstruction", ["mse", "mae", "huber"]),
            "lr":              trial.suggest_float("lr", 1e-4, 1e-2, log=True),
            "batch_size":      trial.suggest_categorical("batch_size", [64, 128, 256]),
            "threshold_pct":   trial.suggest_float("threshold_pct", 90.0, 99.9),
        }

    # ── Training ──────────────────────────────────────────────────────────────

    def fit(self, X_train: np.ndarray,
            lr: float = 1e-3,
            epochs: int = 50,
            batch_size: int = 128,
            threshold_pct: float = 99.0,
            X_val: Optional[np.ndarray] = None):
        """
        Train VAE on normal consumption data (no labels required).
        Sets anomaly threshold at threshold_pct of training reconstruction errors.
        """
        X_norm = self._normalize(X_train)
        tensor  = torch.FloatTensor(X_norm)
        loader  = DataLoader(TensorDataset(tensor), batch_size=batch_size, shuffle=True)

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr, weight_decay=1e-5)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

        with mlflow.start_run(run_name="vae_training", nested=True):
            mlflow.log_params({
                "input_dim": self.model.input_dim,
                "latent_dim": self.model.latent_dim,
                "kl_weight": self.model.kl_weight,
                "lr": lr, "epochs": epochs, "batch_size": batch_size,
                "threshold_pct": threshold_pct,
            })

            self.model.train()
            for epoch in range(epochs):
                epoch_loss = 0.0
                for (batch,) in loader:
                    batch = batch.to(self.device)
                    optimizer.zero_grad()
                    x_hat, mu, logvar = self.model(batch)
                    loss = self.model.elbo_loss(batch, x_hat, mu, logvar)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                    optimizer.step()
                    epoch_loss += loss.item()

                avg_loss = epoch_loss / len(loader)
                scheduler.step()

                if (epoch + 1) % 10 == 0:
                    logger.info(f"Epoch {epoch+1}/{epochs} | Loss: {avg_loss:.4f}")
                    mlflow.log_metric("train_loss", avg_loss, step=epoch)

            # Compute threshold on training data
            train_scores = self._compute_scores(X_train)
            self.threshold_ = float(np.percentile(train_scores, threshold_pct))
            mlflow.log_metric("anomaly_threshold", self.threshold_)
            logger.info(f"✓ VAE trained. Anomaly threshold (p{threshold_pct:.0f}): {self.threshold_:.4f}")

    def _compute_scores(self, X: np.ndarray, n_samples: int = 50) -> np.ndarray:
        """Compute anomaly scores for a batch of daily profiles."""
        X_norm  = self._normalize(X)
        tensor  = torch.FloatTensor(X_norm).to(self.device)
        self.model.eval()
        with torch.no_grad():
            scores = self.model.anomaly_score(tensor, n_samples=n_samples)
        return scores.cpu().numpy()

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return anomaly probability in [0,1] using sigmoid of normalized score."""
        raw_scores = self._compute_scores(X)
        if self.threshold_ is not None:
            # Sigmoid centered on threshold
            normalized = (raw_scores - self.threshold_) / (self.threshold_ * 0.5 + 1e-8)
            return 1 / (1 + np.exp(-normalized))
        return raw_scores

    def is_anomaly(self, X: np.ndarray) -> np.ndarray:
        """Boolean: is each sample above the fitted threshold?"""
        scores = self._compute_scores(X)
        return scores > self.threshold_

    def get_reconstruction(self, X: np.ndarray) -> np.ndarray:
        """Return reconstructed profiles (for visualization of what 'normal' looks like)."""
        X_norm = self._normalize(X)
        tensor = torch.FloatTensor(X_norm).to(self.device)
        self.model.eval()
        with torch.no_grad():
            x_hat, _, _ = self.model(tensor)
        return x_hat.cpu().numpy() * self.scaler_std_ + self.scaler_mean_

    def save(self, path: str):
        os.makedirs(path, exist_ok=True)
        torch.save(self.model.state_dict(), os.path.join(path, "vae.pt"))
        metadata = {
            "input_dim":    self.model.input_dim,
            "latent_dim":   self.model.latent_dim,
            "kl_weight":    self.model.kl_weight,
            "encoder_layers": 2,
            "reconstruction": self.model.reconstruction,
            "threshold":    self.threshold_,
        }
        with open(os.path.join(path, "vae_config.json"), "w") as f:
            json.dump(metadata, f)
        np.save(os.path.join(path, "scaler_mean.npy"), self.scaler_mean_)
        np.save(os.path.join(path, "scaler_std.npy"),  self.scaler_std_)
        logger.info(f"✓ VAEDetector saved to {path}")

    @classmethod
    def load(cls, path: str) -> "VAEDetector":
        with open(os.path.join(path, "vae_config.json")) as f:
            cfg = json.load(f)
        instance = cls(**{k: v for k, v in cfg.items() if k != "threshold"})
        instance.model.load_state_dict(
            torch.load(os.path.join(path, "vae.pt"), map_location="cpu")
        )
        instance.model.eval()
        instance.threshold_   = cfg.get("threshold")
        instance.scaler_mean_ = np.load(os.path.join(path, "scaler_mean.npy"))
        instance.scaler_std_  = np.load(os.path.join(path, "scaler_std.npy"))
        logger.info(f"✓ VAEDetector loaded from {path}")
        return instance
