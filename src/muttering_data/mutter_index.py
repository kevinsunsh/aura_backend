#!/usr/bin/env python3
"""
音频文件索引映射
根据muttering_data目录下的文件名创建中文到文件路径的映射
"""

import os
from pathlib import Path
from enum import Enum
import random
# 获取当前文件所在目录
CURRENT_DIR = Path(__file__).parent

# 音频文件映射 - 中文文本到文件路径
MUTTERING_FILE_MAP = {
    "other": [
        {
            "text": "这个吗",
            "file": "zhe_ge_ma_float32.bin",
        },
        {
            "text": "怎么说呢",
            "file": "zen_me_shuo_ne_float32.bin",
        },
        {
            "text": "怎么说呢2",
            "file": "zen_me_shuo_ne_2_float32.bin",
        },
        {
            "text": "我想想",
            "file": "wo_xiang_xiang_float32.bin",
        },
        {
            "text": "我觉得",
            "file": "wo_jue_de_float32.bin",
        },
        {
            "text": "其实吧",
            "file": "qi_shi_ba_float32.bin",
        }
    ],
    "ask": [
        {
            "text": "在呢",
            "file": "zai_ne_float32.bin",
        }
    ],
    "ask_user": [
        {
            "text": "在吗",
            "file": "zai_ma_float32.bin",
        }
    ],
    "hello": [
        {
            "text": "你好呀",
            "file": "ni_hao_ya_float32.bin",
        },
        {
            "text": "你好",
            "file": "ni_hao_float32.bin",
        },
    ]
}

class MutteringType(Enum):
    OTHER = "other"
    ASK_USER = "ask_user"
    ASK = "ask"
    HELLO = "hello"

def get_muttering_file_path(muttering_type: MutteringType) -> str:
    """
    根据中文文本获取对应的音频文件路径
    
    Args:
        text: 中文文本
        
    Returns:
        音频文件的完整路径，如果找不到则返回None
    """
    if muttering_type.value in MUTTERING_FILE_MAP:
        filenames = MUTTERING_FILE_MAP[muttering_type.value]
        random_filename = random.choice(filenames)
        return str(CURRENT_DIR / random_filename["file"])
    return None
