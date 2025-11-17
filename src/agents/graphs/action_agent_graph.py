"""
完整的 Action Agent 流程图实现
包含计划制定、执行计划（观察+动作）的循环
"""
import json
import numpy as np
from typing import Dict, List, Any, Optional, Literal
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain.chat_models import init_chat_model
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt, Command
from langgraph.prebuilt import create_react_agent
from loguru import logger
from agents.agent_memory.configuration.config import ChatModel, EmbeddingModel

from agents.states.action_agent_state import ActionFlowState, Plan, StepType, Step, QueryItems, SearchState, SearchActionDecision, QueryRegions, RegionInfo, ValidatedRegions, EntityInfo, ObservationResult, SearchResult, QueryItemsParams, ExecuteActionParams, ReportParams, QueryRegionsParams
from agents.prompts.action_agent_prompts import (
    ACTION_PLANNING_PROMPT,
    SEARCH_AGENT_PROMPT,
    SEARCH_REPORT_PROMPT,
    PLAN_REPORT_PROMPT,
    ACTION_REPORT_PROMPT,
    FIX_PLAN_PROMPT,
    OBSERVATION_PROMPT
)
from agents.agent_memory.configuration import get_chat_model_by_type
from agents.agent_memory.message_store import MessageStore
from agents.output_parser.output_parser import RemoveFunctionCallOutputParser
from configuration.configuration import Configuration
from agents.states.action_agent_state import SearchActionDecision
from agents.agent_memory.prompt_manager.spatial_entity.manager import DBManager as SpatialEntityManager
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
from langchain_core.callbacks import dispatch_custom_event
# ==========================================
# 工具定义
# ==========================================

@tool
def query_spatial_memory(
    session_id: str,
    item_description: str, 
    relation_filter: list[str] = None,
    reasoning: str = "",
    max_depth: int = 3,
    limit: int = 10
) -> str:
    """查询空间记忆中符合描述的物品信息
    
    Args:
        item_description: 物品描述，如 "一个红色的杯子"
        relation_filter: 关系过滤条件，如 ["在桌子上", "在房间里"]，如果为空则查询所有匹配的物品
        reasoning: 查询原因说明
    
    Returns:
        匹配的物品信息JSON，包含：item_id, item_type, item_description, item_relation, item_actions
    """
    # TODO: 实现实际的空间记忆查询逻辑
    # logger.bind(tag="BASE").info(f"查询空间记忆: {item_description}, 关系过滤: {relation_filter}")
    embedding_model = EmbeddingModel(
        model_name="doubao-embedding-large-text-250515",
        api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
        api_base="https://ark.cn-beijing.volces.com/api/v3"
    )
    query_vector = embedding_model.embed(item_description)
    entities = SpatialEntityManager().get_instance().query_items_by_constraints(
        scene_id=scene_id,
        session_id=session_id,
        description_vector=query_vector
    )
    feedback = {}
    for entity in entities:
        feedback[entity["id"]] = {
            "name": entity["item_name"],
            "label": entity["label_name"],
            "description": entity["description"],
            "item_description": entity["item_description"],
            "acceptable_actions": entity["actions"]
        }
    return json.dumps(feedback, ensure_ascii=False, indent=2)

def format_observation_result(feedback) -> str:
    """格式化观察结果"""
    logger.bind(tag="BASE").info(f"格式化观察结果: {feedback}")
    content = [f"以下是你在当前区域：{feedback['current_region']}观察到的物品信息："]
    for key, value in feedback.items():
        if key == "current_region":
            continue
        for entity_id, entity in value.items():
            if entity_id == "Aura_0":
                continue
            content.append(f"你的{key}有物品entity_id为:{entity_id}, 物品描述为:{entity['description']}, 可执行动作有{entity['acceptable_actions']}")
    result = "\n".join(content)
    return result

def format_region_result(current_region, region_list) -> str:
    """格式化区域结果"""
    content = ["以下是查询到的区域信息："]
    content.append(f"人物当前所属区域entity_id为:{current_region}")
    content.append(f"周围其它区域有：")
    for region in region_list:
        if region["entity_id"] == current_region:
            continue
        content.append(f"entity_id为:{region['entity_id']}")
    content.append(f"可以对历史记录里未观察的区域move_to过去，然后观察周围物品，这样可以遍历所有区域，就不会遗漏掉要找的东西。")
    result = "\n".join(content)
    logger.bind(tag="BASE").info(f"格式化区域结果: {result}")
    return result

@tool(args_schema=QueryItems)
def query_items(
    current_scene_id: str,
    current_region: str,
    action_goal: str
) -> str:
    """不能移动位置的动作，只能观察附近10米空间的物品，用不同的query可以观察到不同的物品，同样的query只能观察到一样的物品，所以相同query不要多次调用（没有意义），否则会返回同样的物品信息。
    
    Args:
        current_scene_id: 当前场景ID
        action_goal: 说明观察的目标的描述，比如预期找什么样的物品等，描述的越详细，观察到的物品信息越准确。
    
    Returns:
        附近物品列表JSON，每个物品包含：entity_id, description, acceptable_actions
    """
    # TODO: 实现实际的观察逻辑
    try:
        # char_instance_info = CharInstanceInfoManager().get_instance().get_char_instance_info_by_chat_id(session_id)
        self_entity = SpatialEntityManager().get_instance().query_items_by_entity_id(
            scene_id=current_scene_id,
            entity_id="Aura_0"
        )
        
        self_forward = self_entity["properties"].get("forward", [1, 0, 0])
        self_pos = self_entity["anchor_point_3d"]
        embedding_model = EmbeddingModel(
            model_name="doubao-embedding-large-text-250515",
            api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
            api_base="https://ark.cn-beijing.volces.com/api/v3"
        )
        query_vector = embedding_model.embed(action_goal, embedding_size=1024)
        # current_region = SpatialEntityManager().get_instance().query_region_include_item(
        #     scene_id=current_scene_id,
        #     item_entity_id="Aura_0",
        #     session_id="static"
        # )
        entities = SpatialEntityManager().get_instance().query_items_in_region(
            scene_id=current_scene_id,
            region_entity_id=current_region,
            session_id="static",
            description_vector=query_vector,
            description_similarity_threshold=0.3,
            limit=30
        )
        action_model_config = get_chat_model_by_type("pfc_action")
        action_model = init_chat_model(
            model=action_model_config.model_name,
            model_provider=action_model_config.model_provider,
            api_key=action_model_config.api_key,
            base_url=action_model_config.api_base
        )
        # 创建输出解析器
        output_parser = RemoveFunctionCallOutputParser(pydantic_object=ObservationResult)
        structured_llm = action_model | output_parser
        format_instructions = output_parser.get_format_instructions()
        query_item_info_list = []
        for entity in entities:
            query_item_info_list.append(f"entity_id: {entity['entity_id']}, description: {entity['description']}, acceptable_actions: {entity['actions']}")
        system_instructions = OBSERVATION_PROMPT.format(
            item_info_list="\n".join(query_item_info_list),
            query_target=action_goal,
            format=format_instructions
        )
        
        messages = [SystemMessage(content=system_instructions)]
        
        observations: ObservationResult = structured_llm.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
        feedback = {}
        feedback["current_region"] = current_region
        feedback["forward"] = {}
        feedback["backward"] = {}
        feedback["left"] = {}
        feedback["right"] = {}
        for entity in entities:
            entity_id = entity["entity_id"]
            if entity_id not in observations.entities:
                continue
            entity_pos = entity["anchor_point_3d"]
            try:
                self_pos_np = np.array(self_pos, dtype=float)
                self_fwd_np = np.array(self_forward, dtype=float)
                entity_pos_np = np.array(entity_pos, dtype=float)
                # 投影到平面 (x, y)，忽略 z，高度不影响左右前后
                fwd_xy = self_fwd_np[:2]
                vec_xy = (entity_pos_np - self_pos_np)[:2]
                # 归一化并防御零向量
                fwd_norm = np.linalg.norm(fwd_xy)
                if fwd_norm < 1e-6:
                    fwd_xy = np.array([1.0, 0.0])
                    fwd_norm = 1.0
                dir_xy = vec_xy
                dir_norm = np.linalg.norm(dir_xy)
                # 默认关系
                relation = "forward"
                distance = float(dir_norm)
                if dir_norm < 1e-6:
                    relation = "forward"
                else:
                    # 角度阈值：前后以45°划分
                    cos_val = float(np.dot(fwd_xy, dir_xy) / (fwd_norm * dir_norm))
                    cos_val = max(min(cos_val, 1.0), -1.0)
                    cos_45 = 0.7071067811865476
                    if cos_val >= cos_45:
                        relation = "forward"
                    elif cos_val <= -cos_45:
                        relation = "backward"
                    else:
                        # 左右通过二维叉积符号判定（z 分量）
                        cross_z = fwd_xy[0] * dir_xy[1] - fwd_xy[1] * dir_xy[0]
                        relation = "left" if cross_z > 0 else "right"
                # 写入分类桶
                feedback[relation][entity["entity_id"]] = {
                    "description": observations.entities[entity_id].summary_description,
                    "acceptable_actions": list(set(entity["actions"] + ["move_to", "examine"]))
                }
            except Exception:
                # 回退：若计算失败，按前方处理
                feedback["forward"][entity["entity_id"]] = {
                    "description": observations.entities[entity_id].summary_description,
                    "acceptable_actions": list(set(entity["actions"] + ["move_to", "examine"]))
                }
        return format_observation_result(feedback)
    except Exception as e:
        logger.error(f"观察附近物品失败: {e}")

@tool(args_schema=QueryRegions)
def query_regions(
    scene_id: str,
    current_region: str
) -> List[str]:
    """可以移动位置的动作，查询周围的区域，区域是符合描述的物品的集合。
    
    Args:
        session_id: 当前session_id
        query: 说明查询的区域描述，比如预期找什么样的区域等，描述的越详细，查询到的区域信息越准确。
    
    Returns:
        区域列表，每个区域包含：entity_id
    """
    # TODO: 实现实际的观察逻辑
    try:
        all_region = SpatialEntityManager().get_instance().query_region_connected_with_current_region(
            scene_id=scene_id,
            session_id="static",
            region_entity_id=current_region,
            limit=15,
        )
        return [region["entity_id"] for region in all_region]
    except Exception as e:
        logger.error(f"观察附近物品失败: {e}")

@tool(return_direct=True, args_schema=SearchResult)
def report_search_result(
    search_task: str,
    finish_reasoning: str,
    task_execution_record: str,
) -> str:
    """当完成任务后，调用此工具报告
    
    Args:
        search_task: 搜索任务
        finish_reasoning: 完成任务的原因说明
    Returns:
        搜索任务结果和后续搜索建议
    """
    planner_model_config = get_chat_model_by_type("pfc_action")
    planner_model = init_chat_model(
        model="doubao-seed-1-6-251015",
        model_provider=planner_model_config.model_provider,
        api_key=planner_model_config.api_key,
        base_url=planner_model_config.api_base
    )
    # 构建提示词（加入最近观察，避免重复观察）
    system_instructions = SEARCH_REPORT_PROMPT.format(
        search_task=search_task,
        finish_reasoning=finish_reasoning,
        task_execution_record=task_execution_record
    )
    messages = [SystemMessage(content=system_instructions)]
    result = planner_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
    return result.content

@tool
def execute_action(
    session_id: str,
    entity_id: str, 
    action_cmd: str,
    reasoning: str = ""
) -> str:
    """能移动位置的动作，可以通过和特定物品交互来移动到目标物品位置，然后就有机会在后续的观察动作中获得更多物品的新位置，才能观察到的物品信息。
    
    Args:
        entity_id: 目标物品的entity_id
        action_cmd: 在目标物品acceptable_actions中选择一个要执行的动作命令，比如 "move_to", "examine"等
        reasoning: 执行动作的原因说明
    
    Returns:
        执行动作的结果反馈
    """
    logger.bind(tag="BASE").info(f"执行动作: {action_cmd} -> {entity_id}, 原因: {reasoning}, session_id: {session_id}")
    result_str = f"执行动作 {action_cmd} -> {entity_id} 成功"
    if action_cmd in ["move_to", "examine"]:
        target_entity = SpatialEntityManager().get_instance().query_items_by_entity_id(
            scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
            entity_id=entity_id
        )
        if target_entity:
            # execute_action_data = {
            #     "type": "execute_action_tool",
            #     "action_cmd": action_cmd,
            #     "entity_id": entity_id
            # }
            # interrupt(execute_action_data)
            SpatialEntityManager().get_instance().update_item_position(
                session_id="static",
                scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
                entity_id="Aura_0",
                position=np.array([target_entity["anchor_point_3d"][0], target_entity["anchor_point_3d"][1], target_entity["anchor_point_3d"][2]])
            )
            if action_cmd == "examine":
                result_str = result_str + f"，物品描述为: {target_entity['description']}"
        else:
            result_str = f"执行动作 {action_cmd} -> {entity_id} 失败，没有指定正确的物品entity_id"
    return result_str

# ==========================================
# 辅助函数
# ==========================================

def format_chat_history(chat_history: List[Any]) -> str:
    """格式化聊天记录"""
    if not chat_history:
        return "暂无聊天记录"
    
    formatted = []
    for msg in chat_history:
        formatted.append(f"消息类型:{getattr(msg, 'm_type', 'unknown')}, 角色:{getattr(msg, 'role', 'unknown')}, 内容:{getattr(msg, 'content', '')}")
    
    return "\n".join(formatted)

def format_items_info(items_info: List[Dict[str, Any]]) -> str:
    """格式化物品信息列表"""
    if not items_info:
        return "暂无物品信息"
    
    formatted = []
    for item in items_info:
        formatted.append(f"ID={item.get('item_id')}, 类型={item.get('item_type')}, 描述={item.get('item_description')}, 可执行动作={item.get('item_actions')}")
    
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

def handle_position(user_id:str, session_id:str, scene_id:str, related_items:List[Dict[str, Any]]):
    import requests
    from PIL import Image
    import io
    import numpy as np
    look_url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{session_id}/view_data/look.jpg"
    cam_url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{session_id}/view_data/cam.json"
    depth_url = f"https://aura-view-eye.tos-cn-beijing.volces.com/assets/{user_id}/{session_id}/view_data/depth.png"
    # 直接下载为内存数据（不落地临时文件）
    try:
        print(f"正在下载 look.jpg: {look_url}")
        resp_look = requests.get(look_url, timeout=30)
        resp_look.raise_for_status()
        # 使用 PIL 解码图像，然后转换为 numpy 数组（RGB 格式）
        look_img_pil = Image.open(io.BytesIO(resp_look.content)).convert('RGB')
        look_img = np.array(look_img_pil)
        # PIL 返回 RGB，OpenCV 是 BGR，但这里只需要形状，所以不需要转换通道顺序
        if look_img is None:
            raise RuntimeError("look.jpg 解析失败")
        print("look.jpg 下载并解析完成")
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
    except Exception as e:
        raise Exception(f"下载资源失败: {e}")
    
    try:
        img_h, img_w = (look_img.shape[0], look_img.shape[1]) if look_img is not None else (1080, 1920)
    except Exception:
        img_h, img_w = (1080, 1920)
    inv_mvp = None
    depth_linear = None
    try:
        print(f"正在解析 cam.json（内存）")
        print(f"cam.json 下载成功，包含 {len(cam_data)} 个键")
        # 优先读取分离的 proj/view 矩阵
        proj = cam_data.get('projection_matrix')
        view_m = cam_data.get('view_matrix')
        scene_name = cam_data.get('scene_name')
        # # 近远裁剪面（若提供）
        # if isinstance(cam_data.get('near'), (int, float)):
        #     near_plane = float(cam_data['near'])
        # if isinstance(cam_data.get('far'), (int, float)):
        #     far_plane = float(cam_data['far'])
        if isinstance(proj, list) and len(proj) == 16 and isinstance(view_m, list) and len(view_m) == 16:
            proj_matrix = np.array([proj[i*4:(i+1)*4] for i in range(4)], dtype=np.float64).transpose()
            view_matrix = np.array([view_m[i*4:(i+1)*4] for i in range(4)], dtype=np.float64).transpose()
            print("已解析分离的 proj/view 矩阵 (4x4)")
            try:
                inv_proj_matrix = np.linalg.inv(proj_matrix)
                inv_view_matrix = np.linalg.inv(view_matrix)
                camera_position = inv_view_matrix[:3, 3]
                cam_fwd_h = inv_view_matrix @ np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float64)
                camera_forward = cam_fwd_h[:3]
                n = np.linalg.norm(camera_forward)
                if n > 0:
                    camera_forward = camera_forward / n
            except Exception as e:
                print(f"计算 inv_proj/inv_view 或相机参数失败: {e}")
    except requests.exceptions.RequestException as e:
        print(f"下载 cam.json 失败: {e}")
    except json.JSONDecodeError as e:
        print(f"解析 cam.json 失败: {e}")
    except Exception as e:
        print(f"处理 cam.json 时出错: {e}")
    # 读取 PNG 深度图（内存）
    try:
        print(f"正在解析 depth.png（内存）")
        # 使用 PIL 解码 PNG 深度图（保持位深/通道）
        depth_img_pil = Image.open(io.BytesIO(depth_content))
        depth_img = np.array(depth_img_pil)
        if depth_img is None:
            raise RuntimeError("depth.png 解码失败")
        # 期望格式：32位色，float 分4字节压入 RGBA
        # PIL 解码返回通道顺序为 RGBA（若有4通道）
        if depth_img.ndim == 3 and depth_img.shape[2] == 4:
            # 提取通道（R,G,B,A）- PIL 直接返回 RGBA 顺序
            r = depth_img[:, :, 0]
            g = depth_img[:, :, 1]
            b = depth_img[:, :, 2]
            a = depth_img[:, :, 3]
            # 还原为小端序 float32 字节序列 [R,G,B,A]
            rgba_bytes = np.stack([r, g, b, a], axis=-1).astype(np.uint8)
            flat_bytes = rgba_bytes.reshape(-1, 4)
            # 通过视图转换为 float32，再 reshape 回原尺寸
            depth_f32 = flat_bytes.view(np.float32).reshape(depth_img.shape[0], depth_img.shape[1])
            depth_linear = depth_f32.astype(np.float64)
        else:
            raise RuntimeError("depth.png 通道数不为4，无法按 RGBA 打包规则解析")
        print(f"depth.png 解析成功（RGBA-packed float32），shape={depth_linear.shape}, 值范围=[{np.nanmin(depth_linear):.6f}, {np.nanmax(depth_linear):.6f}]")
    except Exception as e:
        print(f"读取 depth.png 失败: {e}")
    # 视口矩形
    view_rect = (0, 0, img_w, img_h)
    related_items_with_id = []
    for related_item in related_items:
        x1 = related_item.get("bounding_box", [0, 0, 0, 0])[0]
        y1 = related_item.get("bounding_box", [0, 0, 0, 0])[1]
        x2 = related_item.get("bounding_box", [0, 0, 0, 0])[2]
        y2 = related_item.get("bounding_box", [0, 0, 0, 0])[3]
        # 计算像素中心点
        cx_px = (x2 - x1) / 2 + x1
        cy_px = (y2 - y1) / 2 + y1
        if inv_proj_matrix is not None and inv_view_matrix is not None and depth_linear is not None and camera_position is not None and camera_forward is not None:
            # 确保区域有效
            if x2 > x1 and y2 > y1:
                # 获取检测区域内的深度值并找到中值
                detection_depth_region = depth_linear[y1:y2, x1:x2]
                # 过滤掉无效的深度值（通常为0或负数）
                valid_depths = detection_depth_region[detection_depth_region > 0]
                if len(valid_depths) > 0:
                    depth_value = float(np.median(valid_depths))
                else:
                    # 如果没有有效深度值，使用中心点
                    u0 = int(np.clip(np.floor(cx_px), 0, img_w - 1))
                    v0 = int(np.clip(np.floor(cy_px), 0, img_h - 1))
                    depth_value = float(depth_linear[v0, u0])
            else:
                # 如果区域无效，使用中心点
                u0 = int(np.clip(np.floor(cx_px), 0, img_w - 1))
                v0 = int(np.clip(np.floor(cy_px), 0, img_h - 1))
                depth_value = float(depth_linear[v0, u0])
                # 将两个屏幕点转换为世界坐标
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
            bbox = [world[0], world[1], world[2], world_size, world_size, world_size]
            embedding_model = EmbeddingModel(
                model_name="doubao-embedding-large-text-250515",
                api_key="dc7e10e7-1095-40ae-a172-3a7d16fc1e61",
                api_base="https://ark.cn-beijing.volces.com/api/v3"
            )
            query_vector = embedding_model.embed(f"{related_item.get('item_name', '')}: {related_item.get('item_description', '')}")
            spatial_entity = SpatialEntityManager().get_instance().query_entity_by_description_and_bbox_overlap(
                session_id="static",
                scene_id=scene_id,
                world_bb=bbox,
                description_vector=query_vector,
                entity_types=["object"],
                limit=50,
            )
            if spatial_entity:
                related_items_with_id.append({
                    "item_name": related_item.get("item_name", ""),
                    "item_description": related_item.get("item_description", ""),
                    "spatial_entity_id": spatial_entity["entity_id"],
                    "world_bb": spatial_entity["entity_bbox_3d"].tolist()
                })
            else:
                related_items_with_id.append({
                    "item_name": related_item.get("item_name", ""),
                    "item_description": related_item.get("item_description", ""),
                    "spatial_entity_id": None
                    "world_bb": None
                })
    return related_items_with_id
# ==========================================
# 节点定义
# ==========================================

def prepare_data(state: ActionFlowState) -> Dict[str, Any]:
    session_id = state.get("session_id", "")
    current_scene_id = state.get("current_scene_id", None)
    if not current_scene_id:
        char_instance_info = CharInstanceInfoManager().get_instance().get_char_instance_info_by_chat_id(session_id)
        current_scene_id = char_instance_info.current_scene_id
    user_id = state.get("user_id", "")
    action_input = state.get("action_input", {})
    related_items = action_input.get("related_items", [])
    related_items_with_id = handle_position(user_id, session_id, current_scene_id, related_items)
    action_input["related_items"] = related_items_with_id
    validated_regions = state.get("validated_regions", ValidatedRegions(regions={}))
    if isinstance(validated_regions, ValidatedRegions):
        validated_regions.reset_regions()
    else:
        validated_regions = ValidatedRegions(regions={})
    return {"session_id": session_id, "current_scene_id": current_scene_id, "validated_regions": validated_regions, "action_input": action_input}

def planner_node(
    state: ActionFlowState, 
    config: RunnableConfig
) -> Command[Literal["search_team", "reporter"]]:
    """计划节点：生成行动计划"""
    logger.bind(tag="BASE").info("Planner 生成行动计划")
    
    # 检查是否超过最大迭代次数
    if state["remaining_steps"] <= 2:
        logger.bind(tag="BASE").info(f"剩余步骤不足2步，无法生成计划: {state["remaining_steps"]}")
        return Command(goto="reporter")
    try:
        session_id = state.get("session_id", "")
        current_scene_id = state.get("current_scene_id", None)
        logger.bind(tag="BASE").info(f"current_scene_id: {current_scene_id}")
        validated_regions = state.get("validated_regions", ValidatedRegions(regions={}))
        validated_regions.reset_regions()
        # 获取必要信息
        user_id = state.get("user_id", "")
        action_input = state.get("action_input", {})
        action_goal = action_input.get("goal_to_plan", "")
        related_items = action_input.get("related_items", [])
        # 获取模型
        planner_model_config = get_chat_model_by_type("pfc_action")
        planner_model = init_chat_model(
            model="doubao-seed-1-6-251015",
            model_provider=planner_model_config.model_provider,
            api_key=planner_model_config.api_key,
            base_url=planner_model_config.api_base
        )
        
        # 创建输出解析器
        output_parser = RemoveFunctionCallOutputParser(pydantic_object=Plan)
        structured_llm = planner_model | output_parser
        format_instructions = output_parser.get_format_instructions()
        
        plan_history = state.get("plan_history", [])
        # 构建提示词（加入最近观察，避免重复观察）
        system_instructions = ACTION_PLANNING_PROMPT.format(
            current_goal=action_goal,
            related_items=related_items,
            task_execution_record="\n".join(plan_history),
            format=format_instructions
        )
        
        messages = [HumanMessage(content=system_instructions)]
        logger.bind(tag="BASE").info(f"system_instructions: {system_instructions}")
        result = planner_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
        logger.bind(tag="BASE").info(f"result: {result.content}")
    except Exception as e:
        logger.bind(tag="BASE").info(f"生成计划失败: {e} goto reporter")
        return Command(goto="reporter")
    # 生成计划
    try:
        plan: Plan = output_parser.invoke(result.content)
        logger.bind(tag="BASE").info(f"生成计划，步骤数: {len(plan.steps)}" + ", 步骤详情: " + "\n".join([f"步骤{i+1}: {step.step_goal}" for i, step in enumerate(plan.steps)]))
        
        # 更新状态
        return Command(
            update={
                "current_plan": plan,
                "current_scene_id": current_scene_id,
                "validated_regions": validated_regions
            },
            goto="search_team" if not plan.has_achieved_goal else "reporter"
        )
    except Exception as e:
        logger.bind(tag="BASE").info(f"生成计划失败: {e} goto fix_plan_node")
        return Command(
            update={"raw_plan": result.content},
            goto="fix_plan_node"
        )

def fix_plan_node(
    state: ActionFlowState,
    config: RunnableConfig
) -> Command[Literal["planner", "reporter"]]:
    """修复计划节点：修复计划中的错误"""
    logger.bind(tag="BASE").info("Fix Plan 修复计划")
    
    raw_plan = state.get("raw_plan")
    if state["remaining_steps"] <= 2:
        logger.warning(f"剩余步骤不足2步，无法修复计划: {state["remaining_steps"]}")
        return Command(goto="reporter")
    
    if not raw_plan:
        logger.warning("没有原始计划")
        return Command(goto="reporter")
    
    # 获取模型
    planner_model_config = get_chat_model_by_type("pfc_action")
    planner_model = init_chat_model(
        model="doubao-seed-1-6-251015",
        model_provider=planner_model_config.model_provider,
        api_key=planner_model_config.api_key,
        base_url=planner_model_config.api_base
    )
    output_parser = RemoveFunctionCallOutputParser(pydantic_object=Plan)
    structured_llm = planner_model | output_parser
    format_instructions = output_parser.get_format_instructions()
    system_instructions = FIX_PLAN_PROMPT.format(
        raw_plan=raw_plan,
        format=format_instructions
    )
    messages = [HumanMessage(content=system_instructions)]
    plan: Plan = structured_llm.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
    # 更新状态
    return Command(
        update={
            "current_plan": plan
        },
        goto="search_team" if not plan.has_achieved_goal else "reporter"
    )

def search_team_node(
    state: ActionFlowState,
    config: RunnableConfig
) -> Command[Literal["search", "planner", "reporter"]]:
    """搜索团队节点：分配任务给搜索者"""
    logger.bind(tag="BASE").info("Search Team 分配任务")
    
    current_plan = state.get("current_plan")
    # 检查计划是否存在
    if not current_plan or not current_plan.steps:
        logger.warning("当前没有有效的计划或步骤")
        return Command(goto="reporter")
    
    # 找到第一个未执行的步骤
    next_step = None
    for step in current_plan.steps:
        if not step.result:
            next_step = step
            break
    
    if state["remaining_steps"] <= 3:
        logger.warning(f"剩余步骤不足3步，无法分配任务: {state["remaining_steps"]}")
        next_step = None
    
    if not next_step:
        # 所有步骤都已完成
        logger.bind(tag="BASE").info("所有步骤已完成，返回规划节点")
        planner_model_config = get_chat_model_by_type("pfc_action")
        planner_model = init_chat_model(
            model="doubao-seed-1-6-251015",
            model_provider=planner_model_config.model_provider,
            api_key=planner_model_config.api_key,
            base_url=planner_model_config.api_base
        )
        # 构建提示词（加入最近观察，避免重复观察）
        plan_record = ["计划执行记录:"]
        for i, step in enumerate(current_plan.steps):
            if step.result:
                plan_record.append(f"Step {i+1}: {step.step_goal}, 执行结果: {step.result}")
            else:
                plan_record.append(f"Step {i+1}: {step.step_goal}, 执行结果: 未执行")
        plan_record = "\n".join(plan_record)
        system_instructions = PLAN_REPORT_PROMPT.format(
            plan_execution_record="\n".join(plan_record)
        )
        messages = [SystemMessage(content=system_instructions)]
        result = planner_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
        logger.bind(tag="BASE").info(f"报告搜索结果: {result.content}")
        plan_history = state.get("plan_history", [])
        plan_history.append(result.content)
        update = {"plan_history": plan_history}
        return Command(goto="planner", update=update)
    
    # 根据步骤类型分发到不同的节点
    logger.bind(tag="BASE").info(f"执行搜索步骤: {next_step.step_goal}")
    return Command(goto="search", update={"session_id": state.get("session_id", ""), "current_plan": current_plan, "action_input": state.get("action_input", {})})

def _search_decide_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal["tool_query_items", "tool_query_regions", "tool_execute_action", "tool_report", END]]:
    """搜索子图-决策节点：决定调用哪个工具，并写入参数到状态"""
    logger.bind(tag="BASE").info("Search子图 决策下一步工具")
    current_plan = state.get("current_plan")
    current_scene_id = state.get("current_scene_id", "")
    current_region = state.get("current_region", None)
    action_input = state.get("action_input", {})
    related_items = action_input.get("related_items", [])
    if not current_region:
        current_region_obj = SpatialEntityManager().get_instance().query_region_include_item(
            scene_id=current_scene_id,
            item_entity_id="Aura_0",
            session_id="static"
        )
        current_region = current_region_obj['entity_id']
    
    validated_regions = state.get("validated_regions", ValidatedRegions(regions={}))
    search_steps_history = state.get("search_steps", [])

    if state["remaining_steps"] <= 3:
        logger.bind(tag="BASE").info(f"剩余步骤不足3步，无法决策: {state["remaining_steps"]}")
        decision = SearchActionDecision(action_name="Report", action_params=ReportParams(finish_reasoning="达到最大计划迭代次数"))
        update = {"next_search_decision": decision}
        return Command(goto="tool_report", update=update)
    # 检查计划是否存在
    if not current_plan or not current_plan.steps:
        logger.bind(tag="BASE").info("当前没有有效的计划或步骤")
        decision = SearchActionDecision(action_name="Report", action_params=ReportParams(finish_reasoning="当前没有有效的计划或步骤"))
        update = {"next_search_decision": decision}
        return Command(goto="tool_report", update=update)
    
    # if len(search_steps_history) == 0:
    #     logger.bind(tag="BASE").info(f"查询当前区域周边的区域: {current_region}, {validated_regions.to_string()}")
    #     decision = SearchActionDecision(action_name="Query_Regions", action_params=QueryRegionsParams(current_region=current_region))
    #     update = {"next_search_decision": decision, "current_region": current_region, "validated_regions": validated_regions}
    #     return Command(goto="tool_query_regions", update=update)
    
    # 找到第一个未执行的步骤
    next_step = None
    for step in current_plan.steps:
        if not step.result:
            next_step = step
            break
    
    # 获取模型
    observer_model_config = get_chat_model_by_type("pfc_action_planner")
    observer_model = init_chat_model(
        model="doubao-seed-1-6-251015",
        model_provider=observer_model_config.model_provider,
        api_key=observer_model_config.api_key,
        base_url=observer_model_config.api_base
    )
    need_query_items = False
    if current_region in validated_regions.regions:
        if validated_regions.regions[current_region].is_searched == False:
            need_query_items = True
    else:
        need_query_items = True
    # 解析成 SearchDecision
    output_parser = RemoveFunctionCallOutputParser(pydantic_object=SearchActionDecision)
    structured_llm = observer_model | output_parser
    format_instructions = output_parser.get_format_instructions()
    system_instructions = SEARCH_AGENT_PROMPT.format(
        current_region=f"当前区域: {current_region}{'， 当前区域未搜索过，如需搜索物品，请调用Query_Items工具。' if need_query_items else ''}",
        related_items=related_items,
        validated_regions=validated_regions.to_string(),
        search_task=f"任务目标: {next_step.step_goal}, 检查点: {', '.join(next_step.check_points)}",
        task_execution_record="\n".join(search_steps_history),
        format=format_instructions
    )
    messages = [SystemMessage(content=system_instructions)]
    decision: SearchActionDecision = structured_llm.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
    logger.bind(tag="BASE").info(f"搜索决策: {decision}")
    update = {"next_search_decision": decision, "current_region": current_region}
    if decision.action_name == "Query_Items":
        return Command(update=update, goto="tool_query_items")
    if decision.action_name == "Query_Regions":
        return Command(update=update, goto="tool_query_regions")
    if decision.action_name == "Execute_Action":
        return Command(update=update, goto="tool_execute_action")
    return Command(update=update, goto="tool_report")

# def _fix_search_node(
#     state: SearchState,
#     config: RunnableConfig
# ) -> Command[Literal["tool_query_items", "tool_query_regions", "tool_execute_action", "tool_report", END]]:
#     """修复计划节点：修复计划中的错误"""
#     logger.bind(tag="BASE").info("Fix Search 修复搜索")
    
#     raw_search = state.get("raw_search")
#     current_step = config["metadata"]["langgraph_step"]
#     recursion_limit = config["recursion_limit"]

#     if current_step >= recursion_limit:
#         logger.warning(f"达到最大计划迭代次数 {recursion_limit}")
#         return Command(goto="tool_query_regions", update=update)
    
#     if not raw_plan:
#         logger.warning("没有原始计划")
#         return Command(goto="reporter")
    
#     # 获取模型
#     planner_model_config = get_chat_model_by_type("pfc_action")
#     planner_model = init_chat_model(
#         model="doubao-seed-1-6-251015",
#         model_provider=planner_model_config.model_provider,
#         api_key=planner_model_config.api_key,
#         base_url=planner_model_config.api_base
#     )
#     output_parser = RemoveFunctionCallOutputParser(pydantic_object=Plan)
#     structured_llm = planner_model | output_parser
#     format_instructions = output_parser.get_format_instructions()
#     system_instructions = FIX_PLAN_PROMPT.format(
#         raw_plan=raw_plan,
#         format=format_instructions
#     )
#     messages = [HumanMessage(content=system_instructions)]
#     plan: Plan = structured_llm.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
#     # 更新状态
#     return Command(
#         update={
#             "current_plan": plan
#         },
#         goto="search_team" if not plan.has_achieved_goal else "reporter"
#     )

def _search_tool_query_items_node(
    state: SearchState
) -> Command[Literal["search_decide"]]:
    """搜索子图-观察工具节点"""
    decision: SearchActionDecision | None = state.get("next_search_decision")
    if not decision or not decision.action_params or not isinstance(decision.action_params, QueryItemsParams):
        logger.warning("缺少动作参数，回到决策")
        return Command(goto="search_decide")
    # session_id = decision.session_id or state.get("session_id", "") if decision else state.get("session_id", "")
    current_scene_id = state.get("current_scene_id", "")
    current_region = state.get("current_region", None)
    try:
        result = query_items.invoke({"current_scene_id": current_scene_id, "current_region": current_region, "action_goal": decision.action_params.query_item_description})
        search_steps = state.get("search_steps", [])
        search_steps.append(f"Step {len(search_steps)+1}: Query_Items: 查询目标 {decision.action_params.query_item_description}\n 查询结果: {result}")
        current_region = state.get("current_region", None)
        update = {"search_steps": search_steps}
        if current_region:
            validated_regions = state.get("validated_regions", ValidatedRegions(regions={}))
            if current_region not in validated_regions.regions:
                validated_regions.regions[current_region] = RegionInfo(is_visited=True, is_searched=True)
            else:
                validated_regions.regions[current_region].is_searched = True
                validated_regions.regions[current_region].is_visited = True
            update = {"search_steps": search_steps, "validated_regions": validated_regions}
        return Command(update=update, goto="search_decide")
    except Exception as e:
        logger.error(f"执行观察失败: {e}")
        return Command(goto="search_decide")

def _search_tool_query_regions_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal["search_decide"]]:
    """搜索子图-查询区域工具节点"""
    # decision: SearchDecision | None = state.get("next_search_decision")
    current_scene_id = state.get("current_scene_id", "")
    current_region = state.get("current_region", "")
    try:
        result = query_regions.invoke({"scene_id": current_scene_id, "current_region": current_region})
        search_steps = state.get("search_steps", [])
        search_steps.append(f"Step {len(search_steps)+1}: Query_Regions: 查询当前区域{current_region}周边的区域\n结果: {result}")
        validated_regions = state.get("validated_regions", ValidatedRegions(regions={}))
        for region_id in result:
            if region_id not in validated_regions.regions:
                validated_regions.regions[region_id] = RegionInfo(is_visited=False, is_searched=False)
        update = {"search_steps": search_steps, "validated_regions": validated_regions}
        logger.bind(tag="BASE").info(f"查询区域成功: {update}")
        return Command(update=update, goto="search_decide")
    except Exception as e:
        logger.bind(tag="BASE").info(f"查询区域失败: {e}")
        return Command(goto="search_decide")

def _search_tool_execute_action_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal["search_decide"]]:
    """搜索子图-执行动作工具节点"""
    decision: SearchActionDecision | None = state.get("next_search_decision")
    if not decision or not decision.action_params or not isinstance(decision.action_params, ExecuteActionParams):
        logger.bind(tag="BASE").warning("缺少动作参数，回到决策")
        return Command(goto="search_decide")
    session_id = state.get("session_id", "")
    current_scene_id = state.get("current_scene_id", "")
    current_region = state.get("current_region", None)
    validated_regions = state.get("validated_regions", ValidatedRegions(regions={}))

    spatial_entity = SpatialEntityManager().get_instance().query_items_by_entity_id(
        scene_id=current_scene_id,
        entity_id=decision.action_params.entity_id
    )
    search_steps = state.get("search_steps", [])
    if spatial_entity:
        if spatial_entity['entity_type'] == 'region':
            spatial_entity_id = spatial_entity['entity_id']
            if spatial_entity_id not in validated_regions.regions:
                validated_regions.regions[spatial_entity_id] = RegionInfo(is_visited=False, is_searched=False)
            else:
                validated_regions.regions[spatial_entity_id].is_visited = True
            current_region = spatial_entity['entity_id']
        position = spatial_entity["anchor_point_3d"]
        result = interrupt({
            "type": "execute_action_tool",
            "session_id": session_id,
            "entity_id": decision.action_params.entity_id,
            "action_cmd": decision.action_params.action_cmd,
            "reasoning": "reasoning",
            "position": position
        })
        # result = execute_action.invoke({
        #     "session_id": session_id,
        #     "entity_id": decision.action_params.entity_id,
        #     "action_cmd": decision.action_params.action_cmd,
        #     "reasoning": "reasoning",
        # })
        search_steps.append(f"执行: {decision.action_params.action_cmd} -> {decision.action_params.entity_id}\n结果: {result}")
    else:
        search_steps.append(f"执行: {decision.action_params.action_cmd} -> {decision.action_params.entity_id}\n结果: 目标不存在")
    return Command(update={"search_steps": search_steps, "current_region": current_region, "validated_regions": validated_regions}, goto="search_decide")

def _search_tool_report_node(
    state: SearchState,
    config: RunnableConfig
) -> Command[Literal[END]]:
    """搜索子图-报告工具节点，结束当前步骤并返回上层"""
    decision: SearchActionDecision | None = state.get("next_search_decision")
    if not decision or not decision.action_params or not isinstance(decision.action_params, ReportParams):
        logger.warning("缺少动作参数，回到决策")
        return Command(goto="search_decide")
    try:
        # 写入当前步骤结果
        current_plan = state.get("current_plan")
        search_steps = state.get("search_steps", [])
        if current_plan and getattr(current_plan, "steps", None):
            for step in current_plan.steps:
                if not step.result:
                    result = report_search_result.invoke({
                        "search_task": step.step_goal,
                        "finish_reasoning": decision.action_params.finish_reasoning,
                        "task_execution_record": "\n".join(search_steps),
                    })
                    step.result = result
                    break
        return Command(update={"search_steps": None, "next_search_decision": None}, goto=END)
    except Exception as e:
        logger.error(f"报告结果失败: {e}")
        return Command(goto=END)

def reporter_node(state: ActionFlowState) -> Dict[str, Any]:
    """报告节点：生成最终结果"""
    logger.bind(tag="BASE").info("Reporter 生成最终报告")
    current_plan = state.get("current_plan", None)
    plan_history = state.get("plan_history", "")
    action_input = state.get("action_input", {})
    action_goal = action_input.get("goal_to_plan", "")
    # 构建最终结果
    result = "## 执行步骤"
    for i, plan_content in enumerate(plan_history):
        result += f"\n### 步骤 {i+1}: {plan_content}\n"
    result += "\n## 状态\n"
    if current_plan and current_plan.has_achieved_goal:
        result += "✓ 目标已达成\n"
    else:
        result += "✗ 目标未达成\n"
    # 所有步骤都已完成
    logger.bind(tag="BASE").info("所有步骤已完成，返回规划节点")
    planner_model_config = get_chat_model_by_type("pfc_action")
    planner_model = init_chat_model(
        model="doubao-seed-1-6-251015",
        model_provider=planner_model_config.model_provider,
        api_key=planner_model_config.api_key,
        base_url=planner_model_config.api_base
    )
    # 构建提示词（加入最近观察，避免重复观察）
    system_instructions = ACTION_REPORT_PROMPT.format(
        task_goal=action_goal,
        task_execution_report=result
    )
    messages = [SystemMessage(content=system_instructions)]
    result = planner_model.invoke(messages, extra_body={"thinking": {"type": "disabled"}})
    logger.bind(tag="BASE").info(f"生成最终报告: {result.content}")
    return {"action_result": result.content}

# ==========================================
# Graph 构建
# ==========================================

action_agent_builder = StateGraph(
    ActionFlowState,
    config_schema=Configuration
)

# 添加节点
action_agent_builder.add_node("prepare_data", prepare_data)
action_agent_builder.add_node("planner", planner_node)
action_agent_builder.add_node("search_team", search_team_node)

# 构建搜索子图：工具节点化 + 条件边
search_subgraph_builder = StateGraph(
    SearchState,
    config_schema=Configuration
)
search_subgraph_builder.add_node("search_decide", _search_decide_node)
search_subgraph_builder.add_node("tool_query_items", _search_tool_query_items_node)
search_subgraph_builder.add_node("tool_query_regions", _search_tool_query_regions_node)
search_subgraph_builder.add_node("tool_execute_action", _search_tool_execute_action_node)
search_subgraph_builder.add_node("tool_report", _search_tool_report_node)
search_subgraph_builder.add_edge(START, "search_decide")
search_subgraph = search_subgraph_builder.compile()

# 将子图作为一个节点挂到主图
action_agent_builder.add_node("search", search_subgraph)

# action_agent_builder.add_node("observe", observe_node)
# action_agent_builder.add_node("action", action_node)
action_agent_builder.add_node("reporter", reporter_node)
action_agent_builder.add_node("fix_plan_node", fix_plan_node)

# 添加边
# 注意：每个节点都有自己的 Command，通过 goto 控制流程
# planner -> search_team -> (search) -> search_team -> planner (循环)
# 或者到达 reporter -> END
action_agent_builder.add_edge(START, "prepare_data")
action_agent_builder.add_edge("prepare_data", "planner")
action_agent_builder.add_edge("reporter", END)
action_agent_builder.add_edge("search", "search_team")

# 编译Graph
action_agent_graph = action_agent_builder.compile()


# ==========================================
# 测试代码
# ==========================================

if __name__ == "__main__":
    # 简单的测试流程
    import os
    import sys
    from pprint import pprint
    from langgraph.checkpoint.memory import MemorySaver
    
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)
    import dotenv
    dotenv.load_dotenv(os.path.join(project_root, '.env'))
    
    checkpointer = MemorySaver()
    chat_id = "fc5d21b7-0e45-08d8-2252-c59cf44104dd"
    user_id = "test_user_123"
    
    # 构造测试状态
    test_state = ActionFlowState(
        action_goal="找到并检查这个房间所有的能坐的位子",
        action_result="",
        observations=[],
        plan_iterations=0,
        current_plan=None,
        messages=[],
        session_id=chat_id,
        character_description="一个智能AI助手"
    )
    
    # 编译 graph
    test_graph = action_agent_graph
    thread_config = {
        "configurable": {
            "thread_id": "test_thread"
        },
        "recursion_limit": 100
    }

    # SpatialEntityManager().get_instance().add_entity(
    #     session_id="static",
    #     scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
    #     entity_type='object',
    #     entity_class="Aura",
    #     world_pos=np.array([950, 970, 0]),  # 使用计算出的边界框中心点
    #     world_bb=np.array([950, 970, 0, 10, 10, 10]),
    #     confidence=1.0,
    #     parent_id=None,
    #     max_age_sec=100000000.0,
    # )
    SpatialEntityManager().get_instance().update_item_position(
        session_id="static",
        scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
        entity_id="Aura_0",
        position=np.array([950, 970, 0])
    )
    SpatialEntityManager().get_instance().update_item_properties(
        session_id="static",
        scene_id="894a42a7-a517-4479-8233-75b0642d1aa6",
        entity_id="Aura_0",
        properties={"forward": [1, 0, 0]}
    )
    
    try:
        print("=== 开始执行测试 Action Agent Graph ===")
        # 执行 graph，stream 模式逐步输出状态变更
        for idx, event in enumerate(test_graph.stream(test_state, thread_config, stream_mode="updates")):
            print(f"\n---- Event #{idx} ----")
            # pprint(event)
    except Exception as e:
        print(f"执行测试Graph时出错: {str(e)}")
        import traceback
        traceback.print_exc()
