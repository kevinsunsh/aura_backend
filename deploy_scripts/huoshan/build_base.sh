#!/bin/bash

docker build --platform=linux/amd64 --no-cache -t dcc-cloud-cn-beijing.cr.volces.com/dcc-cloud/aura_backend:basev1 -f ../../src/Dockerfile_base ../../src

# 推送 Docker 镜像
docker push dcc-cloud-cn-beijing.cr.volces.com/dcc-cloud/aura_backend:basev1
