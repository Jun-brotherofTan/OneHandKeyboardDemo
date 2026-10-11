

from __future__ import print_function

import os
import six
import ast
import copy

import numpy as np
import paddle.fluid as fluid


def cast_fp32_to_fp16(exe, main_program):
    print("Cast parameters to float16 data format.")
    for param in main_program.global_block().all_parameters():
        if not param.name.endswith(".master"):
            param_t = fluid.global_scope().find_var(param.name).get_tensor()
            data = np.array(param_t)
            if param.name.find("layer_norm") == -1:
                param_t.set(np.float16(data).view(np.uint16), exe.place)
            master_param_var = fluid.global_scope().find_var(param.name + ".master")
            if master_param_var is not None:
                master_param_var.get_tensor().set(data, exe.place)


def init_checkpoint(exe, init_checkpoint_path, main_program, use_fp16=False):
    assert os.path.exists(init_checkpoint_path), "[%s] cann't be found." % init_checkpoint_path

    def existed_persitables(var):
        if not fluid.io.is_persistable(var):
            return False
        return os.path.exists(os.path.join(init_checkpoint_path, var.name))

    fluid.io.load_vars(exe, init_checkpoint_path, main_program=main_program, predicate=existed_persitables)
    print("Load model from {}".format(init_checkpoint_path))

    if use_fp16:
        cast_fp32_to_fp16(exe, main_program)


def init_pretraining_params(exe, pretraining_params_path, main_program, use_fp16=False):
    assert os.path.exists(pretraining_params_path), "[%s] cann't be found." % pretraining_params_path

    def existed_params(var):
        if not isinstance(var, fluid.framework.Parameter):
            return False
        return os.path.exists(os.path.join(pretraining_params_path, var.name))

    fluid.io.load_vars(exe, pretraining_params_path, main_program=main_program, predicate=existed_params)
    print("Load pretraining parameters from {}.".format(pretraining_params_path))

    if use_fp16:
        cast_fp32_to_fp16(exe, main_program)
