"""Gumbel-Softmax layer implementation.
Reference: https://arxiv.org/pdf/1611.04051.pdf"""
from re import search
from typing import NamedTuple, Optional

# pylint: disable=E0401
from tensorflow import (Tensor, TensorShape, concat, one_hot, split, squeeze,
                        stop_gradient)
from tensorflow.keras.layers import Activation, Layer
from tensorflow.keras.utils import register_keras_serializable
from tensorflow.math import log
from tensorflow.nn import softmax
from tensorflow.random import categorical, uniform

TOL = 1e-20


def gumbel_noise(shape: TensorShape) -> Tensor:
    """Create a single sample from the standard (loc = 0, scale = 1) Gumbel distribution."""
    uniform_sample = uniform(shape, seed=0)
    return -log(-log(uniform_sample + TOL) + TOL)

@register_keras_serializable(package='Synthetic Data', name='GumbelSoftmaxLayer')
class GumbelSoftmaxLayer(Layer):
    "A Gumbel-Softmax layer implementation that should be stacked on top of a categorical feature logits."

    def __init__(self, tau: float = 0.2, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.tau = tau

    # pylint: disable=W0221, E1120
    def call(self, _input):
        """Computes Gumbel-Softmax for the logits output of a particular categorical feature."""
        noised_input = _input + gumbel_noise(_input.shape)
        soft_sample = softmax(noised_input/self.tau, -1)
        hard_sample = stop_gradient(squeeze(one_hot(categorical(log(soft_sample), 1), _input.shape[-1]), 1))
        return hard_sample, soft_sample

    def get_config(self):
        config = super().get_config().copy()
        config.update({'tau': self.tau})
        return config


@register_keras_serializable(package='Synthetic Data', name='GumbelSoftmaxActivation')
class GumbelSoftmaxActivation(Layer):
    """An interface layer connecting different parts of an incoming tensor to adequate activation functions.
    The tensor parts are qualified according to the passed processor object.
    Processed categorical features are sent to specific Gumbel-Softmax layers.
    Processed features of different kind are sent to a TanH activation.
    Finally all output parts are concatenated and returned in the same order.

    The parts of an incoming tensor are qualified by leveraging a namedtuple pointing to each of the used data \
        processor's pipelines in/out feature maps. For simplicity this object can be taken directly from the data \
        processor col_transform_info."""

    def __init__(self, activation_info: NamedTuple, name: Optional[str] = None, **kwargs):
        """Arguments:
            col_map (NamedTuple): Defines each of the processor pipelines input/output features.
            name (Optional[str]): Name of the layer"""
        super().__init__(name=name, **kwargs)

        self._activation_info = activation_info

        self.cat_feats = activation_info.categorical
        self.num_feats = activation_info.numerical

        self._cat_lens = [len([col for col in self.cat_feats.feat_names_out if search(f'^{cat_feat}_.*$', col)]) \
            for cat_feat in self.cat_feats.feat_names_in]
        self._num_lens = len(self.num_feats.feat_names_out)

    def call(self, _input):  # pylint: disable=W0221
        num_cols, cat_cols = split(_input, [self._num_lens, -1], 1, name='split_num_cats')
        cat_cols = split(cat_cols, self._cat_lens if self._cat_lens else [0], 1, name='split_cats')

        num_cols = [Activation('tanh', name='num_cols_activation')(num_cols)]
        cat_cols = [GumbelSoftmaxLayer(name=name)(col)[0] for name, col in \
            zip(self.cat_feats.feat_names_in, cat_cols)]
        return concat(num_cols+cat_cols, 1)

    def get_config(self):
        config = super().get_config().copy()
        config.update({'activation_info': self._activation_info})
        return config
