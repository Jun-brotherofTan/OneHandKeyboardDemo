

from paddle.fluid import dygraph
from paddle.fluid import layers


class Biaffine(dygraph.Layer):
    """Biaffine"""
    def __init__(self, n_in, n_out=1, bias_x=True, bias_y=True):
        super(Biaffine, self).__init__()

        self.n_in = n_in
        self.n_out = n_out
        self.bias_x = bias_x
        self.bias_y = bias_y
        self.weight = layers.create_parameter(shape=(n_out, n_in + bias_x, n_in + bias_y), dtype="float32")

    def forward(self, x, y):
        """Forward network"""
        if self.bias_x:
            x = layers.concat((x, layers.ones_like(x[:, :, :1])), axis=-1)
        if self.bias_y:
            y = layers.concat((y, layers.ones_like(x[:, :, :1])), axis=-1)
        # x.shape=(b, m, i)
        b = x.shape[0]
        # self.weight.shape=(o, i, j)
        o = self.weight.shape[0]
        x = layers.expand(layers.unsqueeze(x, axes=[1]), expand_times=(1, o, 1, 1))
        weight = layers.expand(layers.unsqueeze(self.weight, axes=[0]), expand_times=(b, 1, 1, 1))
        y = layers.expand(layers.unsqueeze(y, axes=[1]), expand_times=(1, o, 1, 1))

        # s.shape=(b, o, m, n), that is, [batch_size, n_out, seq_len, seq_len]
        s = layers.matmul(layers.matmul(x, weight), layers.transpose(y, perm=(0, 1, 3, 2)))
        # remove dim 1 if n_out == 1
        if s.shape[1] == 1:
            s = layers.squeeze(s, axes=[1])
        return s
