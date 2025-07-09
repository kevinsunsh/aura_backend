import json
import uuid
import asyncio
import time
from datetime import datetime
from typing import Literal, Optional, Tuple, Dict, Any, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from langgraph.constants import Send
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.config import get_stream_writer

from agents.states.muttering_state import MutteringTaskState
from agents.configuration import Configuration, get_chat_model_by_type
import logging
from agents.prompts.muttering_prompt import (
    MUTTERING_CHOOSER_PROMPT
)
from agents.aura_memory.message_store import Message
from utils.utils import start_performance_point, end_performance_point
from agents.graphs.todo_mock_func import (
    _get_persona_text
)
from agents.task_manager import TaskManager, TaskType, TaskStateType
# from sentence_transformers import SentenceTransformer
# from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)
# sentence_transformer_model = SentenceTransformer('BAAI/bge-small-zh-v1.5')

async def _generate_muttering(state: MutteringTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:
        if TaskManager.get_instance().get_task_state(TaskType.MUTTERING) == TaskStateType.STOPPED:
            return Command(goto=END, update={
                "muttering_response": "stopped"
            })
        if TaskManager.get_instance().get_task_state(TaskType.MUTTERING) == TaskStateType.PAUSED:
            return Command(goto=END, update={
                "muttering_response": "paused"
            })
        # return Command(goto=END, update={
        #     "muttering_response": "paused"
        # })
        observing_task_shared_data = await TaskManager.get_instance().get_task_shared_data(TaskType.OBSERVING)
        last_bot_message_time = observing_task_shared_data.get("last_bot_message_time", None)
        last_user_message_time = observing_task_shared_data.get("last_user_message_time", None)
        last_bot_message_content = observing_task_shared_data.get("last_bot_message_content", None)
        last_user_message_content = observing_task_shared_data.get("last_user_message_content", None)
        if last_bot_message_time is None or last_user_message_time is None:
            return Command(goto=END, update={
                "muttering_response": "skipped"
            })
        if last_bot_message_time > last_user_message_time:
            return Command(goto=END, update={
                "muttering_response": "skipped"
            })
        chat_model = get_chat_model_by_type("basic")
        prompt = MUTTERING_CHOOSER_PROMPT.format(
            user_input=last_user_message_content
        )
        response = await chat_model.ainvoke([
            SystemMessage(content=prompt)
        ],
        extra_body={"thinking": {"type": "disabled"}})
        muttering_type = response.content
        # sentences = [
        #     last_user_message_content,
        #     "打招呼",
        #     "问在不在"
        # ]
        # # 获取句子向量
        # embeddings = sentence_transformer_model.encode(sentences)

        # # 计算相似度
        # similarity_matrix = cosine_similarity(embeddings)
        # # INSERT_YOUR_CODE
        # def get_max_similarity_except_self(similarity_matrix, idx):
        #     """
        #     返回指定索引对应的相似度矩阵中，除自身外的最大相似度值和索引
        #     :param similarity_matrix: 相似度矩阵 (numpy.ndarray)
        #     :param idx: 当前行的索引
        #     :return: (最大相似度值, 最大相似度对应的索引)
        #     """
        #     import numpy as np
        #     row = similarity_matrix[idx].copy()
        #     row[idx] = -np.inf  # 排除自身
        #     max_idx = np.argmax(row)
        #     max_value = row[max_idx]
        #     return max_value, max_idx

        # # 以用户消息为基准，获取其与其他候选句的最大相似度
        # muttering_type_idx = 0  # 用户消息在sentences中的索引
        # max_sim, max_sim_idx = get_max_similarity_except_self(similarity_matrix, muttering_type_idx)
        # if max_sim > 0.5:
        #     if max_sim_idx == 1:
        #         muttering_type = "hello"
        #     elif max_sim_idx == 2:
        #         muttering_type = "ask"
        # else:
        #     muttering_type = "other"
       
        return Command(goto=END, update={
            "muttering_response": "finished",
            "muttering_content": muttering_type
        })
    except Exception as e:
        logger.error(f"生成回复时出错: {str(e)}")
        return Command(goto=END, update={
            "muttering_response": "error"
        })            

# 创建前台状态机图
builder = StateGraph(MutteringTaskState, config_schema=Configuration)

# 添加节点
builder.add_node("generate_muttering", _generate_muttering)

# 添加边
builder.add_edge(START, "generate_muttering")

