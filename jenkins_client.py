"""
Jenkins 客户端
用于与 Jenkins API 交互
"""
import requests
import logging
import time
from urllib.parse import urljoin, quote
from config import Config

logger = logging.getLogger(__name__)

class JenkinsClient:
    """Jenkins API 客户端"""
    
    def __init__(self):
        self.base_url = Config.JENKINS_URL.rstrip('/')
        self.username = Config.JENKINS_USERNAME
        self.api_token = Config.JENKINS_API_TOKEN
        self._jobs_cache = None
        self._cache_time = None
        self._cache_ttl = 60  # 缓存1分钟
        self._crumb = None  # (crumb_request_field, crumb_value)，用于带认证时的 CSRF
    
    def _get_auth(self):
        """获取认证信息"""
        if self.api_token:
            # Jenkins API Token 认证：用户名用 username 或 token 对应用户名
            user = self.username or 'api'
            return (user, self.api_token)
        return None
    
    def _get_crumb_headers(self):
        """获取 Jenkins Crumb（CSRF），用于开启「防止跨站请求伪造」时的 API 调用"""
        if self._crumb is not None:
            return {self._crumb[0]: self._crumb[1]}
        auth = self._get_auth()
        if not auth:
            return {}
        try:
            url = urljoin(self.base_url, '/crumbIssuer/api/json')
            r = requests.get(url, auth=auth, timeout=10)
            if r.status_code == 200:
                data = r.json()
                self._crumb = (data.get('crumbRequestField', 'Jenkins-Crumb'), data.get('crumb', ''))
                return {self._crumb[0]: self._crumb[1]}
            # 404 说明未开启 Crumb，后续请求不带 crumb
            if r.status_code == 404:
                self._crumb = ()
                return {}
        except Exception as e:
            logger.debug(f"获取 Jenkins Crumb 失败（可能未开启 CSRF）: {e}")
            self._crumb = ()
        return {}
    
    def _request(self, method, endpoint, **kwargs):
        """发送请求（认证 + 可选 Crumb）"""
        url = urljoin(self.base_url, endpoint)
        auth = self._get_auth()
        
        # 带认证时加上 Crumb 头（若 Jenkins 开启了防 CSRF）
        headers = kwargs.pop('headers', None) or {}
        if auth and self._crumb != ():
            crumb_headers = self._get_crumb_headers()
            headers.update(crumb_headers)
        if headers:
            kwargs['headers'] = headers
        
        try:
            response = requests.request(method, url, auth=auth, timeout=30, **kwargs)
            # 若 403 且带了认证，尝试刷新 Crumb 后重试一次
            if response.status_code == 403 and auth and self._crumb is not None:
                self._crumb = None
                crumb_headers = self._get_crumb_headers()
                if crumb_headers:
                    kwargs['headers'] = kwargs.get('headers', {})
                    kwargs['headers'].update(crumb_headers)
                    response = requests.request(method, url, auth=auth, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Jenkins API 请求失败: {method} {url}, 错误: {e}")
            raise
    
    def get_jobs(self, use_cache=True):
        """获取 Jenkins 任务树（支持 folder，树状结构）"""
        # 检查缓存
        if use_cache and self._jobs_cache and self._cache_time:
            if time.time() - self._cache_time < self._cache_ttl:
                return self._jobs_cache
        
        try:
            tree = self._fetch_jobs_tree('')
            # 更新缓存
            self._jobs_cache = tree
            self._cache_time = time.time()
            return tree
        except Exception as e:
            logger.error(f"获取 Jenkins 任务列表失败: {e}", exc_info=True)
            if self._jobs_cache:
                logger.warning("使用缓存的任务列表")
                return self._jobs_cache
            raise
    
    def _fetch_jobs_tree(self, path_prefix):
        """递归获取任务树，返回当前层节点列表；节点为 folder 时含 children，否则为 job 叶子"""
        endpoint = '/api/json?tree=jobs[name,url,_class]'
        if path_prefix:
            endpoint = f'/job/{path_prefix}/api/json?tree=jobs[name,url,_class]'
        
        response = self._request('GET', endpoint)
        data = response.json()
        nodes = []
        
        for job in data.get('jobs', []):
            job_class = job.get('_class', '')
            job_name = job.get('name', '')
            job_url = job.get('url', '')
            
            if path_prefix:
                job_path = f"{path_prefix}/job/{job_name}"
            else:
                job_path = job_name
            
            if 'Folder' in job_class:
                children = self._fetch_jobs_tree(job_path)
                nodes.append({
                    'name': job_name,
                    'path': job_path,
                    'type': 'folder',
                    'children': children
                })
            else:
                nodes.append({
                    'name': job_name,
                    'path': job_path,
                    'url': job_url,
                    'type': 'job'
                })
        
        return nodes
    
    def trigger_build(self, job_path, params=None):
        """触发 Jenkins 构建（buildWithParameters）。params 为 Jenkins 参数名到值的字典，支持 GitLab（BRANCH_TAG）与云效（如 GIT_BRANCH）等不同任务"""
        endpoint = f'/job/{job_path}/buildWithParameters'
        
        build_params = {}
        if params:
            if isinstance(params, dict) and all(isinstance(k, str) for k in params.keys()):
                build_params = {k: str(v) for k, v in params.items() if v is not None and str(v).strip() != ''}
                # 与 Jenkins gitParameter(branchFilter: 'origin.*/.*') 一致：传 origin/ 前缀，避免与手动选择分支时日志/行为不一致
                if 'BRANCH_TAG' in build_params:
                    val = build_params['BRANCH_TAG'].strip()
                    if val and not val.startswith('origin/'):
                        build_params['BRANCH_TAG'] = 'origin/' + val
            else:
                for k in ('branch', 'operation', 'pod_num'):
                    if params.get(k):
                        build_params[{'branch': 'BRANCH_TAG', 'operation': '请选择操作', 'pod_num': 'pod_num'}[k]] = params[k]
        
        try:
            response = self._request('POST', endpoint, params=build_params, allow_redirects=False)
            
            # 从 Location 头获取 queue item URL
            location = response.headers.get('Location', '')
            if location:
                # 从 queue item 获取 build number
                build_number = self._get_build_number_from_queue(location)
                return build_number
            else:
                logger.warning(f"触发构建成功但未返回 Location，job_path={job_path}")
                return None
        except Exception as e:
            logger.error(f"触发构建失败: job_path={job_path}, params={params}, 错误: {e}")
            raise
    
    def _get_build_number_from_queue(self, queue_url):
        """从 queue item 获取 build number"""
        try:
            # queue item API: /queue/item/{id}/api/json
            # 需要等待 build 被分配到 executor
            max_retries = 30
            for i in range(max_retries):
                time.sleep(1)
                try:
                    response = self._request('GET', queue_url.replace(self.base_url, '') + '/api/json')
                    data = response.json()
                    
                    if data.get('executable'):
                        return data['executable']['number']
                    elif data.get('cancelled'):
                        return None
                except:
                    pass
            
            logger.warning(f"无法从 queue 获取 build number，queue_url={queue_url}")
            return None
        except Exception as e:
            logger.error(f"获取 build number 失败: {e}")
            return None
    
    def get_build_status(self, job_path, build_number):
        """获取构建状态"""
        endpoint = f'/job/{job_path}/{build_number}/api/json?tree=building,result'
        
        try:
            response = self._request('GET', endpoint)
            data = response.json()
            
            building = data.get('building', False)
            result = data.get('result')
            
            return {
                'building': building,
                'result': result  # SUCCESS, FAILURE, ABORTED, None(还在构建)
            }
        except Exception as e:
            logger.error(f"获取构建状态失败: job_path={job_path}, build_number={build_number}, 错误: {e}")
            raise
    
    def get_job_parameters_and_status(self, job_path):
        """获取任务参数定义（分支/操作/pod 默认值与选项）及最近构建状态，与「手动构建」一致"""
        # job_path 格式如 "myjob" 或 "folder/job/name"
        endpoint = f'/job/{job_path}/api/json?tree=lastBuild[number,result,building],property[parameterDefinitions[name,defaultParameterValue[value],choices]]'
        try:
            response = self._request('GET', endpoint)
            data = response.json()
        except Exception as e:
            logger.error(f"获取任务参数失败 job_path={job_path}: {e}")
            raise
        
        # 最近构建状态
        last_build = data.get('lastBuild')
        status = {
            'building': False,
            'lastBuild': None
        }
        if last_build:
            status['lastBuild'] = {
                'number': last_build.get('number'),
                'result': last_build.get('result'),  # SUCCESS, FAILURE, ABORTED, None
                'building': last_build.get('building', False)
            }
            status['building'] = status['lastBuild']['building']
        
        # 参数定义：从 property 中找 ParametersDefinitionProperty
        parameters = {}
        for prop in data.get('property', []):
            if 'parameterDefinitions' not in prop:
                continue
            for pd in prop.get('parameterDefinitions', []):
                name = pd.get('name')
                if not name:
                    continue
                default_val = ''
                if pd.get('defaultParameterValue') and isinstance(pd['defaultParameterValue'], dict):
                    default_val = pd['defaultParameterValue'].get('value', '') or ''
                choices = pd.get('choices') or []
                parameters[name] = {'default': default_val, 'choices': choices}
        
        return {'status': status, 'parameters': parameters}
