from dataclasses import dataclass
from einops import rearrange, reduce, repeat
from einops.layers.torch import Rearrange
import torch
import torch.nn as nn
import torch.nn.functional as F
from sunyata.pytorch.arch.attentionpool import Attention
from sunyata.pytorch.arch.base import SE, BaseCfg, ConvMixerLayer

@dataclass
class ConvMixerCfg(BaseCfg):
    num_layers: int = 8
    hidden_dim: int = 256
    kernel_size: int = 5
    patch_size: int = 2
    num_classes: int = 10

    drop_rate: float = 0.
    squeeze_factor: int = 4

    skip_connection: bool = True

    eca_kernel_size: int = 3


class ConvMixerattn(nn.Module):
    def __init__(self, cfg: ConvMixerCfg):
        super().__init__()

        self.layers = nn.ModuleList([
            ConvMixerLayer(cfg.hidden_dim, cfg.kernel_size, cfg.drop_rate)
            for _ in range(cfg.num_layers)
        ])

        # self.embed = nn.Sequential(
        #     nn.Conv2d(3, cfg.hidden_dim, kernel_size=cfg.patch_size,
        #               stride=cfg.patch_size),
        #     nn.GELU(),
        #     # eps>6.1e-5 to avoid nan in half precision
        #     nn.BatchNorm2d(cfg.hidden_dim, eps=7e-5),
        # )
        self.embed = nn.Sequential(
            nn.Conv2d(3, cfg.hidden_dim, kernel_size=cfg.kernel_size, padding="same"),
            nn.GELU(),
            # eps>6.1e-5 to avoid nan in half precision
            nn.BatchNorm2d(cfg.hidden_dim, eps=7e-5),
        )
        
        # self.digup = nn.Sequential(
        #     nn.AdaptiveAvgPool2d((1, 1)),
        #     nn.Flatten(),
        #     nn.Linear(cfg.hidden_dim, cfg.num_classes)
        # )
        self.attn = Attention(cfg.hidden_dim, 3)
        self.layer_norm = nn.LayerNorm(cfg.hidden_dim)
        self.fc = nn.Linear(cfg.hidden_dim, cfg.num_classes)

        self.cfg = cfg
        # logits = torch.zeros(1, cfg.hidden_dim)
        # self.register_buffer('logits', logits)

    def forward(self, x):
        # data = x.flatten(2).transpose(1, 2)
        # x = self.embed(x)
        data = x.flatten(2).transpose(1, 2)  # [B, HW, C]
        x = self.embed(x)
        logits = self.attn(x, data)
        for layer in self.layers:
            x = x + layer(x)
            logits = self.attn(x, data) + logits
            logits = self.layer_norm(logits)
        logits = self.fc(logits)
        # x = self.digup(x)
        return logits
    

class ConvMixerattn2(nn.Module):
    def __init__(self, cfg: ConvMixerCfg):
        super().__init__()

        self.layers = nn.ModuleList([
            ConvMixerLayer(cfg.hidden_dim, cfg.kernel_size, cfg.drop_rate)
            for _ in range(cfg.num_layers)
        ])

        self.embed = nn.Sequential(
            nn.Conv2d(3, cfg.hidden_dim, kernel_size=cfg.patch_size,
                      stride=cfg.patch_size),
            nn.GELU(),
            # eps>6.1e-5 to avoid nan in half precision
            nn.BatchNorm2d(cfg.hidden_dim, eps=7e-5),
        )

        self.digup = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, 1)),
            Rearrange('b c h w -> b (h w) c'),
            # nn.Flatten(),
            # nn.Linear(cfg.hidden_dim, cfg.num_classes)
        )
        self.attn = Attention(cfg.hidden_dim,context_dim=cfg.hidden_dim,
                      heads=1, dim_head=cfg.hidden_dim)

        self.layer_norm = nn.LayerNorm(cfg.hidden_dim)
        self.fc = nn.Linear(cfg.hidden_dim, cfg.num_classes)

        self.cfg = cfg

    def forward(self, x):
        

        x = self.embed(x)
        input = x.flatten(2).transpose(1, 2)  # data:init   [B, HW, C]  
        logits = [self.digup(x)]
        # logits = self.attn(logits, input)

        for layer in self.layers:
            x = layer(x) + x
            logits =logits + [self.digup(x)]
        logits = rearrange(logits, 'n b hw c -> b (n hw) c')
        logits = self.attn(input, logits)
        logits = reduce(logits, 'b n c -> b c', 'mean')
        logits = self.layer_norm(logits)
        logits = self.fc(logits)
        # x = self.digup(x)
        return logits
    

from functools import wraps
def cache_fn(f):
    cache = dict()
    @wraps(f)
    def cached_fn(*args, _cache = True, key = None, **kwargs):
        if not _cache:
            return f(*args, **kwargs)
        nonlocal cache
        if key in cache:
            return cache[key]
        result = f(*args, **kwargs)
        cache[key] = result
        return result
    return cached_fn

class ConvMixerattn3(nn.Module):
    def __init__(self, cfg: ConvMixerCfg):
        super().__init__()
        weight_tie_layers = False
        self_per_cross_conv = 1

        # self.layers = nn.ModuleList([
        #     ConvMixerLayer(cfg.hidden_dim, cfg.kernel_size, cfg.drop_rate)
        #     for _ in range(cfg.num_layers)
        # ])

        conv = lambda: ConvMixerLayer(cfg.hidden_dim, cfg.kernel_size, cfg.drop_rate)
        attn = lambda: Attention(query_dim=cfg.hidden_dim,
                              context_dim=cfg.hidden_dim,
                              heads=1,
                              dim_head=cfg.hidden_dim)
        conv, attn = map(cache_fn, (conv, attn))

        self.layer = nn.ModuleList([])
        for i in range(cfg.num_layers):
            should_cache = i > 0 and weight_tie_layers
            cache_args = {'_cache': should_cache}

            self_conv = nn.ModuleList([])

            for key in range(self_per_cross_conv):
                self_conv.append(
                    conv(**cache_args, key=key)
                )
            self.layer.append(nn.ModuleList([
                self_conv,
                attn(**cache_args)
            ]))

        self.embed = nn.Sequential(
            nn.Conv2d(3, cfg.hidden_dim, kernel_size=cfg.patch_size,
                      stride=cfg.patch_size),
            nn.GELU(),
            # eps>6.1e-5 to avoid nan in half precision
            nn.BatchNorm2d(cfg.hidden_dim, eps=7e-5),
        )

        self.digup = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Linear(cfg.hidden_dim, cfg.num_classes)
        )
        self.attn = Attention(query_dim=cfg.hidden_dim,
                              context_dim=cfg.hidden_dim,
                              heads=1,
                              dim_head=cfg.hidden_dim)
        self.layer_norm = nn.LayerNorm(cfg.hidden_dim)
        # self.fc = nn.Linear(cfg.hidden_dim, cfg.num_classes)

        self.cfg = cfg
        self.latent = nn.Parameter(torch.randn(1, cfg.hidden_dim))

    def forward(self, x):
        batch_size, _, _, _ = x.shape
        latent = repeat(self.latent, 'n d -> b n d', b = batch_size)
        x = self.embed(x)
        input = x.permute(0, 2, 3, 1)
        input = rearrange(input, 'b ... d -> b (...) d')
        latent = self.attn(latent, input)
        latent = self.layer_norm(latent)

        for self_conv, attn in self.layer:
            for conv in self_conv:
                x = conv(x) + x
            input = x.permute(0, 2, 3, 1)
            input = rearrange(input, 'b ... d -> b (...) d')
            latent = attn(latent, input) + latent
            latent = self.layer_norm(latent)
            B, HW, C = latent.size()
            h = int(HW ** 0.5)
            x = latent.transpose(1, 2).view(B, C, h, h)
            
        x = self.digup(x)
        return x
    

