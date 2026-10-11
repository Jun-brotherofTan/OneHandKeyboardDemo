

from paddle.fluid import layers


def index_sample(x, index):
    """Select input value according to index
    
    Arags：
        input: input matrix
        index: index matrix

    Returns:
        output

    >>> input
    [
        [1, 2, 3],
        [4, 5, 6]
    ]
    >>> index
    [
        [1, 2],
        [0, 1]
    ]
    >>> index_sample(input, index)
    [
        [2, 3],
        [4, 5]
    ]
    """
    x_s = x.shape
    dim = len(index.shape) - 1
    assert x_s[:dim] == index.shape[:dim]
    r_x = layers.reshape(x, shape=(-1, *x_s[dim:]))
    index = layers.reshape(index, shape=(index.shape[0], index.shape[1], 1))
    # generate arange index, shape like index
    # arr_index = layers.arange(start=0, end=layers.cast(layers.shape(x)[0], ), dtype=index.dtype)
    batch_size = layers.cast(layers.shape(index)[0], dtype=index.dtype)
    zero = layers.fill_constant(shape=[1], dtype=index.dtype, value=0)
    one = layers.fill_constant(shape=[1], dtype=index.dtype, value=1)
    arr_index = layers.unsqueeze(layers.range(zero, batch_size, one, dtype=index.dtype), [1, 2])

    arr_index = layers.expand_as(arr_index, index)
    #  genrate new index
    new_index = layers.concat([arr_index, index], -1)
    new_index = layers.reshape(new_index, (-1, 2))
    # get output
    out = layers.gather_nd(r_x, new_index)
    out = layers.reshape(out, (-1, x_s[-1] * 2))
    return out
