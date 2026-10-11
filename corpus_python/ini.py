

from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import paddle
# paddle_version = [int(i) for i in paddle.__version__.split('.')]
# if paddle_version[1] < 7:
#     raise RuntimeError('paddle-ernie requires paddle 1.7+, got %s' %
#                        paddle.__version__)

from ddparser.ernie.modeling_ernie import ErnieModel
from ddparser.ernie.modeling_ernie import (ErnieModelForSequenceClassification,
                                           ErnieModelForTokenClassification,
                                           ErnieModelForQuestionAnswering,
                                           ErnieModelForPretraining)

from ddparser.ernie.tokenizing_ernie import ErnieTokenizer, ErnieTinyTokenizer
