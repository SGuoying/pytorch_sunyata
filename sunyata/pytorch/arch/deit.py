# %%
import torch
import torch.nn as nn
import torch.nn.functional as F
from functools import partial

from timm.models.vision_transformer import Mlp, PatchEmbed

from timm.models.layers import DropPath, trunc_normal_
from timm.models.registry import register_model

# %%
class Attention(nn.Module):
    def __init__(
            self, 
            dim, 
            num_heads=8, 
            qkv_bias=False,
            qk_scale=None,
            attn_drop=0.,
            proj_drop=0.
    ):
        super().__init__()
        self.num_heads = num_heads
        head_dim = dim // num_heads
        self.scale = qk_scale or head_dim ** -0.5

        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)

    def forward(self, x):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]

        q = q * self.scale

        attn = (q @ k.transpose(-2, -1))
        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)

        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        x = self.proj_drop(x)
        return x
# %%
class Layer_scale_init_Block(nn.Module):
    def __init__(
            self,
            dim,
            num_heads,
            mlp_ratio=4.,
            qkv_bias=False,
            qk_scale=None,
            drop=0.,
            attn_drop=0.,
            drop_path=0.,
            act_layer=nn.GELU,
            norm_layer=nn.LayerNorm,
            Attention_block=Attention,
            Mlp_block=Mlp,
            init_values=1e-4,
    ):
        super().__init__()
        self.norm1 = norm_layer(dim)
        self.attn = Attention_block(
            dim, num_heads, qkv_bias, qk_scale, attn_drop, proj_drop=drop
        )
        # NOTE: drop path for stochastic depth, we shall see if this is better than dropout here
        self.drop_path = DropPath(drop_path) if drop_path > 0. else nn.Identity()
        self.norm2 = norm_layer(dim)
        mlp_hidden_dim = int(dim * mlp_ratio)
        self.mlp = Mlp_block(in_features=dim, hidden_features=mlp_hidden_dim, act_layer=act_layer, drop=drop)
        self.gamma_1 = nn.Parameter(init_values * torch.ones((dim)), requires_grad=True)
        self.gamma_2 = nn.Parameter(init_values * torch.ones((dim)), requires_grad=True)

    def forward(self, x):
        x = x + self.drop_path(self.gamma_1 * self.attn(self.norm1(x)))
        x = x + self.drop_path(self.gamma_2 * self.mlp(self.norm2(x)))
        return x
# %%
class vit_models(nn.Module):
    def __init__(
            self,
            img_size=224,
            patch_size=16,
            in_chans=3,
            num_classes=1000,
            embed_dim=768,
            depth=12,
            num_heads=12,
            mlp_ratio=4.,
            qkv_bias=False,
            qk_scale=None,
            drop_rate=0.,
            attn_drop_rate=0.,
            drop_path_rate=0.,
            norm_layer=nn.LayerNorm,
            global_pool=None,
            block_layers = Layer_scale_init_Block,
            Patch_layer = PatchEmbed,
            act_layer = nn.GELU,
            Attention_block = Attention,
            Mlp_block = Mlp,
            dpr_constant=True,
            init_scale=1e-4,
            mlp_ratio_clstk=4.0,
    ):
        super().__init__()

        self.dropout_rate = drop_rate
        self.num_classes = num_classes
        self.num_features = self.embed_dim = embed_dim

        self.patch_embed = Patch_layer(
            img_size=img_size, patch_size=patch_size, in_chans=in_chans, embed_dim=embed_dim
        )
        num_patchs = self.patch_embed.num_patches

        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))

        self.pos_embed = nn.Parameter(torch.zeros(1, num_patchs, embed_dim))

        dpr = [drop_path_rate for i in range(depth)]
        self.blocks = nn.ModuleList([
            block_layers(
                dim=embed_dim, num_heads=num_heads, mlp_ratio=mlp_ratio, qkv_bias=qkv_bias, qk_scale=qk_scale,
                drop=0.0, attn_drop=attn_drop_rate, drop_path=dpr[i], norm_layer=norm_layer,
                act_layer=act_layer, Attention_block=Attention_block, Mlp_block=Mlp_block, init_values=init_scale
            )
            for i in range(depth)
        ])

        self.norm = norm_layer(embed_dim)
        
        self.feature_info = [dict(num_chs=embed_dim, reduction=0, module='head')]
        self.head = nn.Linear(embed_dim, num_classes) if num_classes > 0 else nn.Identity()

        trunc_normal_(self.pos_embed, std=.02)
        trunc_normal_(self.cls_token, std=.02)
        self.apply(self._init_weights)

    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            trunc_normal_(m.weight, std=.02)
            if isinstance(m, nn.Linear) and m.bias is not None:
                nn.init.constant_(m.bias, 0)
        elif isinstance(m, nn.LayerNorm):
            nn.init.constant_(m.bias, 0)
            nn.init.constant_(m.weight, 1.0)

    @torch.jit.ignore
    def no_weight_decay(self):
        return {'pos_embed', 'cls_token'}
    
    def get_classifier(self):
        return self.head

    def get_num_layers(self):
        return len(self.blocks)
    
    def reset_classifier(self, num_classes, global_pool=''):
        self.num_classes = num_classes
        self.head = nn.Linear(self.embed_dim, num_classes) if num_classes > 0 else nn.Identity()

    def forward(self, x):
        B = x.shape[0]
        x = self.patch_embed(x)

        cls_tokens = self.cls_token.expand(B, -1, -1)

        x = x + self.pos_embed

        x = torch.cat((cls_tokens, x), dim=1)

        for i, blk in enumerate(self.blocks):
            x = blk(x)

        x = self.norm(x)

        x = x[:, 0]

        if self.dropout_rate:
            x = F.dropout(x, p=float(self.dropout_rate), training=self.training)

        x = self.head(x)

        return x
# %%
class bayes_vit_models(vit_models):
    def __init__(
            self,
            img_size=224,
            patch_size=16,
            in_chans=3,
            num_classes=1000,
            embed_dim=768,
            depth=12,
            num_heads=12,
            mlp_ratio=4.,
            qkv_bias=False,
            qk_scale=None,
            drop_rate=0.,
            attn_drop_rate=0.,
            drop_path_rate=0.,
            norm_layer=nn.LayerNorm,
            global_pool=None,
            block_layers = Layer_scale_init_Block,
            Patch_layer = PatchEmbed,
            act_layer = nn.GELU,
            Attention_block = Attention,
            Mlp_block = Mlp,
            dpr_constant=True,
            init_scale=1e-4,
            mlp_ratio_clstk=4.0,
    ):
        super().__init__(
            img_size,
            patch_size,
            in_chans,
            num_classes,
            embed_dim,
            depth,
            num_heads,
            mlp_ratio,
            qkv_bias,
            qk_scale,
            drop_rate,
            attn_drop_rate,
            drop_path_rate,
            norm_layer,
            global_pool,
            block_layers,
            Patch_layer,
            act_layer,
            Attention_block,
            Mlp_block,
            dpr_constant,
            init_scale,
            mlp_ratio_clstk,
        )

        log_prior = torch.zeros(1, num_classes)
        self.register_buffer('log_prior', log_prior)
#         self.logits_bias = nn.Parameter(torch.zeros(1, num_classes))
        self.logits_layer_norm = nn.LayerNorm(num_classes)
        # self.norm = None
        self.apply(self._init_weights)


    def forward(self, x):
        B = x.shape[0]
        x = self.patch_embed(x)

        cls_tokens = self.cls_token.expand(B, -1, -1)
        log_prior = self.log_prior.expand(B, -1)

        x = x + self.pos_embed

        x = torch.cat((cls_tokens, x), dim=1)

        for i, blk in enumerate(self.blocks):
            x = blk(x)
            logits = self.norm(x)
            logits = x[:, 0]
            logits = self.head(logits)
            log_prior = log_prior + logits
            log_prior = self.logits_layer_norm(log_prior)
            # log_prior = log_prior - torch.mean(log_prior, dim=-1, keepdim=True) + self.logits_bias
            # log_prior = F.log_softmax(log_prior, dim=-1)
        
        return log_prior

# %%
@register_model
def deit_tiny_patch16_LS(pretrained=False, pretrained_cfg=None, img_size=224, pretrained_21k = False,   **kwargs):
    model = vit_models(
        img_size=img_size, patch_size=16, embed_dim=192, depth=12, num_heads=3, mlp_ratio=4, qkv_bias=True,
        norm_layer=partial(nn.LayerNorm, eps=1e-6), block_layers=Layer_scale_init_Block,
        **kwargs
    )
    return model
# %%
@register_model
def bayes_deit_tiny_patch16_LS(pretrained=False, pretrained_cfg=None, img_size=224, pretrained_21k = False,   **kwargs):
    model = bayes_vit_models(
        img_size=img_size, patch_size=16, embed_dim=192, depth=12, num_heads=3, mlp_ratio=4, qkv_bias=True,
        norm_layer=partial(nn.LayerNorm, eps=1e-6), block_layers=Layer_scale_init_Block,
        **kwargs
    )
    return model
# %%
