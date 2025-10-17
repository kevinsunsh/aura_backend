"""
完整的 Agent 流程图实现
包含目标分析、行为规划、执行等待、结果验证和继续规划
"""
import re
import cv2
import json
import requests
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain.chat_models import init_chat_model
from langgraph.constants import Send
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from agents.states.agent_flow_state import AgentFlowState, NextAction, FeedbackAnalysis
from agents.prompts.agent_flow_prompts import (
    ACTION_PLANNING_PROMPT,
    FEEDBACK_ANALYSIS_PROMPT,
    EXAMINE_PROMPT
)
from loguru import logger
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.message_store import MessageStore
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from agents.agent_memory.prompt_manager.scene_iteams.manager import DBManager as SceneItemEntryManager
from agents.agent_memory.configuration.config import EmbeddingModel
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
from agents.agent_memory.prompt_manager.prompt_manager import PromptManager, GenerationType, GenerationOptions
from utils.utils import safe_async_call

def format_chat_history(chat_history: List[Dict[str, Any]]) -> str:
    """格式化聊天记录"""
    if not chat_history:
        return "暂无聊天记录"
    
    formatted = []
    for msg in chat_history:
        formatted.append(f"消息类型:{msg.m_type}, 角色:{msg.role}, 内容:{msg.content}")
    
    return "\n".join(formatted)

def format_items(items: List[Dict[str, Any]]) -> str:
    """格式化物品列表"""
    if not items:
        return "暂无物品"
    formatted = []
    formatted.append("你的周围有以下物品：")
    for item in items:
        if isinstance(item["actions"], dict):
            actions_str = ",".join([action for actions in item.get("actions", {}).values() for action in actions])
        if isinstance(item["actions"], list):
            actions_str = ",".join([action for action in item.get("actions", [])])
        line = f"ID={item.get('item_id')}, 描述={item.get('description') or ''}"
        if actions_str:
            line += f", 可接受动作=[{actions_str}]"
        else:
            line += f", 可接受动作=[move_to]"
        formatted.append(line)
    formatted.append("注意：ID只能用于作为动作目标参数，不能在任何其他地方使用。如果你需要在其他地方引用该物品，请使用该物品的描述内容。")
    return "\n".join(formatted)

def deproject_screen_to_world(
    screen_pos: np.ndarray,           # [x, y] 像素坐标
    view_rect: tuple,                 # (min_x, min_y, width, height)
    inv_view_matrix: np.ndarray,      # 4x4 逆视图矩阵 (world = inv_view * camera)
    inv_projection_matrix: np.ndarray # 4x4 逆投影矩阵 (camera = inv_proj * proj)
) -> tuple[np.ndarray, np.ndarray]:
    """
    将屏幕坐标反向投影到世界空间中的射线起点和方向。

    Args:
        screen_pos: [x, y] 屏幕像素坐标
        view_rect: (min_x, min_y, width, height) 视口区域
        inv_view_matrix: 4x4 逆视图矩阵 (将相机空间转为世界空间)
        inv_projection_matrix: 4x4 逆投影矩阵 (将投影空间转为相机空间)

    Returns:
        world_origin: 世界空间中射线起点（即相机位置）
        world_direction: 世界空间中射线方向（单位向量）
    """
    # 1. 转换为整数像素坐标
    pixel_x = int(screen_pos[0])
    pixel_y = int(screen_pos[1])

    # 2. 归一化到 [0, 1] 范围内
    min_x, min_y, width, height = view_rect
    normalized_x = (pixel_x - min_x) / width
    normalized_y = (pixel_y - min_y) / height

    # 3. 映射到 [-1, 1] 的投影空间（NDC）
    screen_space_x = (normalized_x - 0.5) * 2.0
    screen_space_y = (1.0 - normalized_y - 0.5) * 2.0  # 注意 Y 轴翻转

    # 4. 构造投影空间中的两个点（z=1 和 z=0.01）
    ray_start_proj = np.array([screen_space_x, screen_space_y, 1.0, 1.0])  # near plane
    ray_end_proj   = np.array([screen_space_x, screen_space_y, 0.01, 1.0])  # far point

    # 5. 应用逆投影矩阵（投影空间 → 相机空间）
    h_ray_start_view = inv_projection_matrix @ ray_start_proj
    h_ray_end_view   = inv_projection_matrix @ ray_end_proj

    # 6. 除以 w 分量，得到相机空间坐标
    if h_ray_start_view[3] != 0:
        ray_start_view = h_ray_start_view[:3] / h_ray_start_view[3]
    else:
        ray_start_view = h_ray_start_view[:3]

    if h_ray_end_view[3] != 0:
        ray_end_view = h_ray_end_view[:3] / h_ray_end_view[3]
    else:
        ray_end_view = h_ray_end_view[:3]

    # 7. 计算相机空间中的方向
    ray_dir_view = ray_end_view - ray_start_view
    ray_dir_view = ray_dir_view / np.linalg.norm(ray_dir_view)

    # 8. 变换到世界空间
    ray_start_world = inv_view_matrix @ np.append(ray_start_view, 1.0)
    ray_start_world = ray_start_world[:3] / ray_start_world[3] if ray_start_world[3] != 0 else ray_start_world[:3]

    ray_dir_world = inv_view_matrix @ np.append(ray_dir_view, 0.0)
    ray_dir_world = ray_dir_world[:3] / np.linalg.norm(ray_dir_world)

    return ray_start_world, ray_dir_world

def world_position_from_depth(
    screen_pos: np.ndarray,
    view_rect: tuple,
    inv_view_matrix: np.ndarray,
    inv_projection_matrix: np.ndarray,
    camera_position: np.ndarray,
    camera_forward: np.ndarray,
    depth_value: float,
):
    """
    基于射线 + 深度余弦校正计算最终世界坐标。

    约定：depth_value 为相机前向方向（camera_forward）上的线性深度(米)，
    即常见的相机空间 Z 深度。如果是其它定义，请先转换到该定义。
    """
    origin, direction = deproject_screen_to_world(
        screen_pos, view_rect, inv_view_matrix, inv_projection_matrix
    )
    # 使用更准确的相机位置作为射线起点
    cam_pos = np.asarray(camera_position, dtype=np.float64)
    cam_fwd = np.asarray(camera_forward, dtype=np.float64)
    cam_fwd = cam_fwd / (np.linalg.norm(cam_fwd) if np.linalg.norm(cam_fwd) > 0 else 1.0)

    correction_factor = float(np.dot(direction, cam_fwd))
    if abs(correction_factor) < 1e-6:
        raise ValueError("Ray direction is nearly perpendicular to camera forward vector.")

    euclidean_distance = float(depth_value) / correction_factor
    world_position = cam_pos + direction * euclidean_distance
    return world_position

def screen_distance_to_world_distance(
    screen_pos1: np.ndarray,
    screen_pos2: np.ndarray,
    depth1: float,
    depth2: float,
    view_rect: tuple,
    inv_view_matrix: np.ndarray,
    inv_projection_matrix: np.ndarray,
    camera_position: np.ndarray,
    camera_forward: np.ndarray,
) -> float:
    """
    根据屏幕空间的两个点和对应的深度值，计算它们在世界空间中的距离。
    
    Args:
        screen_pos1: 第一个屏幕点坐标 [x, y]
        screen_pos2: 第二个屏幕点坐标 [x, y]
        depth1: 第一个点的深度值（米）
        depth2: 第二个点的深度值（米）
        view_rect: 视口区域 (min_x, min_y, width, height)
        inv_view_matrix: 4x4 逆视图矩阵
        inv_projection_matrix: 4x4 逆投影矩阵
        camera_position: 相机位置
        camera_forward: 相机前向向量
        
    Returns:
        两个点在世界空间中的欧几里得距离（米）
    """
    # 将两个屏幕点转换为世界坐标
    world_pos1 = world_position_from_depth(
        screen_pos1, view_rect, inv_view_matrix, inv_projection_matrix,
        camera_position, camera_forward, depth1
    )
    
    world_pos2 = world_position_from_depth(
        screen_pos2, view_rect, inv_view_matrix, inv_projection_matrix,
        camera_position, camera_forward, depth2
    )
    
    # 计算欧几里得距离
    distance = np.linalg.norm(world_pos2 - world_pos1)
    return float(distance)

def is_point_in_bbox(point, bbox_min, bbox_max):
    """检查点是否在包围盒内"""
    return (bbox_min[0] <= point[0] <= bbox_max[0] and
            bbox_min[1] <= point[1] <= bbox_max[1] and
            bbox_min[2] <= point[2] <= bbox_max[2])

def find_matching_item(pos, existing_items):
    """在现有物品中查找匹配的物品（同类型且在bbox内）"""
    for item in existing_items:
        item_dict = item.to_dict() if hasattr(item, 'to_dict') else item
        # 计算现有物品的bbox
        ex_bb_x = float(item_dict.get('world_bb_x', item_dict.get('world_pos_x', 0.0)))
        ex_bb_y = float(item_dict.get('world_bb_y', item_dict.get('world_pos_y', 0.0)))
        ex_bb_z = float(item_dict.get('world_bb_z', item_dict.get('world_pos_z', 0.0)))
        ex_bb_w = float(item_dict.get('world_bb_w', 0.0))
        ex_bb_h = float(item_dict.get('world_bb_h', 0.0))
        ex_bb_d = float(item_dict.get('world_bb_d', 0.0))
        
        bbox_min = [ex_bb_x, ex_bb_y, ex_bb_z]
        bbox_max = [ex_bb_x + ex_bb_w, ex_bb_y + ex_bb_h, ex_bb_z + ex_bb_d]
        
        if is_point_in_bbox(pos, bbox_min, bbox_max):
            return item_dict
    return None

# def analyze_goals(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
#     """分析目标节点"""
#     try:
#         # 获取聊天模型
#         planner = get_chat_model_by_type("pfc_action_planner")
#         # 格式化输入数据
#         chat_id = state.get("chat_id", "")
#         user_id = state.get("user_id", "")
#         prompt_manager = PromptManager.get_instance()
#         chat_history = MessageStore.get_instance().get_messages_in_recent_time(milliseconds=120*1000, chat_id=chat_id, m_type="text")
#         char_instance_info = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(user_id, chat_id)
#         view_np = np.array(char_instance_info.view_matrix, dtype=float)
#         view_np = view_np.reshape(4, 4)
#         view_np = np.transpose(view_np)
#         scene_id = char_instance_info.current_scene_id
#         inv_view_matrix = np.linalg.inv(view_np)
#         character_world_pos = np.dot(inv_view_matrix, np.array([0, 0, 0, 1]))[:3]
#         character_world_pos = character_world_pos.tolist()
#         character_world_pos[2] = 0.5
#         candidate_items = SceneItemEntryManager().get_scene_items_by_distance(character_world_pos, 1000, scene_id, ["Nova", "Zoe", "Eva", "Nova老", "nova", "MHC_Talker"])
#         chat_history_str = format_chat_history(chat_history)
#         previous_goal_str = state.get("action_goal", "")
#         scene_description = format_items(candidate_items)
#         planner_model = init_chat_model(
#             model=planner.model_name,
#             model_provider=planner.model_provider,
#             api_key=planner.api_key,
#             base_url=planner.api_base
#         )
#         output_parser = RemoveFunctionCallOutputParser(pydantic_object=ActionsGoal)
#         structured_llm = planner_model | output_parser
#         goal_format = output_parser.get_format_instructions()
#         # Format system instructions for plan generation
#         system_instructions = GOAL_ANALYSIS_PROMPT.format(
#             character_description=prompt_manager.character.description,
#             scene_description=scene_description,
#             chat_history=chat_history_str,
#             previous_goal=previous_goal_str,
#             format=goal_format
#         )
#         # Generate plan
#         actions_plan: ActionsGoal = structured_llm.invoke([
#             SystemMessage(content=system_instructions)
#         ])
#         update_data = {
#             "action_goal": actions_plan.action_goal,
#             "related_environment_description": actions_plan.related_environment_description,
#             "chat_history": chat_history_str,
#             "scene_id": prompt_manager.scene_info.scene_id,
#             "character_description": prompt_manager.character.description
#         }
#         return update_data
#     except Exception as e:
#         logger.error(f"分析目标时出错: {str(e)}")
#         return Command(goto=END)

def prepare_data(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
    """准备数据节点"""
    try:
        action_goal = state.get("action_goal", "")
        embedding_model = EmbeddingModel(
            model_name="doubao-embedding-large-text-250515",
            api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
            api_base="https://ark.cn-beijing.volces.com/api/v3",
        )
        desc_vec = embedding_model.embed(action_goal)
        user_id = state.get("user_id", "")
        chat_id = state.get("chat_id", "")
        scene_id = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(user_id, chat_id).current_scene_id
        character_description = PromptManager.get_instance().character.description
        bot_name = PromptManager.get_instance().character.name
        items = SceneItemEntryManager().search_items_by_description_vector(scene_id, desc_vec, top_k=20)
        important_items = SceneItemEntryManager().get_scene_items_by_type(scene_id, "", ["Nova", "Zoe", "Eva", "Nova老", "nova", "MHC_Talker"])
        items.extend(important_items)
        related_items_str = format_items(items)
        update_data = {
            "related_items": related_items_str,
            "character_description": character_description,
            "scene_id": scene_id,
            "bot_name": bot_name,
            "current_result": "",
            "action_step_count": 0
        }
        return update_data
    except Exception as e:
        logger.bind(tag="BASE").info(f"准备数据时出错: {str(e)}")
        return Command(goto=END)

def plan_action(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
    """行为规划节点"""
    try:
        # 获取聊天模型
        planner = get_chat_model_by_type("pfc_action_planner")
        # 格式化输入数据
        chat_id = state.get("chat_id", "")
        action_goal = state.get("action_goal", "")
        character_description = state.get("character_description", "")
        related_items = state.get("related_items", "")
        goal_timestamp = state.get("goal_timestamp", 0)
        action_step_count = state.get("action_step_count")
        current_timestamp = int(datetime.now().timestamp() * 1000)
        duration = current_timestamp - goal_timestamp
        chat_history = MessageStore.get_instance().get_messages_in_recent_time(milliseconds=duration, chat_id=chat_id, m_type="action")
        chat_history_str = format_chat_history(chat_history)
        # logger.bind(tag="BASE").info(f"related_items_str: {related_items_str}")
        planner_model = init_chat_model(
            model=planner.model_name,
            model_provider=planner.model_provider,
            api_key=planner.api_key,
            base_url=planner.api_base
        )
        output_parser = RemoveFunctionCallOutputParser(pydantic_object=NextAction)
        structured_llm = planner_model | output_parser
        plan_format = output_parser.get_format_instructions()
        # Format system instructions for plan generation
        system_instructions = ACTION_PLANNING_PROMPT.format(
            character_description=character_description,
            current_goal=action_goal,
            action_history=chat_history_str,
            related_items=related_items,
            format=plan_format
        )
        # logger.bind(tag="BASE").info(f"plan_action system instructions: {system_instructions}")
        # Generate plan
        next_action: NextAction = structured_llm.invoke([
            SystemMessage(content=system_instructions)
        ],
        extra_body={"thinking": {"type": "disabled"}})
        update_data = {
            "action_target_id": next_action.action_target_id,
            "action_cmd": next_action.action_cmd,
            "look_for_item_type": next_action.look_for_item_type.replace(" ", "_"),
            "look_for_item_description": next_action.look_for_item_description,
            "next_action_reasoning": next_action.next_action_reasoning,
            "current_result": "",
            "action_step_count": action_step_count + 1
        }
        return update_data
    except Exception as e:
        logger.bind(tag="BASE").info(f"规划行为时出错: {str(e)}")
        return Command(goto=END)

def look_for(user_id: str, chat_id: str, scene_id: str, item_type: str, action_target_description: str) -> Dict[str, Any]:
    """观察节点"""
    try:
        chat_model = get_chat_model_by_type("vlm")
        url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{chat_id}/view_data/look.jpg"
        cam_url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{chat_id}/view_data/cam.json"
        depth_url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{chat_id}/view_data/depth.png"
        messages=[{
            "role": "user",
            "content": [{
                "type": "image_url",  # 图片输入
                "image_url": {"url": url}
            }, {
                "type": "text",  # 文本提示
                "text": EXAMINE_PROMPT.format(target_description=action_target_description)
            }]
        }]
        response = chat_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
        response_text = response.content
        logger.bind(tag="BASE").info(f"look_for response: {response_text}")
        m = re.search(r"<bbox>\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*</bbox>", response_text)
        node = None
        if m:
            raw_x1, raw_y1, raw_x2, raw_y2 = map(int, m.groups())
            print(raw_x1, raw_y1, raw_x2, raw_y2)  # 351 658 496 783
            x1 = int(raw_x1 * 512 / 1024)
            y1 = int(raw_y1 * 512 / 1024)
            x2 = int(raw_x2 * 512 / 1024)
            y2 = int(raw_y2 * 512 / 1024)
            print(f"正在下载 cam.json: {cam_url}")
            resp_cam = requests.get(cam_url, timeout=30)
            resp_cam.raise_for_status()
            cam_data = json.loads(resp_cam.content.decode('utf-8'))
            print("cam.json 下载并解析完成")
            print(f"正在下载 depth.png: {depth_url}")
            resp_depth = requests.get(depth_url, timeout=30)
            resp_depth.raise_for_status()
            depth_content = resp_depth.content
            if depth_content is None or len(depth_content) == 0:
                raise RuntimeError("depth.png 内容为空")
            print("depth.png 下载完成（内存）")
            # 使用 OpenCV 解码 PNG 深度图（保持位深/通道）
            depth_buf = np.frombuffer(depth_content, dtype=np.uint8)
            depth_img = cv2.imdecode(depth_buf, cv2.IMREAD_UNCHANGED)
            if depth_img is None:
                raise RuntimeError("depth.png 解码失败")
            
            proj = cam_data.get('projection_matrix')
            view_m = cam_data.get('view_matrix')
            proj_matrix = np.array([proj[i*4:(i+1)*4] for i in range(4)], dtype=np.float64).transpose()
            view_matrix = np.array([view_m[i*4:(i+1)*4] for i in range(4)], dtype=np.float64).transpose()
            inv_proj_matrix = np.linalg.inv(proj_matrix)
            inv_view_matrix = np.linalg.inv(view_matrix)
            camera_position = inv_view_matrix[:3, 3]
            cam_fwd_h = inv_view_matrix @ np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float64)
            camera_forward = cam_fwd_h[:3]
            n = np.linalg.norm(camera_forward)
            if n > 0:
                camera_forward = camera_forward / n
            # 期望格式：32位色，float 分4字节压入 RGBA
            # OpenCV 解码返回通道顺序为 BGRA（若有4通道）
            if depth_img.ndim == 3 and depth_img.shape[2] == 4:
                # 提取通道（B,G,R,A）
                b = depth_img[:, :, 0]
                g = depth_img[:, :, 1]
                r = depth_img[:, :, 2]
                a = depth_img[:, :, 3]
                # 还原为小端序 float32 字节序列 [R,G,B,A]
                rgba_bytes = np.stack([r, g, b, a], axis=-1).astype(np.uint8)
                flat_bytes = rgba_bytes.reshape(-1, 4)
                # 通过视图转换为 float32，再 reshape 回原尺寸
                depth_f32 = flat_bytes.view(np.float32).reshape(depth_img.shape[0], depth_img.shape[1])
                depth_linear = depth_f32.astype(np.float64)
                detection_depth_region = depth_linear[y1:y2, x1:x2]
                # 过滤掉无效的深度值（通常为0或负数）
                valid_depths = detection_depth_region[detection_depth_region > 0]
                if len(valid_depths) > 0:
                    depth_value = float(np.median(valid_depths))
                # 视口矩形
                img_w = 512
                img_h = 512
                view_rect = (0, 0, img_w, img_h)
                # 逆视图矩阵
                inv_view_matrix = np.linalg.inv(view_matrix)
                # 逆投影矩阵
                inv_proj_matrix = np.linalg.inv(proj_matrix)
                # 相机位置
                camera_position = inv_view_matrix[:3, 3]
                # 相机向前
                cam_fwd_h = inv_view_matrix @ np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float64)
                camera_forward = cam_fwd_h[:3]
                n = np.linalg.norm(camera_forward)
                if n > 0:
                    camera_forward = camera_forward / n
                cx_px = (x2 - x1) / 2 + x1
                cy_px = (y2 - y1) / 2 + y1
                world = world_position_from_depth(
                            np.array([cx_px, cy_px], dtype=np.float64),
                            view_rect,
                            inv_view_matrix,
                            inv_proj_matrix,
                            camera_position,
                            camera_forward,
                            depth_value,
                        )
                world_size = screen_distance_to_world_distance(
                    np.array([x2, y2], dtype=np.float64),
                    np.array([x1, y1], dtype=np.float64),
                    depth_value,
                    depth_value,
                    view_rect,
                    inv_view_matrix,
                    inv_proj_matrix,
                    camera_position,
                    camera_forward,
                )
                scene_items = SceneItemEntryManager().get_scene_items_by_world_position(scene_id, world, 1000, action_target_description, 5)
                # 找到匹配的已知对象，只更新位置和bbox
                half = max(0.01, float(world_size) / 2.0)
                bb_min = [world[0] - half, world[1] - half, world[2] - half]
                bb_max = [world[0] + half, world[1] + half, world[2] + half]
                if len(scene_items) > 0:
                    matched_item = find_matching_item(world, scene_items)
                    if matched_item:
                        node = {
                            'item_type': matched_item.get('item_type'),
                            'item_name': matched_item.get('item_name'),
                            'description': matched_item.get('description'),
                            'description_vector': matched_item.get('description_vector', []),
                            'translation': world,
                            'extras': {
                                'tags': [matched_item.get('item_id')],
                                'boundingBox': {
                                    'min': bb_min,
                                    'max': bb_max
                                },
                                'actions': matched_item.get('actions', {}),
                                'skills': matched_item.get('skills', {}),
                                'detection_type': 'type',
                                'confidence': 1.0,
                                'class_id': 'class_id',
                                'original_class': matched_item.get('item_type')
                            }
                        }
                        SceneItemEntryManager().upsert_scene_items_batch(scene_id, [node])
                if node is None:
                    # 未找到匹配项，认为是新对象
                    scene_items = SceneItemEntryManager().get_scene_items_by_type(scene_id, item_type)
                    embedding_model = EmbeddingModel(
                        model_name="doubao-embedding-large-text-250515",
                        api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                        api_base="https://ark.cn-beijing.volces.com/api/v3",
                    )
                    desc_vec = embedding_model.embed(action_target_description)
                    node = {
                            'item_type': item_type,
                            'item_name': item_type,
                            'description': action_target_description,
                            'description_vector': desc_vec,
                            'translation': world,
                            'extras': {
                                'tags': [f"{item_type}_{len(scene_items)}"],
                                'boundingBox': {
                                    'min': bb_min,
                                    'max': bb_max
                                },
                                'actions': {},
                                'skills': {},
                                'detection_type': item_type,
                                'confidence': 1.0,
                                'class_id': item_type,
                                'original_class': item_type
                            }
                    }
                    SceneItemEntryManager().upsert_scene_items_batch(scene_id, [node])
        return f"看到了，{node['item_type']}({node['description']})" if node else f"没有看到{node['description']}"
    except Exception as e:
        logger.bind(tag="BASE").info(f"观察节点时出错: {str(e)}")
        return f"没有看到{node['description']}"

def execute_action(state: AgentFlowState, config: RunnableConfig) -> Dict[str, Any]:
    """执行行动节点"""
    action_target_id = state.get("action_target_id", "")
    action_cmd = state.get("action_cmd", "")
    look_for_item_type = state.get("look_for_item_type", 'None')
    look_for_item_description = state.get("look_for_item_description", 'None')
    action_reasoning = state.get("next_action_reasoning", "")
    scene_id = state.get("scene_id", "")
    user_id = state.get("user_id", "")
    chat_id = state.get("chat_id", "")
    bot_name = state.get("bot_name", "")
    goal_timestamp = state.get("goal_timestamp", 0)
    action_step_count = state.get("action_step_count")
    current_timestamp = int(datetime.now().timestamp() * 1000)
    duration = current_timestamp - goal_timestamp
    character_description = state.get("character_description", "")
    interrupt_message = json.dumps({"id": action_target_id, "cmd": action_cmd, "reasoning": action_reasoning, "scene_id": scene_id, "bot_name": bot_name}, ensure_ascii=False, indent=2)
    if 'None' not in look_for_item_type or 'None' not in look_for_item_description:
        look_for_result = look_for(user_id, chat_id, scene_id, look_for_item_type, look_for_item_description)
    feedback = interrupt(interrupt_message)
    if action_step_count > 10:
        logger.bind(tag="BASE").info(f"目标执行次数超过10次，结束流程")
        return Command(goto=END, update={"action_goal": action_goal, "current_result": "目标执行次数超过10次，需要重新制定目标"})
    try:
        planner = get_chat_model_by_type("pfc_action_planner")
        # 格式化输入数据
        chat_id = state.get("chat_id", "")
        action_goal = state.get("action_goal", "")
        # action_target_id = state.get("action_target_id", "")
        # action_cmd = state.get("action_cmd", "")
        # current_action = state.get("current_action", "")
        # current_target = state.get("current_target", "")
        character_description = state.get("character_description", "")
        planner_model = init_chat_model(
            model=planner.model_name,
            model_provider=planner.model_provider,
            api_key=planner.api_key,
            base_url=planner.api_base
        )
        output_parser = RemoveFunctionCallOutputParser(pydantic_object=FeedbackAnalysis)
        structured_llm = planner_model | output_parser
        feedback_format = output_parser.get_format_instructions()
        chat_history = MessageStore.get_instance().get_messages_in_recent_time(milliseconds=duration, chat_id=chat_id, m_type="action")
        chat_history_str = format_chat_history(chat_history)
        # Format system instructions for plan generation
        system_instructions = FEEDBACK_ANALYSIS_PROMPT.format(
            character_description=character_description,
            current_goal=action_goal,
            action_history=chat_history_str,
            format=feedback_format
        )
        # logger.bind(tag="BASE").info(f"execute_action system instructions: {system_instructions}")
        # Generate plan
        feedback_analysis: FeedbackAnalysis = structured_llm.invoke([
            SystemMessage(content=system_instructions)
        ],
        extra_body={"thinking": {"type": "disabled"}})
        if feedback_analysis.analysis_result_type == "goal_archived":
            logger.bind(tag="BASE").info(f"目标已实现")
            return Command(goto=END, update={"action_goal": action_goal, "current_result": feedback_analysis.analysis_result_reasoning})
        # elif feedback_analysis.analysis_result_type == "plan_next_action":
        # logger.bind(tag="BASE").info(f"规划下一步行动: {feedback_analysis.analysis_result_reasoning}")
        return Command(goto="plan_action", 
            update={"action_goal": action_goal, "current_result": "", "feedback_reasoning": feedback_analysis.analysis_result_reasoning + " " + look_for_result})
    except Exception as e:
        logger.bind(tag="BASE").info(f"执行行动时出错: {str(e)}")
        return Command(goto=END)

# 创建状态图
builder = StateGraph(AgentFlowState)

# 添加节点
# builder.add_node("analyze_goals", analyze_goals)
builder.add_node("prepare_data", prepare_data)
builder.add_node("plan_action", plan_action)
builder.add_node("execute_action", execute_action)
# 添加边
builder.add_edge(START, "prepare_data")
builder.add_edge("prepare_data", "plan_action")
builder.add_edge("plan_action", "execute_action")
