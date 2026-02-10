"""
GitLab API 客户端
用于获取项目列表、分支列表等（常见 GitLab 集成方式：base_url + private token）
"""
import json
import logging
import requests
from urllib.parse import urljoin, quote

logger = logging.getLogger(__name__)


def _parse_json_response(response, url, log_prefix="GitLab"):
    """安全解析 JSON，若响应为空或非 JSON 则记录并抛出包含响应信息的异常。"""
    text = (response.text or "").strip()
    final_url = getattr(response, "url", url) or url
    if not text:
        logger.warning(f"{log_prefix} 响应为空: status={response.status_code}, url={final_url}")
        raise ValueError("GitLab 返回空响应，请检查地址与 Token 是否正确")
    # 被重定向到登录页说明 Token 未生效或未带对
    if "sign_in" in final_url or "login" in final_url.lower():
        logger.warning(f"{log_prefix} 被重定向到登录页: url={final_url}")
        raise ValueError(
            "GitLab 返回了登录页，说明未识别到有效认证。请检查：① Base URL 为 GitLab 根地址（如 http://192.168.14.14），不要带 /api/v4；② Private Token 正确且具有 api 权限。"
        )
    if text.lower().startswith("<!doctype") or text.strip().lower().startswith("<html"):
        logger.warning(f"{log_prefix} 响应为 HTML 而非 API: url={final_url}")
        raise ValueError(
            "GitLab 返回了 HTML 页面而非 API 数据，请检查 Base URL 与 Private Token 是否正确（Token 需有 api 权限）。"
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        snippet = text[:500] if len(text) > 500 else text
        logger.warning(f"{log_prefix} 响应非 JSON: status={response.status_code}, url={final_url}, body_preview={snippet!r}")
        raise ValueError(
            f"GitLab 返回非 JSON（可能为错误页或地址错误）。HTTP {response.status_code}，响应预览: {snippet[:200]}"
        ) from e


class GitLabClient:
    def __init__(self, base_url, token, ssl_verify=True):
        self.base_url = base_url.rstrip('/')
        if not self.base_url.endswith('/api/v4'):
            self.api_base = self.base_url + '/api/v4'
        else:
            self.api_base = self.base_url
        self.token = token
        self.ssl_verify = bool(ssl_verify)

    def _headers(self):
        return {'PRIVATE-TOKEN': self.token}

    def _request(self, method, path, **kwargs):
        url = urljoin(self.api_base + '/', path.lstrip('/'))
        kwargs.setdefault('headers', {}).update(self._headers())
        kwargs.setdefault('timeout', 15)
        kwargs.setdefault('verify', self.ssl_verify)
        kwargs.setdefault('allow_redirects', False)
        try:
            r = requests.request(method, url, **kwargs)
            if r.is_redirect and ('sign_in' in (r.headers.get('Location') or '') or 'login' in (r.headers.get('Location') or '').lower()):
                logger.warning(f"GitLab 重定向到登录页: {url} -> {r.headers.get('Location')}")
                raise ValueError(
                    "GitLab 要求登录，请检查 Base URL 与 Private Token 是否正确（Token 需有 api 权限）。"
                )
            r.raise_for_status()
            return r
        except ValueError:
            raise
        except requests.RequestException as e:
            logger.error(f"GitLab API 请求失败: {method} {url}: {e}")
            raise

    def get_projects(self, per_page=100, search=None):
        """获取项目列表。返回 [{"id", "name", "path_with_namespace", ...}, ...]"""
        params = {'per_page': per_page}
        if search:
            params['search'] = search
        r = self._request('GET', '/projects', params=params)
        data = _parse_json_response(r, r.url, "GitLab projects")
        if not isinstance(data, list):
            return []
        return data

    def get_branches(self, project_id, per_page=100):
        """获取项目分支列表。project_id 可为数字或 URL 编码的 path。返回 [{"name", ...}, ...]"""
        pid = quote(str(project_id), safe='') if isinstance(project_id, str) and '/' in project_id else project_id
        r = self._request('GET', f'/projects/{pid}/repository/branches', params={'per_page': per_page})
        data = _parse_json_response(r, r.url, "GitLab branches")
        if not isinstance(data, list):
            return []
        return [{'name': b.get('name', '')} for b in data]
