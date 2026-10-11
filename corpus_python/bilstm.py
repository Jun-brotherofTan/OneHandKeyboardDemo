

import numpy as np
import paddle
import time
from paddle.fluid import dygraph
from paddle.fluid import initializer
from paddle.fluid import layers

from ddparser.parser.nets import nn
from ddparser.parser.nets import rnn
from ddparser.parser.nets import SharedDropout


class BiLSTM(dygraph.Layer):
    """
    BiLSTM
    TODO：
        Replace this class with the official implementation.
    """
    def __init__(self, input_size, hidden_size, num_layers=1, dropout=0):
        super(BiLSTM, self).__init__()

        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout

        self.lstm = paddle.nn.LSTM(input_size=input_size,
                                   hidden_size=hidden_size,
                                   num_layers=num_layers,
                                   dropout=dropout,
                                   direction="bidirectional")

    def forward(self, x, seq_mask):
        """Forward network"""
        seq_lens = nn.reduce_sum(seq_mask, -1)
        y, _ = self.lstm(x, sequence_length=seq_lens)

        return y
