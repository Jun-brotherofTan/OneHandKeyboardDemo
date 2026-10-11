

import numpy as np
import paddle
import time
from paddle.fluid import dygraph
from paddle.fluid import layers

from ddparser.parser.nets import BiLSTM
from ddparser.parser.nets import nn


class CharLSTM(dygraph.Layer):
    """CharLSTM"""
    def __init__(self, n_chars, n_embed, n_out, pad_index=0):
        super(CharLSTM, self).__init__()
        self.n_chars = n_chars
        self.n_embed = n_embed
        self.n_out = n_out
        self.pad_index = pad_index

        # the embedding layer
        self.embed = dygraph.Embedding(size=(n_chars, n_embed))
        # the lstm layer
        self.lstm = BiLSTM(input_size=n_embed, hidden_size=n_out // 2)
        self.lstm = paddle.nn.LSTM(input_size=n_embed, hidden_size=n_out // 2, direction="bidirectional")

    def forward(self, x):
        """Forward network"""
        mask = layers.reduce_any(x != self.pad_index, -1)
        lens = nn.reduce_sum(mask, -1)
        masked_x = nn.masked_select(x, mask)
        char_mask = masked_x != self.pad_index
        emb = self.embed(masked_x)
        word_lens = nn.reduce_sum(char_mask, -1)
        _, (h, _) = self.lstm(emb, sequence_length=word_lens)
        h = layers.concat(layers.unstack(h), axis=-1)
        feat_embed = nn.pad_sequence_paddle(layers.split(h, lens.numpy().tolist(), dim=0), self.pad_index)
        return feat_embed
