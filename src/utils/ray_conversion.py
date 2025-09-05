#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
屏幕坐标到射线转换工具
使用MVP逆矩阵将屏幕坐标转换为3D射线
"""

import numpy as np
from typing import Tuple, Optional

def screen_to_ray_robust(screen_x: float, screen_y: float, mvp_matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    更健壮的屏幕坐标到射线转换函数
    可以处理w分量为0的情况
    
    Args:
        screen_x: 屏幕X坐标
        screen_y: 屏幕Y坐标  
        mvp_matrix: MVP矩阵 (4x4)
        
    Returns:
        tuple: (ray_origin, ray_direction) 射线起点和方向向量
    """
    # 确保MVP矩阵是4x4的numpy数组
    mvp_matrix = np.array(mvp_matrix, dtype=np.float32)
    if mvp_matrix.shape != (4, 4):
        if mvp_matrix.size == 16:
            mvp_matrix = mvp_matrix.reshape(4, 4)
        else:
            raise ValueError(f"MVP矩阵必须是4x4，当前形状: {mvp_matrix.shape}")
    
    mvp_matrix = mvp_matrix.T
    mvp_inv = np.linalg.inv(mvp_matrix)
    
    pos_start = np.array([screen_x, screen_y, 0.001, 1], dtype=np.float32)
    pos_end = np.array([screen_x, screen_y, 0.5, 1], dtype=np.float32)
    
    world_start = mvp_inv @ pos_start
    world_end = mvp_inv @ pos_end
    
    world_start = world_start[:3] / world_start[3]
    world_end = world_end[:3] / world_end[3]
    
    ray_origin = world_start
    ray_direction = world_end - world_start
    ray_direction = ray_direction / np.linalg.norm(ray_direction)
    
    return ray_origin, ray_direction

def screen_to_ray(screen_x: float, screen_y: float, mvp_matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    将屏幕坐标转换为3D射线
    
    Args:
        screen_x: 屏幕X坐标
        screen_y: 屏幕Y坐标  
        mvp_matrix: MVP矩阵 (4x4)
        
    Returns:
        tuple: (ray_origin, ray_direction) 射线起点和方向向量
    """
    # 确保MVP矩阵是4x4的numpy数组
    mvp_matrix = np.array(mvp_matrix, dtype=np.float32)
    if mvp_matrix.shape != (4, 4):
        if mvp_matrix.size == 16:
            # 如果是1D数组，重塑为4x4
            mvp_matrix = mvp_matrix.reshape(4, 4)
        else:
            raise ValueError(f"MVP矩阵必须是4x4，当前形状: {mvp_matrix.shape}")
    
    # 屏幕坐标 (x, y, 0) 和 (x, y, 1) - 齐次坐标
    pos_start = np.array([screen_x, screen_y, 0, 1], dtype=np.float32)
    pos_end = np.array([screen_x, screen_y, 1, 1], dtype=np.float32)
    
    mvp_matrix = mvp_matrix.T
    # 计算MVP逆矩阵
    mvp_inv = np.linalg.inv(mvp_matrix)
    
    # 将屏幕坐标转换为世界坐标
    world_start = mvp_inv @ pos_start
    world_end = mvp_inv @ pos_end
    
    # 转换为非齐次坐标 (透视除法) - 添加安全检查
    if abs(world_start[3]) < 1e-6:
        raise ValueError("world_start[3] 接近零，无法进行透视除法")
    if abs(world_end[3]) < 1e-6:
        raise ValueError("world_end[3] 接近零，无法进行透视除法")
    
    world_start = world_start[:3] / world_start[3]
    world_end = world_end[:3] / world_end[3]
    
    # 计算射线起点和方向
    ray_origin = world_start
    ray_direction = world_end - world_start
    
    # 归一化方向向量
    ray_direction = ray_direction / np.linalg.norm(ray_direction)
    
    return ray_origin, ray_direction

def screen_to_ray_with_depth(screen_x: float, screen_y: float, depth: float, mvp_matrix: np.ndarray) -> np.ndarray:
    """
    将屏幕坐标和深度值转换为3D世界坐标
    
    Args:
        screen_x: 屏幕X坐标
        screen_y: 屏幕Y坐标
        depth: 深度值 (0-1)
        mvp_matrix: MVP矩阵 (4x4)
        
    Returns:
        np.ndarray: 3D世界坐标
    """
    # 确保MVP矩阵是4x4的numpy数组
    mvp_matrix = np.array(mvp_matrix, dtype=np.float32)
    if mvp_matrix.shape != (4, 4):
        if mvp_matrix.size == 16:
            # 如果是1D数组，重塑为4x4
            mvp_matrix = mvp_matrix.reshape(4, 4)
        else:
            raise ValueError(f"MVP矩阵必须是4x4，当前形状: {mvp_matrix.shape}")
    
    # 转置MVP矩阵
    mvp_matrix = mvp_matrix.T
    
    # 屏幕坐标 - 齐次坐标
    screen_pos = np.array([screen_x, screen_y, depth, 1], dtype=np.float32)
    
    # 计算MVP逆矩阵
    mvp_inv = np.linalg.inv(mvp_matrix)
    
    # 转换为世界坐标
    world_pos = mvp_inv @ screen_pos
    
    # 转换为非齐次坐标 - 添加安全检查
    if abs(world_pos[3]) < 1e-6:
        raise ValueError("world_pos[3] 接近零，无法进行透视除法")
    
    world_pos = world_pos[:3] / world_pos[3]
    
    return world_pos


def ray_intersect_plane(ray_origin: np.ndarray, ray_direction: np.ndarray, 
                       plane_point: np.ndarray, plane_normal: np.ndarray) -> Optional[np.ndarray]:
    """
    计算射线与平面的交点
    
    Args:
        ray_origin: 射线起点
        ray_direction: 射线方向向量
        plane_point: 平面上的一点
        plane_normal: 平面法向量
        
    Returns:
        Optional[np.ndarray]: 交点坐标，如果射线与平面平行则返回None
    """
    # 计算射线方向与平面法向量的点积
    denom = np.dot(ray_direction, plane_normal)
    
    # 如果点积接近0，说明射线与平面平行
    if abs(denom) < 1e-6:
        return None
    
    # 计算交点参数t
    t = np.dot(plane_point - ray_origin, plane_normal) / denom
    
    # 计算交点坐标
    intersection = ray_origin + t * ray_direction
    
    return intersection


def explain_w_component():
    """解释w分量为0的含义"""
    print("=== w分量为0的几何意义 ===")
    
    # 示例1: 正常的点
    point_normal = np.array([1, 2, 3, 1])  # w = 1
    print(f"正常点 [1, 2, 3, 1]:")
    print(f"  3D坐标: [{point_normal[0]/point_normal[3]:.1f}, {point_normal[1]/point_normal[3]:.1f}, {point_normal[2]/point_normal[3]:.1f}]")
    
    # 示例2: w = 0 的方向向量
    direction_vector = np.array([1, 2, 3, 0])  # w = 0
    print(f"\n方向向量 [1, 2, 3, 0]:")
    print(f"  表示方向: [1, 2, 3]")
    print(f"  长度: {np.linalg.norm(direction_vector[:3]):.3f}")
    print(f"  不能进行透视除法 (w=0)")
    
    # 示例3: 在射线转换中的含义
    print(f"\n在射线转换中:")
    print(f"  world_start[3] = 0 意味着起点在无穷远处")
    print(f"  world_end[3] = 0 意味着终点在无穷远处")
    print(f"  这通常表示MVP矩阵有问题或变换无效")
    
    # 示例4: 可能的解决方案
    print(f"\n可能的解决方案:")
    print(f"  1. 检查MVP矩阵是否正确")
    print(f"  2. 检查屏幕坐标是否在有效范围内")
    print(f"  3. 使用不同的深度值 (0.1 而不是 0)")


def test_ray_conversion():
    """测试射线转换功能"""
    print("=== 射线转换测试 ===")
    
    # 测试坐标
    test_x, test_y = 100, 200
    
    try:
        # 测试1: 4x4矩阵
        print("\n--- 测试1: 4x4矩阵 (会自动转置) ---")
        mvp_matrix_4x4 = np.eye(4, dtype=np.float32)
        print(f"原始MVP矩阵:\n{mvp_matrix_4x4}")
        ray_origin, ray_direction = screen_to_ray(test_x, test_y, mvp_matrix_4x4)
        
        print(f"屏幕坐标: ({test_x}, {test_y})")
        print(f"射线起点: {ray_origin}")
        print(f"射线方向: {ray_direction}")
        print(f"方向向量长度: {np.linalg.norm(ray_direction)}")
        
        # 测试2: 1D数组 (16个元素)
        print("\n--- 测试2: 1D数组重塑为4x4 ---")
        mvp_matrix_1d = np.eye(4).flatten()  # 16个元素的1D数组
        ray_origin2, ray_direction2 = screen_to_ray(test_x, test_y, mvp_matrix_1d)
        
        print(f"1D数组形状: {mvp_matrix_1d.shape}")
        print(f"射线起点: {ray_origin2}")
        print(f"射线方向: {ray_direction2}")
        
        # 测试深度转换
        print("\n--- 测试深度转换 ---")
        depth_point = screen_to_ray_with_depth(test_x, test_y, 0.5, mvp_matrix_4x4)
        print(f"深度0.5的世界坐标: {depth_point}")
        
        # 测试射线与平面交点
        print("\n--- 测试射线与平面交点 ---")
        plane_point = np.array([0, 0, 0])
        plane_normal = np.array([0, 0, 1])  # XY平面
        
        intersection = ray_intersect_plane(ray_origin, ray_direction, plane_point, plane_normal)
        if intersection is not None:
            print(f"与XY平面的交点: {intersection}")
        else:
            print("射线与XY平面平行")
            
        # 测试3: 错误的矩阵形状
        print("\n--- 测试3: 错误矩阵形状 ---")
        try:
            wrong_matrix = np.array([[1, 2, 3], [4, 5, 6]])  # 2x3矩阵
            screen_to_ray(test_x, test_y, wrong_matrix)
        except ValueError as e:
            print(f"预期的错误: {e}")
            
        # 测试4: 可能导致除零的矩阵
        print("\n--- 测试4: 可能导致除零的矩阵 ---")
        try:
            # 创建一个可能导致w分量为0的矩阵
            problematic_matrix = np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0], 
                [0, 0, 1, 0],
                [0, 0, 0, 0]  # 这会导致w分量为0
            ], dtype=np.float32)
            screen_to_ray(test_x, test_y, problematic_matrix)
        except ValueError as e:
            print(f"预期的除零错误: {e}")
            
    except Exception as e:
        print(f"测试失败: {e}")


if __name__ == "__main__":
    explain_w_component()
    print("\n" + "="*50 + "\n")
    test_ray_conversion()
