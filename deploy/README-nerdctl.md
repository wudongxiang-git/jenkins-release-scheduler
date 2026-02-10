# 使用 nerdctl 打包部署

在 containerd / nerdctl 环境（如 K8s 节点、与 Jenkins 同机）下构建并运行本服务。

## 一、构建镜像

在项目根目录执行：

```bash
# 默认镜像名 jenkins-release-scheduler:latest
nerdctl build -t jenkins-release-scheduler:latest .
```

或使用脚本（可指定镜像名与 tag）：

```bash
cd deploy
chmod +x nerdctl-build.sh
./nerdctl-build.sh
```

自定义镜像名/tag：

```bash
IMAGE_NAME=my-registry.io/lingong/jenkins-release-scheduler IMAGE_TAG=v1.0 ./nerdctl-build.sh
```

## 二、运行容器

**必须**提供 `JENKINS_URL`、`JENKINS_API_TOKEN`，其余为可选。

```bash
export JENKINS_URL=http://jenkins:8080
export JENKINS_API_TOKEN=your-token
export FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx   # 可选
export APP_BASE_URL=https://release.example.com                              # 可选，飞书卡片链接

nerdctl run -d \
  --name jenkins-release-scheduler \
  -p 5000:5000 \
  -v /path/to/data:/data \
  -e JENKINS_URL \
  -e JENKINS_API_TOKEN \
  -e JENKINS_USERNAME \
  -e FEISHU_WEBHOOK_URL \
  -e APP_BASE_URL \
  -e TZ=Asia/Shanghai \
  -e DATABASE_PATH=/data/release_plans.db \
  jenkins-release-scheduler:latest
```

或使用脚本（数据目录默认为当前目录下 `./data`）：

```bash
export JENKINS_URL=http://jenkins:8080
export JENKINS_API_TOKEN=your-token
./nerdctl-run.sh
```

## 三、推送到私有镜像仓库（可选）

若需推送到与流水线一致的私有仓库（如 `registry.iotcloud.local`）：

```bash
nerdctl tag jenkins-release-scheduler:latest registry.iotcloud.local/lingong/jenkins-release-scheduler:latest
nerdctl push registry.iotcloud.local/lingong/jenkins-release-scheduler:latest
```

推送前需登录：

```bash
nerdctl login -u <用户名> --password-stdin registry.iotcloud.local
```

## 四、常用命令

```bash
# 查看日志
nerdctl logs -f jenkins-release-scheduler

# 停止并删除容器
nerdctl stop jenkins-release-scheduler
nerdctl rm jenkins-release-scheduler
```

## 五、与现有 Dockerfile 的关系

项目根目录的 `Dockerfile` 与 `docker build` / `nerdctl build` 完全兼容，无需修改。直接使用：

- `nerdctl build -t <镜像名>:<tag> .` 在项目根目录执行即可。
