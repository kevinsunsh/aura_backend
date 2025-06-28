#!/bin/bash

# 设置新版本号
NEW_VERSION="0.0.1"

# 构建 Docker 镜像
docker build --platform=linux/amd64 --no-cache -t dcc-cloud-cn-beijing.cr.volces.com/dcc-cloud/aura_backend:${NEW_VERSION} -f ../../src/Dockerfile ../../src

# 推送 Docker 镜像
docker push dcc-cloud-cn-beijing.cr.volces.com/dcc-cloud/aura_backend:${NEW_VERSION}

# 更新 s.yaml 中的版本号
awk -v new_version="${NEW_VERSION}" '/version:/{sub(/"[0-9]+\.[0-9]+\.[0-9]+"/, "\"" new_version "\"")}1' s.yaml > s.yaml.tmp && mv s.yaml.tmp s.yaml

# 部署
s deploy