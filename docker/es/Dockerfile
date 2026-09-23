# Elasticsearch 8.13.4 + IK 中文分词插件
# 插件版本必须与 ES 版本精确一致
FROM docker.elastic.co/elasticsearch/elasticsearch:8.13.4

ARG ES_VERSION=8.13.4
# 国内网络失败时，可手动下载对应版本 zip：
#   https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-${ES_VERSION}.zip
# 然后改为 COPY 挂载安装
RUN bin/elasticsearch-plugin install --batch \
    "https://get.infini.cloud/elasticsearch/analysis-ik/${ES_VERSION}"
