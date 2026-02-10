# Jenkins 定时发版 Web 服务

一个轻量级的 Web 服务，用于创建 Jenkins 定时发版计划，支持多任务选择、参数配置、自动触发和结果通知。

## 功能特性

- ✅ 从 Jenkins 自动拉取任务列表（支持 Folder）
- ✅ 创建发版计划：选择任务、设置执行时间、配置参数（分支/操作/pod_num）
- ✅ **可配置 GitLab + Jenkins 参数**：支持多种仓库管理方式（首期 GitLab），通过「配置」页维护 GitLab 连接、配置字典、Jenkins 参数配置；分支从 GitLab 动态拉取，操作等下拉可来自配置字典或内联选项
- ✅ **文件夹/任务就近原则**：每个树节点（文件夹）只需选择「Jenkins 参数配置」即可供下级 job 或自身使用；「GitLab 项目」为可选（用于分支下拉），未配置时分支可手动填写
- ✅ 到点自动触发 Jenkins buildWithParameters
- ✅ 轮询每个任务的构建结果
- ✅ 飞书群机器人通知（包含计划和每项任务完成情况）
- ✅ 统一使用东八区时间

## 环境要求

- Python 3.11+
- Docker（用于容器化部署）
- Jenkins（需要 API Token）
- 飞书群机器人 Webhook（可选）

## 配置说明

通过环境变量配置：

| 环境变量 | 说明 | 必填 | 默认值 |
|---------|------|------|--------|
| `JENKINS_URL` | Jenkins 地址 | 是 | `http://localhost:8080` |
| `JENKINS_API_TOKEN` | Jenkins API Token | 是 | - |
| `JENKINS_USERNAME` | Jenkins 用户名（可选，若 Token 已包含用户信息） | 否 | - |
| `FEISHU_WEBHOOK_URL` | 飞书群机器人 Webhook URL | 否 | - |
| `DATABASE_PATH` | SQLite 数据库文件路径 | 否 | `/data/release_plans.db` |
| `TZ` | 时区（统一使用东八区） | 否 | `Asia/Shanghai` |
| `POLL_INTERVAL` | 轮询构建结果的间隔（秒） | 否 | `20` |
| `POLL_TIMEOUT` | 单任务轮询超时时间（秒） | 否 | `1800`（30分钟） |
| `SCHEDULER_INTERVAL` | 调度器扫描间隔（秒） | 否 | `60`（1分钟） |

## 本地运行

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 设置环境变量（或创建 `.env` 文件）：
```bash
export JENKINS_URL=http://your-jenkins:8080
export JENKINS_API_TOKEN=your-token
export FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
export TZ=Asia/Shanghai
```

3. 运行应用：
```bash
python app.py
```

或使用 Gunicorn：
```bash
gunicorn -w 1 -b 0.0.0.0:5000 app:app
```

访问 http://localhost:5000

## PyCharm 中运行

### 1. 打开项目

- **File → Open**，选择 `jenkins-release-scheduler` 目录，以项目方式打开。

### 2. 配置 Python 解释器

- **File → Settings**（Windows/Linux）或 **PyCharm → Preferences**（macOS）
- 进入 **Project: jenkins-release-scheduler → Python Interpreter**
- 点击右上角齿轮 → **Add...** → **Virtualenv Environment**
  - 选 **New**，Location 用默认的 `venv` 即可，Base interpreter 选本机 Python 3.11+
  - 确定后等待 PyCharm 创建虚拟环境

### 3. 安装依赖

- 在项目根目录右键 `requirements.txt` → **Run 'pip install -r requirements.txt'**
- 或在底部 **Terminal** 中执行：
  ```bash
  pip install -r requirements.txt
  ```

### 4. 配置运行（Run Configuration）

- **Run → Edit Configurations...**
- 点击 **+** → **Python**
- 配置如下：
  - **Name**：`Jenkins Release Scheduler`（或任意名称）
  - **Script path**：选项目根目录下的 `app.py`（或改为 **Module name** 不填，用 **Script path** 指向 `app.py`）
  - **Working directory**：选项目根目录 `jenkins-release-scheduler`
  - **Python interpreter**：选上一步创建的虚拟环境

- **环境变量**（必填项建议都设好）：
  - 点击 **Environment variables** 右侧的 **📋** 图标
  - 添加例如（按你的实际环境修改）：
    | Name | Value |
    |------|--------|
    | `JENKINS_URL` | `http://192.168.14.10:38080` |
    | `JENKINS_API_TOKEN` | 你的 Jenkins API Token |
    | `JENKINS_USERNAME` | Jenkins 用户名（可选） |
    | `FEISHU_WEBHOOK_URL` | 飞书机器人 Webhook（可选） |
    | `TZ` | `Asia/Shanghai` |
    | `DATABASE_PATH` | `./data/release_plans.db`（本地调试用当前目录下的 `data`） |

- 本地调试时可将 **DATABASE_PATH** 设为 `./data/release_plans.db`，避免写系统目录；首次运行前可先建好 `data` 目录（或由程序自动创建）。
- 点击 **Apply** → **OK**。

### 5. 运行

- 点击右上角运行按钮（绿色三角）或 **Run → Run 'Jenkins Release Scheduler'**
- 控制台出现 `* Running on http://0.0.0.0:5000` 后，在浏览器访问：**http://localhost:5000**

### 6. 可选：用 EnvFile 插件管理环境变量

- **File → Settings → Plugins**，搜索 **EnvFile** 并安装，重启 PyCharm
- 在项目根目录创建 `.env` 文件（不要提交到 Git），内容示例：
  ```
  JENKINS_URL=http://192.168.14.10:38080
  JENKINS_API_TOKEN=your-token
  FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  TZ=Asia/Shanghai
  DATABASE_PATH=./data/release_plans.db
  ```
- 在 **Edit Configurations** 中，勾选 **Enable EnvFile**，添加 `.env`，保存后运行时会自动加载这些变量。

---

## Docker 部署

### 构建镜像

```bash
docker build -t jenkins-release-scheduler:latest .
```

### 运行容器

```bash
docker run -d \
  --name jenkins-release-scheduler \
  -p 5000:5000 \
  -v /path/to/data:/data \
  -e JENKINS_URL=http://jenkins:8080 \
  -e JENKINS_API_TOKEN=your-token \
  -e FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx \
  -e TZ=Asia/Shanghai \
  jenkins-release-scheduler:latest
```

## nerdctl 打包部署

在 containerd / nerdctl 环境（如 K8s 节点、与 Jenkins 同机）下构建与运行，使用同一份 Dockerfile 即可。

### 构建镜像

```bash
nerdctl build -t jenkins-release-scheduler:latest .
```

### 运行容器

```bash
export JENKINS_URL=http://jenkins:8080
export JENKINS_API_TOKEN=your-token

nerdctl run -d \
  --name jenkins-release-scheduler \
  -p 5000:5000 \
  -v /path/to/data:/data \
  -e JENKINS_URL \
  -e JENKINS_API_TOKEN \
  -e FEISHU_WEBHOOK_URL \
  -e TZ=Asia/Shanghai \
  -e DATABASE_PATH=/data/release_plans.db \
  jenkins-release-scheduler:latest
```

### 推送到私有镜像仓库

若使用与流水线一致的私有仓库（如 `registry.iotcloud.local`）：

```bash
nerdctl tag jenkins-release-scheduler:latest registry.iotcloud.local/lingong/jenkins-release-scheduler:latest
nerdctl push registry.iotcloud.local/lingong/jenkins-release-scheduler:latest
```

更多说明与脚本见 [deploy/README-nerdctl.md](deploy/README-nerdctl.md)。

## Rancher 部署

### 1. 创建 ConfigMap（环境变量）

在 Rancher 中创建 ConfigMap，包含以下配置：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: jenkins-release-scheduler-config
data:
  JENKINS_URL: "http://jenkins:8080"
  TZ: "Asia/Shanghai"
  POLL_INTERVAL: "20"
  POLL_TIMEOUT: "1800"
  SCHEDULER_INTERVAL: "60"
```

### 2. 创建 Secret（敏感信息）

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: jenkins-release-scheduler-secret
type: Opaque
stringData:
  JENKINS_API_TOKEN: "your-token"
  FEISHU_WEBHOOK_URL: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
```

### 3. 创建 Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jenkins-release-scheduler
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jenkins-release-scheduler
  template:
    metadata:
      labels:
        app: jenkins-release-scheduler
    spec:
      containers:
      - name: app
        image: jenkins-release-scheduler:latest
        ports:
        - containerPort: 5000
        env:
        - name: DATABASE_PATH
          value: "/data/release_plans.db"
        envFrom:
        - configMapRef:
            name: jenkins-release-scheduler-config
        - secretRef:
            name: jenkins-release-scheduler-secret
        volumeMounts:
        - name: data
          mountPath: /data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: jenkins-release-scheduler-pvc
```

### 4. 创建 PVC（持久化存储）

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jenkins-release-scheduler-pvc
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

### 5. 创建 Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: jenkins-release-scheduler
spec:
  selector:
    app: jenkins-release-scheduler
  ports:
  - port: 5000
    targetPort: 5000
```

### 6. 创建 Ingress（可选）

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: jenkins-release-scheduler-ingress
spec:
  rules:
  - host: release-scheduler.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: jenkins-release-scheduler
            port:
              number: 5000
```

## Jenkins 配置

### 1. 创建 API Token

1. 登录 Jenkins
2. 点击用户名 → Configure
3. 在 "API Token" 部分点击 "Add new Token"
4. 生成 Token 并保存

### 2. 权限要求

API Token 对应的用户需要以下权限：
- `Overall/Read`（查看任务列表）
- `Job/Build`（触发构建）
- `Job/Read`（查看构建状态）

## 飞书配置

1. 在飞书群中添加「自定义机器人」
2. 获取 Webhook URL
3. 将 URL 配置到 `FEISHU_WEBHOOK_URL` 环境变量

## 使用说明

1. **创建发版计划**：
   - 访问首页，选择要发版的任务（可多选）
   - 设置计划执行时间（东八区）
   - 可选：设置默认分支
   - 可选：为每个任务单独配置分支/操作/pod_num
   - 点击「创建发版计划」

2. **查看计划列表**：
   - 访问「发版计划列表」页面
   - 查看所有计划的状态和执行情况
   - 点击「查看详情」查看每个任务的详细结果

3. **自动执行**：
   - 调度器每分钟扫描一次待执行的计划
   - 到点后自动触发所有选中的 Jenkins 任务
   - 轮询每个任务的构建结果（每 20 秒一次，最多等待 30 分钟）
   - 所有任务完成后发送飞书通知

## 注意事项

- **时区**：系统统一使用东八区（Asia/Shanghai），前端时间选择器也会按东八区显示
- **数据库**：SQLite 文件存储在 `/data` 目录，部署时需挂载持久化卷
- **单实例**：当前设计为单实例运行，多副本部署可能导致重复执行（建议使用 StatefulSet + 共享存储或后续改造为分布式锁）
- **Jenkins 参数**：本应用会按每个任务从 Jenkins 读取参数定义，自动识别「分支 / 操作 / Pod 数量」对应的参数名并提交，因此可同时支持从 GitLab 拉取的任务（如 `BRANCH_TAG`）和从云效拉取的任务（如 `GIT_BRANCH`、`操作` 等），无需统一各 Job 的参数名。
- **系统配置（/config）**：在「配置」页可维护：① **GitLab 连接**（名称、Base URL、Private Token）；② **配置字典**（名称、描述、选项列表，供下拉复用）；③ **Jenkins 参数配置**（名称、可选关联 GitLab、param_definitions JSON：参数名、类型 dropdown/number/text、来源 gitlab_branches/字典/内联 options、allow_empty 等）。文件夹在树节点上选择「参数配置」即可生效；可选选「GitLab 项目」以启用分支下拉，未选时分支需手动填写。匹配按**就近原则**。

### 为什么 Git Parameter（分支）的 choices 是空 []

Jenkins 的 **Git Parameter 插件**里，分支/标签列表是**动态加载**的，不会保存在任务配置里，也不会通过「任务 API」的 `parameterDefinitions` 返回。

- **在 Jenkins 里**：只有当你打开「Build with Parameters」页面时，插件才会去查 Git 仓库（`git ls-remote` 等），在服务端生成当前分支/标签列表，再渲染到页面的下拉框里。
- **任务 API**（如 `tree=property[parameterDefinitions[...]]`）只导出**参数定义**（名称、类型、默认值、branchFilter 等），**不包含**这次动态算出来的列表，所以接口里看到的 `choices` 一直是 `[]`。

因此本应用在「获取任务参数」时，对分支只能拿到**默认值**（如 `develop`），拿不到完整分支列表；前端会显示为**文本框 + 默认值**，你可以手动改成分支名，或保持默认。若希望在本应用里也出现分支下拉，需要额外实现（例如用 Jenkins 未公开的填充接口、或本服务自己调 Git 接口），目前未做。

## 故障排查

### 502 Bad Gateway

出现 `ERR_HTTP_RESPONSE_CODE_FAILURE 502 (Bad Gateway)` 说明请求经过了反向代理（如 nginx、Rancher Ingress），但代理拿不到后端正常响应。按下面顺序排查：

1. **确认本服务是否在运行**
   - 在运行该服务的机器上执行：
     ```bash
     curl http://127.0.0.1:5000/health
     ```
   - 若返回 `{"status":"ok"}` 说明进程正常、端口监听正常；若连不上，说明服务没起来或没监听 5000。

2. **看本服务是否启动失败**
   - 若用 PyCharm/命令行直接跑：看控制台是否有 Python 报错（如缺依赖、`DATABASE_PATH` 目录无权限、导入失败等）。
   - 若用 Docker/Rancher：`kubectl logs <pod>` 或 `docker logs <container>` 看是否有异常退出或反复重启。

3. **确认监听地址**
   - 本应用需监听 `0.0.0.0:5000`（否则代理从别的网卡访问会连不上）。直接运行时已用 `host='0.0.0.0'`；用 Gunicorn 时需 `-b 0.0.0.0:5000`。

4. **检查反向代理配置**
   - **Nginx**：`proxy_pass` 指到实际运行服务的地址和端口（例如 `http://127.0.0.1:5000` 或后端 Pod/Service 的地址），且 upstream 无拼写错误、端口正确。
   - **Rancher/K8s Ingress**：Service 的 port 是否对应容器 5000，Pod 是否 Ready、无 CrashLoopBackOff；可从集群内 `curl http://<service-name>:5000/health` 验证。

5. **网络与防火墙**
   - 代理所在机器能否访问后端地址（如 `172.13.15.237` 的 5000 端口）；防火墙/安全组是否放行 5000。

**建议**：先在同一台机上用浏览器或 `curl http://172.13.15.237:5000/health` 直连 5000 端口，若直连正常而通过代理 502，则问题在代理或网络；若直连就失败，则问题在本服务未启动或监听异常。

---

- **加载任务列表 403 Forbidden**：Jenkins 开启了「防止跨站请求伪造」时，API 需要带 Crumb。本应用已自动请求并携带 Crumb；若仍 403，请检查：① `JENKINS_API_TOKEN` 是否正确；② `JENKINS_USERNAME` 是否填为生成该 Token 的 Jenkins 用户名；③ 该账号是否有「Overall/Read」和「Job/Read」权限。
- **无法获取 Jenkins 任务列表**：检查 `JENKINS_URL` 和 `JENKINS_API_TOKEN` 是否正确，Jenkins 是否可访问
- **触发构建失败**：检查 Jenkins 用户权限，确认 Job 名称和路径正确
- **飞书通知未发送**：检查 `FEISHU_WEBHOOK_URL` 是否正确，飞书机器人是否正常
- **计划未执行**：检查调度器日志，确认计划时间是否为未来时间（东八区）

## 许可证

MIT
