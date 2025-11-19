from types import SimpleNamespace
from typing import Any, Dict, List
import json
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from langgraph.graph import START, END, StateGraph
from langgraph.types import Command
from langgraph.config import get_stream_writer

from agents.states.speaking_state import SpeakingTaskState, PlannerResponse
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.prompt_manager.prompt_manager import is_downloadable
from loguru import logger
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from agents.prompts.speaking_prompt import FLASH_RESPONSE_PROMPT, VISUAL_RESPONSE_PROMPT, ACTION_RESPONSE_PROMPT, PLANNER_GOAL_PROMPT, PLANNER_DECISION_PROMPT
from utils.utils import start_performance_point
from langchain.chat_models import init_chat_model
from configuration.configuration import Configuration

reply_max_latency = 30  # s

def _generate_flash_response(state: SpeakingTaskState, config: RunnableConfig):
    """发送立即回复"""
    try:  
        logger.bind(tag="BASE").info(f"生成主动回复: {state}")
        # 使用LLM生成立即回复
        user_input = state.get("user_input", "")
        user_id = state.get("user_id", "")
        session_id = state.get("session_id", "")
        chat_model_config = get_chat_model_by_type("pfc_action_planner")
        chat_model = init_chat_model(
            model=chat_model_config.model_name,
            model_provider=chat_model_config.model_provider,
            api_key=chat_model_config.api_key,
            base_url=chat_model_config.api_base
        )
        # 构建提示词（加入最近观察，避免重复观察）
        image_url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{session_id}/view_data/look.jpg"
        system_content = [SystemMessage(content=FLASH_RESPONSE_PROMPT)]
        
        # 检查URL是否可下载，只有可下载时才添加视觉画面
        if is_downloadable(image_url):
            system_content.append(SystemMessage(content=[
                {
                    "image_url":
                        {
                            "url": image_url
                        },
                    "type":"image_url"
                },
                {
                    "text": "这是Aura眼前看到的画面",
                    "type": "text"
                }
            ]))
        else:
            logger.warning(f"图片URL不可访问，跳过添加视觉画面: {image_url}")
        
        messages = system_content + [HumanMessage(content=f"用户输入: {user_input}")]
        writer = get_stream_writer()
        # tag_configs = {
        #     "<need_planner_response>": "planner_response"
        # }
        # tag_markers = list(tag_configs.keys())
        # buffer = ""
        # 生成立即回复
        final_response = ""
        writer({"chat_start": ""})
        for chunk in chat_model.stream(messages, extra_body={"thinking": {"type": "disabled"}}):
            if hasattr(chunk, 'content'):
                text = chunk.content
                writer({"chat_streaming": text})
                final_response += text
                # def _find_next_tag(segment: str):
                #     matched_tag = None
                #     matched_index = len(segment)
                #     for tag in tag_markers:
                #         idx = segment.find(tag)
                #         if idx != -1 and idx < matched_index:
                #             matched_index = idx
                #             matched_tag = tag
                #     return matched_tag, matched_index

                # def _longest_partial_suffix(segment: str) -> int:
                #     max_len = 0
                #     for tag in tag_markers:
                #         for prefix_len in range(1, len(tag)):
                #             if segment.endswith(tag[:prefix_len]):
                #                 max_len = max(max_len, prefix_len)
                #     return max_len

                # while True:
                #     matched_tag, matched_index = _find_next_tag(buffer)
                #     if not matched_tag:
                #         break
                #     prefix_text = buffer[:matched_index]
                #     if prefix_text:
                #         writer({"chat_streaming": prefix_text})
                #         final_response += prefix_text
                #     buffer = buffer[matched_index + len(matched_tag):]
                #     return Command(goto=tag_configs[matched_tag], update={
                #         "user_input": user_input,
                #         "final_response": final_response
                #     })

                # keep_len = _longest_partial_suffix(buffer)
                # flush_len = len(buffer) - keep_len
                # if flush_len > 0:
                #     flush_text = buffer[:flush_len]
                #     writer({"chat_streaming": flush_text})
                #     final_response += flush_text
                #     buffer = buffer[flush_len:]
        # if buffer:
        #     writer({"chat_streaming": buffer})
        #     final_response += buffer
        writer({"chat_end": final_response})
        return {
            "final_response": final_response
        }
    except Exception as e:
        logger.error(f"生成主动回复时出错: {str(e)}")
        return Command(goto=END, update={
            "speaking_response": "error"
        })            

# def _generate_visual_response(state: SpeakingTaskState, config: RunnableConfig):
#     """发送视觉补充回复"""
#     try:
#         user_input = state.get("user_input", "")
#         flash_response = state.get("final_response") or ""
#         chat_model_config = get_chat_model_by_type("vlm")
#         chat_model = init_chat_model(
#             model=chat_model_config.model_name,
#             model_provider=chat_model_config.model_provider,
#             api_key=chat_model_config.api_key,
#             base_url=chat_model_config.api_base
#         )
#         output_parser = RemoveFunctionCallOutputParser(pydantic_object=VisualResponse)
#         structured_llm = chat_model | output_parser
#         format_instructions = output_parser.get_format_instructions()
#         system_instructions = VISUAL_RESPONSE_PROMPT.format(
#             user_input=user_input,
#             flash_response=flash_response
#         )
#         messages = [SystemMessage(content=system_instructions), HumanMessage(content=[
#             {
#                 "image_url":
#                     {
#                         "url":"https://aura-view-eye.tos-cn-beijing.volces.com/assets/2342342334/0031312f-49f2-0fa3-9a5f-b18815278e2d/view_data/look.jpg"
#                     },
#                 "type":"image_url"
#             },
#             {
#                 "text": "这是你看到的画面",
#                 "type": "text"
#             }
#         ])]
#         final_response = flash_response
#         visual_response_output = chat_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})

#         return {
#             "speaking_response": "finished",
#             "final_response": final_response,
#             "visual_response": visual_response_output
#         }
#     except Exception as e:
#         logger.error(f"生成视觉补充回复时出错: {str(e)}")
#         return Command(goto=END, update={
#             "speaking_response": "error"
#         })

def _decide_next_node(state: SpeakingTaskState, config: RunnableConfig):
    """决定下一个节点"""
    try:
        user_input = state.get("user_input", "")
        flash_response = state.get("final_response") or ""
        chat_model_config = get_chat_model_by_type("pfc_action_planner")
        chat_model = init_chat_model(
            model=chat_model_config.model_name,
            model_provider=chat_model_config.model_provider,
            api_key=chat_model_config.api_key,
            base_url=chat_model_config.api_base
        )
        system_instructions = PLANNER_DECISION_PROMPT.format(
            user_input=user_input,
            flash_response=flash_response
        )
        messages = [SystemMessage(content=system_instructions)]
        planner_response_output = chat_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
        json_output = json.loads(planner_response_output.content)
        need_planner_response = json_output.get("need_planner_response", False)
        if need_planner_response:
            return Command(goto="planner_response")
        return Command(goto=END)
    except Exception as e:
        logger.error(f"决定下一个节点时出错: {str(e)}")
        return Command(goto=END)

def _generate_planner_response(state: SpeakingTaskState, config: RunnableConfig):
    """发送视觉补充回复"""
    try:
        session_id = state.get("session_id", "")
        user_id = state.get("user_id", "")
        import requests
        response = requests.post(
            "https://sd2ruht27399ulo39rt0g.apigateway-cn-beijing.volceapi.com/v1/save_view",
            json={
                "chat_id": session_id,
                "user_id": user_id
            }
        )
        user_input = state.get("user_input", "")
        flash_response = state.get("final_response") or ""
        chat_model_config = get_chat_model_by_type("vlm")
        chat_model = init_chat_model(
            model="doubao-seed-1-6-vision-250815",
            model_provider=chat_model_config.model_provider,
            api_key=chat_model_config.api_key,
            base_url=chat_model_config.api_base
        )
        output_parser = RemoveFunctionCallOutputParser(pydantic_object=PlannerResponse)
        structured_llm = chat_model | output_parser
        format_instructions = output_parser.get_format_instructions()
        system_instructions = PLANNER_GOAL_PROMPT.format(
            user_input=user_input,
            flash_response=flash_response
        )
        image_url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{session_id}/save_view_info/look.jpg"
        
        # 检查URL是否可下载，只有可下载时才添加视觉画面
        human_content = []
        if is_downloadable(image_url):
            human_content = [
                {
                    "image_url":
                        {
                            "url": image_url
                        },
                    "type":"image_url"
                },
                {
                    "text": "这是你看到的画面",
                    "type": "text"
                }
            ]
        else:
            logger.warning(f"图片URL不可访问，跳过添加视觉画面: {image_url}")
            human_content = [{"text": "这是你看到的画面", "type": "text"}]
        
        messages = [SystemMessage(content=system_instructions), HumanMessage(content=human_content)]
        planner_response_output = chat_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
        writer = get_stream_writer()
        json_output = json.loads(planner_response_output.content)
        writer(json_output)
        return Command(goto=END)
    except Exception as e:
        logger.error(f"生成视觉补充回复时出错: {str(e)}")
        return Command(goto=END, update={
            "speaking_response": "error"
        })

# 创建前台状态机图
chat_agent_builder = StateGraph(SpeakingTaskState, config_schema=Configuration)

# 添加节点
chat_agent_builder.add_node("flash_response", _generate_flash_response)
chat_agent_builder.add_node("planner_decision", _decide_next_node)
# builder.add_node("visual_response", _generate_visual_response)
chat_agent_builder.add_node("planner_response", _generate_planner_response)
# 添加边
chat_agent_builder.add_edge(START, "flash_response")
chat_agent_builder.add_edge("flash_response", "planner_decision")

# 编译graph供外部调用
speaking_graph = chat_agent_builder.compile()

# ==========================================
# 测试代码
# ==========================================

if __name__ == "__main__":
    test_cases = [
        {
            "description": "普通快速回复",
            "user_input": "你好，很高兴见到你",
            "expected_goto": END,
        },
        {
            "description": "命中视觉补充标签",
            "user_input": "你看看你面前有什么",
            "expected_goto": "visual_response",
        },
        {
            "description": "命中视觉补充标签",
            "user_input": "你看到前面的那个沙发了么？",
            "expected_goto": "visual_response",
        },
        {
            "description": "命中行动补充标签",
            "user_input": "你到前面的沙发边上去",
            "expected_goto": "action_response",
        },
        {
            "description": "命中行动补充标签",
            "user_input": "向前走两步",
            "expected_goto": "action_response",
        },
    ]

    for case in test_cases:
        outputs: List[str] = []

        def writer(payload: Dict[str, Any]):
            outputs.append(payload.get("content", ""))

        print(f"\n=== 测试场景：{case['description']} ===")
        thread_config = {
            "configurable": {
                "thread_id": f"test_thread_{case['description']}"
            },
            "recursion_limit": 10
        }
        events: List[Dict[str, Any]] = []
        try:
            for idx, event in enumerate(
                speaking_graph.stream(
                    SpeakingTaskState(user_input=case["user_input"]),
                    thread_config,
                    stream_mode="custom"
                )
            ):
                print(f"\n---- Event #{idx} ----")
                print(event)
                events.append(event)
        except Exception as exc:
            print(f"测试执行出错: {exc}")
            continue

