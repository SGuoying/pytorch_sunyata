# %%
import torch
from composer.loss import soft_cross_entropy
from composer.metrics import CrossEntropy
from composer.models import ComposerClassifier
from torchmetrics import MetricCollection
from torchmetrics.classification import MulticlassAccuracy
from sunyata.pytorch.arch.Vit_pytorch import ConvMixerCfg, ViT
from sunyata.pytorch.arch.conformer import Conformer, Conformer2, Conformer3, Conformer3_1, Conformer3_2, Conformer4, Conformer_1, Conformer_2, Convolution

from sunyata.pytorch.arch.convmixer import BayesConvMixer3, BayesConvMixer4, BayesConvMixer5, BayesFormer, ConvMixer2, ConvMixer, BayesConvMixer, ConvMixer3, Former
from sunyata.pytorch.arch.convnextv2 import ConvNeXtV2
# %%
def build_composer_convmixer(model_name: str = 'convmixer',
                            #  loss_name: str = 'cross_entropy',
                             num_layers: int = 8,
                             hidden_dim: int = 256,
                             patch_size: int = 7,
                             kernel_size: int = 5,
                             num_classes: int = 100,
                             layer_norm_zero_init: bool = False,
                             skip_connection: bool = True,
                             eca_kernel_size: int = 3,
                             image_size: int = 224,
                             pool: str = 'cls' # or 'mean'
                             ):
    
    cfg = ConvMixerCfg(
        num_layers = num_layers,
        hidden_dim = hidden_dim,
        patch_size = patch_size,
        kernel_size = kernel_size,
        num_classes = num_classes,
        layer_norm_zero_init = layer_norm_zero_init,
        skip_connection = skip_connection,
        eca_kernel_size = eca_kernel_size,
        image_size = image_size,
        pool = pool
    )

    if model_name == "convmixer":
        model = ConvMixer(cfg)
    elif model_name == "convmixer2":
        model = ConvMixer2(cfg)
    elif model_name == "convmixer3":
        model = ConvMixer3(cfg)
    elif model_name == "bayes_convmixer":
        model = BayesConvMixer(cfg)
    elif model_name == "bayes_convmixer3":
        model = BayesConvMixer3(cfg)
    elif model_name == "bayes_convmixer4":
        model = BayesConvMixer4(cfg)
    elif model_name == "bayes_convmixer5":
        model = BayesConvMixer5(cfg)

    elif model_name == "ConvNeXtV2":
        model = ConvNeXtV2(in_chans=3,
                           num_classes=cfg.num_classes,
                           dims=[64, 128, 256, 512])

    elif model_name == "Convolution":
        model = Convolution(cfg)

    elif model_name == "Conformer":
        model = Conformer(cfg)
    elif model_name == "Conformer_1":
        model = Conformer_1(cfg)
    elif model_name == "Conformer_2":
        model = Conformer_2(cfg)

    elif model_name == "Conformer2":
        model = Conformer2(cfg)

    elif model_name == "Conformer3":
        model = Conformer3(cfg)
    elif model_name == "Conformer3_1":
        model = Conformer3_1(cfg)
    elif model_name == "Conformer3_2":
        model = Conformer3_2(cfg)

    elif model_name == "Conformer4":
        model = Conformer4(cfg)
    elif model_name == "Former":
        model = Former(cfg)
    elif model_name == "BayesFormer":
        model = BayesFormer(cfg)

    else:
        raise ValueError(f"model_name='{model_name}' but only 'convmixer' and 'bayes_convmixer' are supported now.")
    


    # # Specify model initialization
    # def weight_init(w: torch.nn.Module):
    #     if isinstance(w, torch.nn.Linear) or isinstance(w, torch.nn.Conv2d):
    #         torch.nn.init.kaiming_normal_(w.weight)
    #     if isinstance(w, torch.nn.BatchNorm2d):
    #         w.weight.data = torch.rand(w.weight.data.shape)
    #         w.bias.data = torch.zeros_like(w.bias.data)
    #     # When using binary cross entropy, set the classification layer bias to -log(num_classes)
    #     # to ensure the initial probabilities are approximately 1 / num_classes
    #     if loss_name == 'binary_cross_entropy' and isinstance(
    #             w, torch.nn.Linear):
    #         w.bias.data = torch.ones(
    #             w.bias.shape) * -torch.log(torch.tensor(w.bias.shape[0]))

    # model.apply(weight_init)
    # Performance metrics to log other than training loss
    train_metrics = MulticlassAccuracy(num_classes=num_classes, average='micro')
    val_metrics = MetricCollection([
        CrossEntropy(),
        MulticlassAccuracy(num_classes=num_classes, average='micro')
    ])

    # Choose loss function: either cross entropy or binary cross entropy
    # if loss_name == 'cross_entropy':
    #     loss_fn = soft_cross_entropy
    # elif loss_name == 'binary_cross_entropy':
    #     loss_fn = binary_cross_entropy_with_logits
    # else:
    #     raise ValueError(
    #         f"loss_name='{loss_name}' but must be either ['cross_entropy', 'binary_cross_entropy']"
    #     )

    # Wrapper function to convert a image classification Pytorch model into a Composer model
    composer_model = ComposerClassifier(
        model,
        train_metrics=train_metrics,
        val_metrics=val_metrics,
        loss_fn=soft_cross_entropy,
    )
    return composer_model
# %%
# composer_model = build_composer_convmixer()
# input = [torch.randn(2, 3, 224, 224), torch.randint(0,100, (2,))]
# output = composer_model(input)
# output.shape
