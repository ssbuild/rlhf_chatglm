# @Time    : 2023/4/2 22:49
# @Author  : tk
# @FileName: infer_finetuning
import os
import re
from collections import OrderedDict

import torch
from deep_training.data_helper import ModelArguments, TrainingArguments, DataArguments
from transformers import HfArgumentParser,PreTrainedTokenizer

from config.rlhf_config import get_deepspeed_config
from data_utils import train_info_args, NN_DataHelper
from models import MyPPOTransformer, load_in_8bit,LoraArguments,PPOArguments,ChatGLMTokenizer,ChatGLMConfig

deep_config = get_deepspeed_config()

if __name__ == '__main__':
    train_info_args['seed'] = None
    parser = HfArgumentParser((ModelArguments, TrainingArguments, DataArguments, LoraArguments, PPOArguments))
    model_args, training_args, data_args, _,_ = parser.parse_dict(train_info_args)

    dataHelper = NN_DataHelper(model_args, training_args, data_args)
    tokenizer, _, _, _ = dataHelper.load_tokenizer_and_config(tokenizer_class_name=ChatGLMTokenizer,
                                                                   config_class_name=ChatGLMConfig)
    assert tokenizer.eos_token_id == 130005

    ckpt_dir = './best_ckpt'
    config = ChatGLMConfig.from_pretrained(ckpt_dir)

    if deep_config is None:
        train_weight = './best_ckpt/last-v3.ckpt'
        assert os.path.exists(train_weight)
        pl_model = MyPPOTransformer.load_from_checkpoint(train_weight, config=config, model_args=model_args,
                                                      training_args=training_args, strict=False)
    else:
        # 建议直接使用转换脚本命令 支持 deepspeed stage 0,1,2,3， 生成 ./best_ckpt/last.ckpt/best.pt 权重文件
        # cd best_ckpt/last.ckpt
        # python zero_to_fp32.py . best.pt
        train_weight = './best_ckpt/last.ckpt/best.pt'

        # deepspeed stage 0,1,2 不必须执行上面命令
        # train_weight = './best_ckpt/last.ckpt/checkpoint/mp_rank_00_model_states.pt'

        assert os.path.exists(train_weight)
        weights_dict = torch.load(train_weight)
        weights_dict_new = OrderedDict()
        for k, v in (weights_dict['module'] if 'module' in weights_dict else weights_dict).items():
            weights_dict_new[re.sub(r'_forward_module\.', '', k)] = v
        pl_model = MyPPOTransformer(config=config, model_args=model_args, training_args=training_args)
        pl_model.load_state_dict(state_dict=weights_dict_new, strict=False)

    model = pl_model.get_llm_model()

    # 保存hf权重
    # config.save_pretrained('convert/')

    # 保存sft p-tuning-v2 权重
    #  pl_model.save_sft_weight('convert/pytorch_model_sft_ptv2.bin')

    # 保存sft权重
    # pl_model.save_sft_weight('convert/pytorch_model_sft.bin')



    if load_in_8bit:
        pl_model.eval().cuda()
    else:
        pl_model.eval().half().cuda()


    model = pl_model.get_llm_model()

    text = "哪些食物对糖尿病患者有好处?"
    response, history = model.chat(query=text, tokenizer=tokenizer, max_length=2048,
                                      eos_token_id=config.eos_token_id,
                                      do_sample=True, top_p=0.7, temperature=0.95, )
    print('input', text)
    print('output', response)