

from paddle.fluid import dygraph
from paddle.fluid import initializer
from paddle.fluid import layers

from ddparser.parser.nets import SharedDropout


class MLP(dygraph.Layer):
    """MLP"""
    def __init__(self, n_in, n_out, dropout=0):
        super(MLP, self).__init__()

        self.n_in = n_in
        self.n_out = n_out
        self.linear = dygraph.Linear(
            n_in,
            n_out,
            param_attr=initializer.Xavier(uniform=False),
            bias_attr=None,
        )
        self.dropout = SharedDropout(p=dropout)

    def forward(self, x):
        """Forward network"""
        x = self.linear(x)
        x = layers.leaky_relu(x, alpha=0.1)
        x = self.dropout(x)

        return x
