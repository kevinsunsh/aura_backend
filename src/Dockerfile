FROM dcc-cloud-cn-beijing.cr.volces.com/dcc-cloud/aura_backend:basev1

WORKDIR /opt/application
USER root
COPY . .
EXPOSE 8000
# 添加执行权限
RUN chmod +x /opt/application/run.sh
CMD ["bash", "/opt/application/run.sh"]