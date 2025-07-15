#!/bin/bash

# 设置变量
LOCAL_IMAGE="mengs-cn-shanghai.cr.volces.com/aura/aura_backend:0.0.3"
NEW_TAG="0.0.3"
REMOTE_REPO="mengs-cn-beijing.cr.volces.com/aura/aura_backend"

echo "开始推送Docker镜像..."
echo "源镜像: ${LOCAL_IMAGE}"
echo "目标仓库: ${REMOTE_REPO}:${NEW_TAG}"

# 1. 给本地镜像打新标签（指向北京区域）
echo "给镜像打新标签: ${LOCAL_IMAGE} -> ${REMOTE_REPO}:${NEW_TAG}"
docker tag ${LOCAL_IMAGE} ${REMOTE_REPO}:${NEW_TAG}

# 2. 推送镜像到北京区域仓库
echo "推送镜像到北京区域仓库..."
docker push ${REMOTE_REPO}:${NEW_TAG}

# 3. 检查推送结果
if [ $? -eq 0 ]; then
    echo "✅ 镜像推送成功!"
    echo "推送的镜像: ${REMOTE_REPO}:${NEW_TAG}"
else
    echo "❌ 镜像推送失败!"
    exit 1
fi

# 4. 显示本地镜像列表
echo ""
echo "本地aura相关镜像:"
docker images | grep aura

# 5. 清理临时标签（可选）
echo ""
echo "是否要删除临时标签? (y/n)"
read -r response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    docker rmi ${REMOTE_REPO}:${NEW_TAG}
    echo "临时标签已删除"
fi 