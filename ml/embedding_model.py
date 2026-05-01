"""Neural embedding model for Dota 2 heroes and items."""
import torch
import torch.nn as nn


class DotaEmbeddingModel(nn.Module):
    """Learns hero and item embeddings from match data.

    Two modes:
    - Draft mode: encodes 10 heroes into a 128-dim context vector
    - Live mode: encodes 10 heroes + their items into a 256-dim game state vector
    """

    def __init__(self, num_heroes: int, num_items: int,
                 hero_embed_dim: int = 64, item_embed_dim: int = 32):
        super().__init__()

        self.hero_embed_dim = hero_embed_dim
        self.item_embed_dim = item_embed_dim

        # Embedding tables (add 1 for padding/unknown ID 0)
        self.hero_embedding = nn.Embedding(num_heroes + 1, hero_embed_dim, padding_idx=0)
        self.item_embedding = nn.Embedding(num_items + 1, item_embed_dim, padding_idx=0)

        # Draft encoder: 10 heroes (640-dim) -> 128-dim
        draft_input_dim = 10 * hero_embed_dim  # 640
        self.draft_encoder = nn.Sequential(
            nn.Linear(draft_input_dim, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.ReLU(),
        )

        # Live encoder: heroes (640) + player items (320) + my items (192) + time (3) = 1155
        live_input_dim = (10 * hero_embed_dim      # 10 hero embeddings
                         + 10 * item_embed_dim      # 10 mean-pooled item sets
                         + 6 * item_embed_dim        # my 6 item slots
                         + 3)                         # game time one-hot
        self.live_encoder = nn.Sequential(
            nn.Linear(live_input_dim, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 256),
            nn.ReLU(),
        )

        # Item prediction head (multi-label: predict which items to buy)
        self.item_head = nn.Linear(256, num_items + 1)

    def encode_draft(self, hero_ids: torch.Tensor) -> torch.Tensor:
        """Encode a draft (10 hero IDs) into a 128-dim vector.

        Args:
            hero_ids: (batch, 10) tensor of hero IDs
                      Order: [my_hero, ally1-4, enemy1-5]
        Returns:
            (batch, 128) draft context vector
        """
        embeds = self.hero_embedding(hero_ids)  # (batch, 10, 64)
        flat = embeds.reshape(embeds.size(0), -1)  # (batch, 640)
        return self.draft_encoder(flat)

    def encode_live(self, hero_ids: torch.Tensor, player_items: torch.Tensor,
                    my_items: torch.Tensor, game_time_onehot: torch.Tensor) -> torch.Tensor:
        """Encode full game state into a 256-dim vector.

        Args:
            hero_ids: (batch, 10) hero IDs
            player_items: (batch, 10, 6) item IDs for all 10 players
            my_items: (batch, 6) my current item IDs
            game_time_onehot: (batch, 3) one-hot [early, mid, late]
        Returns:
            (batch, 256) game state vector
        """
        # Hero embeddings
        hero_embeds = self.hero_embedding(hero_ids)  # (batch, 10, 64)
        hero_flat = hero_embeds.reshape(hero_embeds.size(0), -1)  # (batch, 640)

        # Per-player item embeddings (mean pool each player's items)
        item_embeds = self.item_embedding(player_items)  # (batch, 10, 6, 32)
        # Mask padding (item_id == 0)
        mask = (player_items > 0).unsqueeze(-1).float()  # (batch, 10, 6, 1)
        masked = item_embeds * mask
        # Mean pool per player (avoid div by zero)
        counts = mask.sum(dim=2).clamp(min=1)  # (batch, 10, 1)
        player_item_means = masked.sum(dim=2) / counts  # (batch, 10, 32)
        player_items_flat = player_item_means.reshape(player_item_means.size(0), -1)  # (batch, 320)

        # My items embeddings
        my_embeds = self.item_embedding(my_items)  # (batch, 6, 32)
        my_flat = my_embeds.reshape(my_embeds.size(0), -1)  # (batch, 192)

        # Concatenate all features
        combined = torch.cat([hero_flat, player_items_flat, my_flat, game_time_onehot], dim=1)
        return self.live_encoder(combined)

    def forward(self, hero_ids: torch.Tensor, player_items: torch.Tensor = None,
                my_items: torch.Tensor = None, game_time_onehot: torch.Tensor = None) -> torch.Tensor:
        """Forward pass -- returns item logits for multi-label prediction.

        If player_items provided: live mode (256-dim encoding)
        Otherwise: draft mode (128-dim encoding, padded to 256)
        """
        if player_items is not None and my_items is not None and game_time_onehot is not None:
            context = self.encode_live(hero_ids, player_items, my_items, game_time_onehot)
        else:
            draft_ctx = self.encode_draft(hero_ids)
            # Pad to 256 to share the item_head
            context = torch.nn.functional.pad(draft_ctx, (0, 128))

        return self.item_head(context)
