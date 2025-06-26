#!/bin/bash

docker build --platform=linux/amd64 --no-cache -t unity-data-cn-shanghai.cr.volces.com/data-platform/nova-backend:basev1 -f ../../Dockerfile_base ../..

# 推送 Docker 镜像
docker push unity-data-cn-shanghai.cr.volces.com/data-platform/nova-backend:basev1