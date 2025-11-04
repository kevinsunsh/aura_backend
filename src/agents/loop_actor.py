import pykka
import asyncio
from loguru import logger
from api_protocol.constant import *
from utils.utils import safe_call
from typing import Any, Dict, Optional, Callable
from agents.agent_memory.prompt_manager.scene_iteams.manager import DBManager as SceneItemEntryManager
from agents.agent_memory.prompt_manager.char_instance_info.manager import DBManager as CharInstanceInfoManager
import numpy as np
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union, linemerge
from scipy.signal import find_peaks
from collections import defaultdict
from agents.agent_memory.prompt_manager.spatial_entity.manager import DBManager as SpatialEntityManager

class LoopActor(pykka.ThreadingActor):
    """Loop Actor - 事件循环"""
    def __init__(self, output_callback: Optional[Callable] = None):
        super().__init__()
        self.output_callback = output_callback
        self.is_running = False
        self.chat_id = None
        self.user_id = None
        self.last_timestamp = 0
    
    def on_receive(self, message):
        """处理接收到的消息"""
        try:
            msg_type = message.get("type")
            if msg_type == "start":
                return self._start_process(message.get("data", {}))
            elif msg_type == "stop":
                return self._stop_process()
            elif msg_type == "input":
                return self._update()
            elif msg_type == "change_scene":
                return self._change_scene(message.get("data", {}))
            elif msg_type == "set_callback":
                self.output_callback = message.get("callback")
                return {"success": True}
            else:
                return {"error": f"Unknown message type: {msg_type}"}
        except Exception as e:
            logger.error(f"Loop Actor处理消息失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _start_process(self, data):
        """启动Loop客户端"""
        try:
            self.chat_id = data.get("chat_id")
            self.user_id = data.get("user_id")
            if not self.chat_id or not self.user_id:
                return {"success": False, "error": "Missing chat_id or user_id"}
            self.is_running = True
            logger.info(f"Loop Actor启动成功: chat_id={self.chat_id}, user_id={self.user_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Loop Actor启动失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _stop_process(self):
        """停止Loop客户端"""
        try:
            self.is_running = False
            logger.info("Loop Actor停止成功")
            return {"success": True}
        except Exception as e:
            logger.error(f"Loop Actor停止失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _run_async(self, coro):
        try:
            asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
            finally:
                loop.close()
    
    def _update(self):
        """处理音频输入"""
        if not self.is_running:
            return {"success": False, "error": "Loop Actor未运行"}
        char_instance_info = CharInstanceInfoManager().get_char_instance_info_by_user_and_chat_id(self.user_id, self.chat_id)
        current_scene_id = char_instance_info.current_scene_id if char_instance_info else "d8943faa-bf00-481b-95af-c73bd04c1eb7"
        result = SceneItemEntryManager().get_scene_items_by_timestamp(self.last_timestamp, current_scene_id)
        self.last_timestamp = result["latest_timestamp"] + 1
        items = result["items"]
        try:
            self._run_async(safe_call(self.output_callback,{
                    "event": ServerEvent.EnvStatus,
                    "payload_msg": {
                        "items": [{"item_id": item.item_id, "description": item.description, "bbox": [item.world_bb_x, item.world_bb_y, item.world_bb_z, item.world_bb_w, item.world_bb_h, item.world_bb_d]} for item in items]
                    }
                }))
            return {"success": True}
        except Exception as e:
            logger.error(f"Loop处理音频失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _change_scene(self, data):
        """切换场景"""
        try:
            self.last_timestamp = 0
            navmesh_triangles = data.get("navmesh_triangles")
            if navmesh_triangles:
                layers = self._navmesh_triangle_list_to_2d_layers(navmesh_triangles)
                for layer in layers:
                    SpatialEntityManager().add_region(
                        session_id=self.chat_id,
                        scene_id=self.scene_id,
                        entity_type="region",
                        entity_class="navmesh",
                        outer_points=layer["exterior"],
                        inner_points=layer["interiors"],
                        confidence=1.0,
                        parent_id=None
                    )
            return {"success": True}
        except Exception as e:
            logger.error(f"切换场景失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _navmesh_indexed_to_2d_layers(self, vertices, indices):
        """
        输入:
            vertices: list of [x, y, z] (or Nx3 array)
            indices:  list of int, length must be divisible by 3
                    e.g., [0,1,2, 1,2,3, ...] → triangles (v0,v1,v2), (v1,v2,v3), ...

        输出:
            同前：多层2D边界 + 连接点
        """
        import numpy as np
        from shapely.geometry import Polygon, LineString, Point
        from shapely.ops import unary_union, linemerge
        from scipy.signal import find_peaks
        from collections import defaultdict

        # --- 解析 vertices ---
        verts = np.array(vertices, dtype=np.float64)
        if verts.ndim != 2 or verts.shape[1] != 3:
            raise ValueError("vertices must be a list of [x, y, z] points (shape Nx3).")

        # --- 解析 indices ---
        idx = np.array(indices, dtype=np.int64)
        if idx.size % 3 != 0:
            raise ValueError("indices length must be divisible by 3.")
        if idx.min() < 0 or idx.max() >= len(verts):
            raise ValueError("indices out of range for vertices.")

        # --- 构建三角形数组 (M, 3, 3) ---
        tri_indices = idx.reshape(-1, 3)  # (M, 3)
        triangles_3d = verts[tri_indices]  # (M, 3, 3)

        return self._process_triangles_3d(triangles_3d)
    
    def _navmesh_triangle_list_to_2d_layers(self, navmesh_triangles):
        """
        输入: triangle list
            格式1（推荐）: [[x0,y0,z0], [x1,y1,z1], [x2,y2,z2], [x3,y3,z3], ...] 
            格式2（展平）: [x0,y0,z0, x1,y1,z1, x2,y2,z2, x3,y3,z3, ...]
            → 每连续3个点构成一个三角形（无重叠）
        
        输出: 多层2D边界 + 连接点（结构见下文）
        """
        # 解析输入
        pts = np.array(navmesh_triangles, dtype=np.float64)
        if pts.size == 0:
            return {}
        if pts.ndim == 1:
            if len(pts) % 9 != 0:  # 每个三角形9个数 (3点×3坐标)
                raise ValueError("For triangle list, total float count must be divisible by 9.")
            triangles_3d = pts.reshape(-1, 3, 3)
        elif pts.ndim == 2:
            if pts.shape[1] != 3:
                raise ValueError("Each vertex must be [x, y, z].")
            if len(pts) % 3 != 0:
                raise ValueError("Vertex count must be divisible by 3 for triangle list.")
            triangles_3d = pts.reshape(-1, 3, 3)
        else:
            raise ValueError("Invalid input shape.")

        return self._process_triangles_3d(triangles_3d)

    def _navmesh_triangle_strip_to_2d_layers(self, navmesh_vertices):
        """
        输入: triangle strip
            格式1（推荐）: [[x0,y0,z0], [x1,y1,z1], [x2,y2,z2], [x3,y3,z3], ...]
            格式2（展平）: [x0,y0,z0, x1,y1,z1, x2,y2,z2, x3,y3,z3, ...]
            → 生成三角形: (v0,v1,v2), (v1,v2,v3), (v2,v3,v4), ...
        
        输出: 同上
        """
        pts = np.array(navmesh_vertices, dtype=np.float64)
        if pts.size == 0:
            return {}
        if pts.ndim == 1:
            if len(pts) % 3 != 0:
                raise ValueError("Vertex count must be divisible by 3.")
            pts = pts.reshape(-1, 3)
        elif pts.ndim == 2:
            if pts.shape[1] != 3:
                raise ValueError("Each vertex must be [x, y, z].")
        else:
            raise ValueError("Invalid input shape.")

        N = len(pts)
        if N < 3:
            return {}

        # Convert strip to triangle list
        triangles_3d = np.array([
            [pts[i], pts[i+1], pts[i+2]]
            for i in range(N - 2)
        ])

        return self._process_triangles_3d(triangles_3d)

    def _process_triangles_3d(self, triangles_3d):
        """内部函数：从 (N, 3, 3) 三角形数组生成多层2D边界"""
        if len(triangles_3d) == 0:
            return {}

        tri_y_min = triangles_3d[:, :, 1].min(axis=1)
        tri_y_max = triangles_3d[:, :, 1].max(axis=1)
        tri_centers_y = (tri_y_min + tri_y_max) / 2.0

        # === 自动分层 ===
        y_vals = tri_centers_y
        y_min_global, y_max_global = y_vals.min(), y_vals.max()

        if y_max_global - y_min_global < 0.5:
            floor_ranges = [(y_min_global - 0.5, y_max_global + 0.5)]
        else:
            hist_bin_width = 0.15
            min_floor_height = 1.8
            peak_prominence = 0.15

            n_bins = max(20, int((y_max_global - y_min_global) / hist_bin_width))
            hist, bin_edges = np.histogram(y_vals, bins=n_bins)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
            hist_norm = hist / hist.max() if hist.max() > 0 else hist

            min_distance_bins = int(min_floor_height / hist_bin_width)
            peaks, _ = find_peaks(
                hist_norm,
                prominence=peak_prominence,
                distance=min_distance_bins
            )

            if len(peaks) == 0:
                floor_ranges = [(y_min_global - 0.5, y_max_global + 0.5)]
            else:
                peak_ys = bin_centers[peaks]
                floor_ranges = []
                for i, yc in enumerate(peak_ys):
                    half_h = min_floor_height / 2
                    y_low = yc - half_h
                    y_high = yc + half_h
                    if floor_ranges and y_low < floor_ranges[-1][1]:
                        y_low = (floor_ranges[-1][1] + yc) / 2
                        y_high = y_low + min_floor_height
                    floor_ranges.append((y_low, y_high))

        layer_boundaries = [floor_ranges[i][1] for i in range(len(floor_ranges) - 1)]

        # === 找跨层三角形 ===
        cross_layer_info = []
        for i, y_boundary in enumerate(layer_boundaries):
            mask = (tri_y_min < y_boundary) & (tri_y_max > y_boundary)
            for tri in triangles_3d[mask]:
                cross_layer_info.append((tri, i, i + 1))

        # === 构建每层多边形 ===
        layers = {}
        for layer_id, (y_low, y_high) in enumerate(floor_ranges):
            mask = (tri_centers_y >= y_low) & (tri_centers_y < y_high)
            tris = triangles_3d[mask]
            if len(tris) == 0:
                continue

            tris_2d = tris[:, :, [0, 2]]
            polys = []
            for tri in tris_2d:
                if (np.linalg.norm(tri[0] - tri[1]) < 1e-6 or
                    np.linalg.norm(tri[1] - tri[2]) < 1e-6 or
                    np.linalg.norm(tri[0] - tri[2]) < 1e-6):
                    continue
                p = Polygon(tri)
                if p.is_valid and not p.is_empty and p.area >= 1e-3:
                    polys.append(p)

            if not polys:
                continue

            merged = unary_union(polys)
            if merged.is_empty:
                continue
            if merged.geom_type == 'MultiPolygon':
                merged = unary_union(merged)
            if merged.geom_type != 'Polygon':
                continue

            # Exterior
            ext = list(merged.exterior.coords)
            if len(ext) > 1 and np.allclose(ext[0], ext[-1]):
                ext = ext[:-1]
            exterior = [(float(x), float(z)) for x, z in ext]

            # Interiors
            interiors = []
            for ring in merged.interiors:
                r = list(ring.coords)
                if len(r) > 1 and np.allclose(r[0], r[-1]):
                    r = r[:-1]
                interiors.append([(float(x), float(z)) for x, z in r])

            layers[layer_id] = {
                "y_range": (float(y_low), float(y_high)),
                "exterior": exterior,
                "interiors": interiors,
                "vertical_connections": []
            }

        # === 检测连接点 ===
        if not cross_layer_info or len(layers) < 2:
            return layers

        groups = defaultdict(list)
        for tri_3d, lower_id, upper_id in cross_layer_info:
            if lower_id in layers and upper_id in layers:
                tri_2d = tri_3d[:, [0, 2]]
                groups[(lower_id, upper_id)].append(tri_2d)

        for (lower_id, upper_id), tri_list in groups.items():
            polys = [Polygon(t) for t in tri_list if Polygon(t).is_valid and not Polygon(t).is_empty]
            if not polys:
                continue
            conn_region = unary_union(polys)
            if conn_region.is_empty:
                continue

            def get_full_boundary(layer_data):
                coords = layer_data["exterior"]
                lines = [LineString(coords + [coords[0]])] if len(coords) > 1 else []
                for hole in layer_data["interiors"]:
                    if len(hole) > 1:
                        lines.append(LineString(hole + [hole[0]]))
                return linemerge(lines) if lines else LineString()

            lower_boundary = get_full_boundary(layers[lower_id])
            upper_boundary = get_full_boundary(layers[upper_id])

            SEARCH_RADIUS = 0.6

            def extract_gap_endpoints(boundary_line, region, radius):
                if boundary_line.is_empty:
                    return []
                segments = []
                if boundary_line.geom_type == 'LineString':
                    c = list(boundary_line.coords)
                    segments = [(c[i], c[i+1]) for i in range(len(c)-1)]
                elif boundary_line.geom_type == 'MultiLineString':
                    for line in boundary_line.geoms:
                        c = list(line.coords)
                        segments.extend([(c[i], c[i+1]) for i in range(len(c)-1)])
                
                near_points = []
                for p1, p2 in segments:
                    mid = Point((p1[0]+p2[0])/2, (p1[1]+p2[1])/2)
                    if mid.distance(region) <= radius:
                        near_points.extend([p1, p2])
                
                if not near_points:
                    return []
                
                unique = []
                for pt in near_points:
                    if not any(np.hypot(pt[0]-q[0], pt[1]-q[1]) < 1e-3 for q in unique):
                        unique.append(pt)
                
                if len(unique) < 2:
                    return unique
                return [unique[0], unique[-1]]

            lower_points = extract_gap_endpoints(lower_boundary, conn_region, SEARCH_RADIUS)
            upper_points = extract_gap_endpoints(upper_boundary, conn_region, SEARCH_RADIUS)

            if len(lower_points) >= 2:
                layers[lower_id]["vertical_connections"].append({
                    "to_layer": upper_id,
                    "connection_points": [(float(x), float(z)) for x, z in lower_points[:2]]
                })
            if len(upper_points) >= 2:
                layers[upper_id]["vertical_connections"].append({
                    "to_layer": lower_id,
                    "connection_points": [(float(x), float(z)) for x, z in upper_points[:2]]
                })

        return layers
