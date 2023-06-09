from typing import Callable
import torch
import torch.nn as nn
import torch.nn.functional as F


class AttentionPool2d(nn.Module):
    "Attention for Learned Aggregation"
    def __init__(self,
        dim:int,
        bias:bool=True,
        # norm:Callable[[int], nn.Module]=nn.LayerNorm
    ):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.q = nn.Linear(dim, dim, bias=bias)
        self.vk = nn.Linear(dim, dim*2, bias=bias)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x, cls_q):
        x = self.norm(x.flatten(2).transpose(1,2))
        B, N, C = x.shape

        q = self.q(cls_q.expand(B, -1, -1))
        k, v = self.vk(x).reshape(B, N, 2, C).permute(2, 0, 1, 3).chunk(2, 0)

        attn = q @ k.transpose(-2, -1)
        attn = attn.softmax(dim=-1)

        x = (attn @ v).transpose(1, 2).reshape(B, C)
        return self.proj(x)
    

class AvgAttnPooling2dS(nn.Module):
    def __init__(self,
        dim:int,
        attn_bias:bool=True,
        # ffn_expand:int=3,
        norm:Callable[[int], nn.Module]=nn.LayerNorm,
        act_cls:Callable[[None], nn.Module]=nn.GELU,
    ):
        super().__init__()
        self.cls_q = nn.Parameter(torch.zeros([1,dim]))
        self.attn = AttentionPool2d(dim, attn_bias)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.norm = norm(dim)
        self.act = act_cls()
        nn.init.trunc_normal_(self.cls_q, std=0.02)
        self.apply(self._init_weights)

    def forward(self, x):
        x = self.norm( self.pool(x).flatten(1) + self.attn(x, self.cls_q))
        x = self.act(x)
        # x_reshaped = torch.unsqueeze(x, 2)
        # x_reshaped = torch.unsqueeze(x_reshaped, 3)
        return x

    @torch.no_grad()
    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            nn.init.trunc_normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.constant_(m.bias, 0)





"""
perceiver

"""
# helpers
from einops import rearrange, repeat
from torch import einsum
from einops.layers.torch import Reduce
def exists(val):
    return val is not None

def default(val, d):
    return val if exists(val) else d

class Attention(nn.Module):
    def __init__(self, query_dim, context_dim = None, heads = 8, dim_head = 32, dropout = 0.):
        super().__init__()
        inner_dim = dim_head * heads
        context_dim = default(context_dim, query_dim)

        self.scale = dim_head ** -0.5
        self.heads = heads

        self.to_q = nn.Linear(query_dim, inner_dim, bias = False)
        self.to_kv = nn.Linear(context_dim, inner_dim * 2, bias = False)

        self.dropout = nn.Dropout(dropout)
        self.to_out = nn.Linear(inner_dim, query_dim)

    def forward(self, x, context):
        # x: [B, C, H, W]
        # context = context.flatten(2).transpose(1, 2)  # [B, HW, C]
        h = self.heads

        q = self.to_q(x)
        context = default(context, x)
        k, v = self.to_kv(context).chunk(2, dim = -1)

        q, k, v = map(lambda t: rearrange(t, 'b n (h d) -> (b h) n d', h = h), (q, k, v))

        sim = einsum('b i d, b j d -> b i j', q, k) * self.scale

        # attention, what we cannot get enough of
        attn = sim.softmax(dim = -1)
        attn = self.dropout(attn)

        out = einsum('b i j, b j d -> b i d', attn, v)
        out = rearrange(out, '(b h) n d -> b n (h d)', h = h)
        out = self.to_out(out)
        # B, HW, C = out.size()
        # h = int(HW ** 0.5)
        # out = out.transpose(1, 2).view(B, C, h, h)
        return out