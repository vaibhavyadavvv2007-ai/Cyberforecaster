import torch
import torch.nn as nn

class TemporalTransformerForecaster(nn.Module):
    def __init__(
        self,
        n_features: int,
        horizon: int,
        n_stages: int = 6,
        d_model: int = 64,
        n_heads: int = 4,
        num_layers: int = 2,
        dim_feedforward: int = 128,
        dropout: float = 0.2
    ):
        super().__init__()
        self.n_features = n_features
        self.horizon = horizon
        self.d_model = d_model
        
        # Feature projection
        self.input_proj = nn.Linear(n_features, d_model)
        
        # Positional Encoding (learnable for simplicity since sequence is short L=10)
        self.pos_encoder = nn.Parameter(torch.randn(1, 100, d_model))
        
        # Transformer Encoder
        encoder_layers = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layers, num_layers=num_layers)
        
        # Shared MLP for heads
        self.shared_mlp = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.ReLU(),
            nn.Dropout(dropout)
        )
        
        # Original Outputs
        self.prog_head = nn.Linear(d_model // 2, horizon)
        self.stage_head = nn.Linear(d_model // 2, n_stages)
        
        # State Reconstruction Head (The "World Model" aspect)
        self.state_head = nn.Linear(d_model // 2, horizon * n_features)

    def forward(self, x: torch.Tensor):
        # x shape: (B, L, F)
        B, L, F = x.shape
        
        # Embed and add positional encoding
        embedded = self.input_proj(x)
        embedded = embedded + self.pos_encoder[:, :L, :]
        
        # Pass through Transformer
        encoded = self.transformer_encoder(embedded)
        
        # We can take the last token or pool. Let's take the last token for forecasting
        context = encoded[:, -1, :]
        
        # Shared representations
        rep = self.shared_mlp(context)
        
        # Head outputs
        prog_logits = self.prog_head(rep)
        stage_logits = self.stage_head(rep)
        state_pred = self.state_head(rep).view(B, self.horizon, self.n_features)
        
        return prog_logits, stage_logits, state_pred

def train(data_dir, epochs=40, predict_next_state=True, loss_state_weight=0.5):
    """
    Dummy train function to replace the lstm one if we swap it in scripts.
    In reality, we will adapt the training loop from lstm_forecaster.py
    """
    pass
