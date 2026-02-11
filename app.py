"""
Jenkins 定时发版 Web 服务
主应用入口
"""
import os
import json
import logging
import threading
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import pytz

from config import Config
from database import init_db, get_db
from jenkins_client import JenkinsClient
from scheduler import Scheduler
from feishu_notifier import FeishuNotifier
from repo_config import REPO_TYPES, get_param_names_for_repo_type
from gitlab_client import GitLabClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# 初始化数据库
init_db()

# 初始化组件
jenkins_client = JenkinsClient()
feishu_notifier = FeishuNotifier()
scheduler = Scheduler(jenkins_client, feishu_notifier)

# 启动后台调度器
scheduler.start()


@app.route('/health')
@app.route('/api/health')
def health():
    """健康检查，供反向代理或负载均衡探测"""
    return jsonify({'status': 'ok'}), 200


@app.route('/')
def index():
    """首页：发版计划创建页面"""
    return render_template('index.html')

@app.route('/plans')
def plans_page():
    """计划列表页面"""
    return render_template('plans.html')


@app.route('/config')
def config_page():
    """系统配置页面：GitLab 连接、配置字典、Jenkins 参数配置"""
    return render_template('config.html')

@app.route('/api/jenkins/jobs', methods=['GET'])
def get_jenkins_jobs():
    """获取 Jenkins 任务列表（树状）"""
    try:
        jobs = jenkins_client.get_jobs()
        return jsonify({'success': True, 'data': jobs})
    except Exception as e:
        logger.error(f"获取 Jenkins 任务列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _job_parent_folder_paths(job_path):
    """Jenkins job path 的父文件夹 path 列表（就近优先）。"""
    parts = job_path.strip().split('/')
    if len(parts) < 2:
        return []
    idx = -2
    out = []
    while -idx <= len(parts):
        parent_path = '/'.join(parts[:idx])
        if parent_path:
            out.append(parent_path)
        idx -= 2
    return out


def _get_folder_param_config_for_job(conn, job_path):
    """按就近原则解析任务使用的 Jenkins 参数配置，返回 (config_id, param_definitions) 或 (None, None)。"""
    cursor = conn.cursor()
    for parent_path in _job_parent_folder_paths(job_path):
        cursor.execute(
            'SELECT j.id, j.param_definitions FROM folder_configs f JOIN jenkins_param_configs j ON f.jenkins_param_config_id=j.id WHERE f.folder_path=?',
            (parent_path,)
        )
        row = cursor.fetchone()
        if row:
            try:
                defs = json.loads(row[1]) if row[1] else []
                return (row[0], defs)
            except (ValueError, TypeError):
                pass
    return (None, None)


def _get_branch_source_for_job(conn, job_path):
    """按就近原则解析分支来源：先任务覆盖，再文件夹。返回 (gitlab_config_id, gitlab_project_id) 或 (None, None)。"""
    cursor = conn.cursor()
    cursor.execute('SELECT gitlab_config_id, gitlab_project_id FROM job_gitlab_override WHERE jenkins_job_path=?', (job_path,))
    row = cursor.fetchone()
    if row and row[0] is not None and row[1] is not None:
        return (row[0], row[1])
    for parent_path in _job_parent_folder_paths(job_path):
        cursor.execute('SELECT gitlab_config_id, gitlab_project_id FROM folder_configs WHERE folder_path=?', (parent_path,))
        row = cursor.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (row[0], row[1])
    return (None, None)


def _get_folder_repo_type_for_job(conn, job_path):
    """兼容旧逻辑：从 folder_repo_config 解析 repo_type。"""
    cursor = conn.cursor()
    for parent_path in _job_parent_folder_paths(job_path):
        cursor.execute('SELECT repo_type FROM folder_repo_config WHERE folder_path=?', (parent_path,))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    return None


# ---------- GitLab 配置 ----------
@app.route('/api/gitlab/configs', methods=['GET'])
def list_gitlab_configs():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, base_url, token, ssl_verify FROM gitlab_configs ORDER BY id')
            rows = cursor.fetchall()
        data = [{'id': r[0], 'name': r[1], 'base_url': r[2], 'token': r[3] or '', 'ssl_verify': bool(r[4])} for r in rows]
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"获取 GitLab 配置列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gitlab/configs', methods=['POST'])
def create_gitlab_config():
    try:
        body = request.get_json() or {}
        name = (body.get('name') or '').strip()
        base_url = (body.get('base_url') or '').strip()
        token = (body.get('token') or '').strip()
        ssl_verify = body.get('ssl_verify', True)
        if not name or not base_url or not token:
            return jsonify({'success': False, 'error': '缺少 name / base_url / token'}), 400
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO gitlab_configs (name, base_url, token, ssl_verify) VALUES (?, ?, ?, ?)',
                (name, base_url, token, 1 if ssl_verify else 0)
            )
            conn.commit()
            uid = cursor.lastrowid
        return jsonify({'success': True, 'data': {'id': uid}})
    except Exception as e:
        logger.error(f"创建 GitLab 配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gitlab/configs/<int:config_id>', methods=['GET'])
def get_gitlab_config(config_id):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, base_url, token, ssl_verify FROM gitlab_configs WHERE id=?', (config_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': '配置不存在'}), 404
        return jsonify({'success': True, 'data': {'id': row[0], 'name': row[1], 'base_url': row[2], 'token': row[3] or '', 'ssl_verify': bool(row[4])}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gitlab/configs/<int:config_id>', methods=['PUT'])
def update_gitlab_config(config_id):
    try:
        body = request.get_json() or {}
        name = (body.get('name') or '').strip()
        base_url = (body.get('base_url') or '').strip()
        token = (body.get('token') or '').strip()
        ssl_verify = body.get('ssl_verify', True)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE gitlab_configs SET name=?, base_url=?, token=?, ssl_verify=? WHERE id=?',
                (name, base_url, token, 1 if ssl_verify else 0, config_id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': '配置不存在'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gitlab/configs/<int:config_id>', methods=['DELETE'])
def delete_gitlab_config(config_id):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM gitlab_configs WHERE id=?', (config_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': '配置不存在'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gitlab/projects', methods=['GET'])
def gitlab_projects():
    config_id = request.args.get('config_id', type=int)
    if not config_id:
        return jsonify({'success': False, 'error': '缺少 config_id'}), 400
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT base_url, token, ssl_verify FROM gitlab_configs WHERE id=?', (config_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'GitLab 配置不存在'}), 404
        client = GitLabClient(row[0], row[1] or '', bool(row[2]))
        projects = client.get_projects(search=request.args.get('search'))
        out = [{'id': p.get('id'), 'name': p.get('name'), 'path_with_namespace': p.get('path_with_namespace')} for p in projects]
        return jsonify({'success': True, 'data': out})
    except Exception as e:
        logger.error(f"获取 GitLab 项目列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gitlab/branches', methods=['GET'])
def gitlab_branches():
    job_path = request.args.get('job_path')
    config_id = request.args.get('config_id', type=int)
    project_id = request.args.get('project_id')
    if job_path:
        try:
            with get_db() as conn:
                gitlab_config_id, gitlab_project_id = _get_branch_source_for_job(conn, job_path)
            if not gitlab_config_id or gitlab_project_id is None:
                return jsonify({'success': False, 'error': '未配置分支来源', 'data': []}), 200
            config_id, project_id = gitlab_config_id, gitlab_project_id
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    if not config_id or project_id is None:
        return jsonify({'success': False, 'error': '缺少 config_id 或 project_id（或通过 job_path 解析）'}), 400
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT base_url, token, ssl_verify FROM gitlab_configs WHERE id=?', (config_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'GitLab 配置不存在'}), 404
        client = GitLabClient(row[0], row[1] or '', bool(row[2]))
        branches = client.get_branches(project_id)
        out = [b.get('name', '') for b in branches]
        return jsonify({'success': True, 'data': out})
    except Exception as e:
        logger.error(f"获取 GitLab 分支失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- 配置字典 ----------
@app.route('/api/dictionaries', methods=['GET'])
def list_dictionaries():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, description, items FROM config_dictionaries ORDER BY id')
            rows = cursor.fetchall()
        data = [{'id': r[0], 'name': r[1], 'description': r[2] or '', 'items': r[3]} for r in rows]
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/dictionaries', methods=['POST'])
def create_dictionary():
    try:
        body = request.get_json() or {}
        name = (body.get('name') or '').strip()
        description = (body.get('description') or '').strip()
        items = body.get('items')
        if not name:
            return jsonify({'success': False, 'error': '缺少 name'}), 400
        if items is None:
            items = []
        items_json = json.dumps(items) if isinstance(items, (list, dict)) else '[]'
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO config_dictionaries (name, description, items) VALUES (?, ?, ?)', (name, description, items_json))
            conn.commit()
            uid = cursor.lastrowid
        return jsonify({'success': True, 'data': {'id': uid}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/dictionaries/<int:dict_id>', methods=['GET'])
def get_dictionary(dict_id):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, description, items FROM config_dictionaries WHERE id=?', (dict_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': '字典不存在'}), 404
        return jsonify({'success': True, 'data': {'id': row[0], 'name': row[1], 'description': row[2] or '', 'items': row[3]}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/dictionaries/<int:dict_id>/options', methods=['GET'])
def get_dictionary_options(dict_id):
    """仅返回选项列表，供下拉数据源使用。items 为 JSON 数组，元素可为字符串或 {value, label}。"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT items FROM config_dictionaries WHERE id=?', (dict_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': '字典不存在'}), 404
        try:
            raw = json.loads(row[0])
        except (ValueError, TypeError):
            raw = []
        if not isinstance(raw, list):
            raw = []
        options = []
        for x in raw:
            if isinstance(x, dict) and 'value' in x:
                options.append(x.get('value'))
            elif isinstance(x, str):
                options.append(x)
            else:
                options.append(str(x))
        return jsonify({'success': True, 'data': options})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/dictionaries/<int:dict_id>', methods=['PUT'])
def update_dictionary(dict_id):
    try:
        body = request.get_json() or {}
        name = (body.get('name') or '').strip()
        description = (body.get('description') or '').strip()
        items = body.get('items')
        items_json = json.dumps(items) if items is not None and isinstance(items, (list, dict)) else None
        with get_db() as conn:
            cursor = conn.cursor()
            if items_json is not None:
                cursor.execute('UPDATE config_dictionaries SET name=?, description=?, items=? WHERE id=?', (name or None, description or None, items_json, dict_id))
            else:
                cursor.execute('UPDATE config_dictionaries SET name=?, description=? WHERE id=?', (name or None, description or None, dict_id))
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': '字典不存在'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/dictionaries/<int:dict_id>', methods=['DELETE'])
def delete_dictionary(dict_id):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM config_dictionaries WHERE id=?', (dict_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': '字典不存在'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Jenkins 自定义参数配置 ----------
@app.route('/api/jenkins-param-configs', methods=['GET'])
def list_jenkins_param_configs():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, gitlab_config_id, param_definitions FROM jenkins_param_configs ORDER BY id')
            rows = cursor.fetchall()
        data = []
        for r in rows:
            try:
                defs = json.loads(r[3]) if r[3] else []
            except (ValueError, TypeError):
                defs = []
            data.append({'id': r[0], 'name': r[1], 'gitlab_config_id': r[2], 'param_definitions': defs})
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/jenkins-param-configs', methods=['POST'])
def create_jenkins_param_config():
    try:
        body = request.get_json() or {}
        name = (body.get('name') or '').strip()
        gitlab_config_id = body.get('gitlab_config_id')
        param_definitions = body.get('param_definitions')
        if not name:
            return jsonify({'success': False, 'error': '缺少 name'}), 400
        defs_json = json.dumps(param_definitions if isinstance(param_definitions, list) else [])
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO jenkins_param_configs (name, gitlab_config_id, param_definitions) VALUES (?, ?, ?)',
                (name, gitlab_config_id, defs_json)
            )
            conn.commit()
            uid = cursor.lastrowid
        return jsonify({'success': True, 'data': {'id': uid}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/jenkins-param-configs/<int:config_id>', methods=['GET'])
def get_jenkins_param_config(config_id):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, gitlab_config_id, param_definitions FROM jenkins_param_configs WHERE id=?', (config_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': '配置不存在'}), 404
        try:
            defs = json.loads(row[3]) if row[3] else []
        except (ValueError, TypeError):
            defs = []
        return jsonify({'success': True, 'data': {'id': row[0], 'name': row[1], 'gitlab_config_id': row[2], 'param_definitions': defs}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/jenkins-param-configs/<int:config_id>', methods=['PUT'])
def update_jenkins_param_config(config_id):
    try:
        body = request.get_json() or {}
        name = (body.get('name') or '').strip()
        gitlab_config_id = body.get('gitlab_config_id')
        param_definitions = body.get('param_definitions')
        with get_db() as conn:
            cursor = conn.cursor()
            if param_definitions is not None:
                defs_json = json.dumps(param_definitions if isinstance(param_definitions, list) else [])
                cursor.execute('UPDATE jenkins_param_configs SET name=?, gitlab_config_id=?, param_definitions=? WHERE id=?', (name or None, gitlab_config_id, defs_json, config_id))
            else:
                cursor.execute('UPDATE jenkins_param_configs SET name=?, gitlab_config_id=? WHERE id=?', (name or None, gitlab_config_id, config_id))
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': '配置不存在'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/jenkins-param-configs/<int:config_id>', methods=['DELETE'])
def delete_jenkins_param_config(config_id):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM jenkins_param_configs WHERE id=?', (config_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': '配置不存在'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- 文件夹配置（新：folder_configs）----------
@app.route('/api/folders/config', methods=['GET'])
def get_folders_config():
    """返回 folder_configs；兼容返回 folder_repo_config 供旧前端"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT folder_path, jenkins_param_config_id, gitlab_config_id, gitlab_project_id
                FROM folder_configs ORDER BY folder_path
            ''')
            rows = cursor.fetchall()
        data = [{'folder_path': r[0], 'jenkins_param_config_id': r[1], 'gitlab_config_id': r[2], 'gitlab_project_id': r[3]} for r in rows]
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"获取文件夹配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/folders/config', methods=['POST'])
def set_folder_config():
    """body: folder_path, jenkins_param_config_id, gitlab_config_id?, gitlab_project_id?。若只传 folder_path+repo_type 则写回 folder_repo_config 兼容旧前端"""
    try:
        body = request.get_json() or {}
        folder_path = (body.get('folder_path') or '').strip()
        if not folder_path:
            return jsonify({'success': False, 'error': '缺少 folder_path'}), 400
        jenkins_param_config_id = body.get('jenkins_param_config_id')
        gitlab_config_id = body.get('gitlab_config_id')
        gitlab_project_id = body.get('gitlab_project_id')
        repo_type = (body.get('repo_type') or '').strip()
        with get_db() as conn:
            cursor = conn.cursor()
            if jenkins_param_config_id is not None:
                cursor.execute('''
                    INSERT OR REPLACE INTO folder_configs (folder_path, jenkins_param_config_id, gitlab_config_id, gitlab_project_id)
                    VALUES (?, ?, ?, ?)
                ''', (folder_path, jenkins_param_config_id, gitlab_config_id, gitlab_project_id))
            elif repo_type:
                cursor.execute('INSERT OR REPLACE INTO folder_repo_config (folder_path, repo_type) VALUES (?, ?)', (folder_path, repo_type))
                cursor.execute('SELECT id FROM jenkins_param_configs LIMIT 1')
                default_id = cursor.fetchone()
                if default_id:
                    cursor.execute('''
                        INSERT OR REPLACE INTO folder_configs (folder_path, jenkins_param_config_id, gitlab_config_id, gitlab_project_id)
                        VALUES (?, ?, NULL, NULL)
                    ''', (folder_path, default_id[0]))
            else:
                cursor.execute('DELETE FROM folder_configs WHERE folder_path=?', (folder_path,))
                cursor.execute('DELETE FROM folder_repo_config WHERE folder_path=?', (folder_path,))
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"设置文件夹配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- 任务级 GitLab 覆盖 ----------
@app.route('/api/job-gitlab-override', methods=['GET'])
def list_job_gitlab_override():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT jenkins_job_path, gitlab_config_id, gitlab_project_id FROM job_gitlab_override')
            rows = cursor.fetchall()
        data = [{'jenkins_job_path': r[0], 'gitlab_config_id': r[1], 'gitlab_project_id': r[2]} for r in rows]
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/job-gitlab-override', methods=['POST'])
def set_job_gitlab_override():
    """body: jenkins_job_path, gitlab_config_id, gitlab_project_id。若 gitlab_config_id/gitlab_project_id 为空则删除覆盖"""
    try:
        body = request.get_json() or {}
        job_path = (body.get('jenkins_job_path') or '').strip()
        if not job_path:
            return jsonify({'success': False, 'error': '缺少 jenkins_job_path'}), 400
        gitlab_config_id = body.get('gitlab_config_id')
        gitlab_project_id = body.get('gitlab_project_id')
        with get_db() as conn:
            cursor = conn.cursor()
            if gitlab_config_id is not None and gitlab_project_id is not None:
                cursor.execute('''
                    INSERT OR REPLACE INTO job_gitlab_override (jenkins_job_path, gitlab_config_id, gitlab_project_id) VALUES (?, ?, ?)
                ''', (job_path, gitlab_config_id, gitlab_project_id))
            else:
                cursor.execute('DELETE FROM job_gitlab_override WHERE jenkins_job_path=?', (job_path,))
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/job-gitlab-override/batch', methods=['POST'])
def set_job_gitlab_override_batch():
    """body: job_paths: string[], gitlab_config_id?: number, gitlab_project_id?。同一 config+project 应用到多个任务；若 config/project 为空则删除这些任务的覆盖"""
    try:
        body = request.get_json() or {}
        job_paths = body.get('job_paths')
        if not isinstance(job_paths, list):
            return jsonify({'success': False, 'error': '缺少或无效的 job_paths'}), 400
        job_paths = [str(p).strip() for p in job_paths if (p or '').strip()]
        gitlab_config_id = body.get('gitlab_config_id')
        gitlab_project_id = body.get('gitlab_project_id')
        with get_db() as conn:
            cursor = conn.cursor()
            for job_path in job_paths:
                if not job_path:
                    continue
                if gitlab_config_id is not None and gitlab_project_id is not None:
                    cursor.execute('''
                        INSERT OR REPLACE INTO job_gitlab_override (jenkins_job_path, gitlab_config_id, gitlab_project_id) VALUES (?, ?, ?)
                    ''', (job_path, gitlab_config_id, gitlab_project_id))
                else:
                    cursor.execute('DELETE FROM job_gitlab_override WHERE jenkins_job_path=?', (job_path,))
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/repo-types', methods=['GET'])
def get_repo_types():
    """获取支持的代码仓库类型列表（供前端下拉，兼容旧 UI）"""
    return jsonify({'success': True, 'data': REPO_TYPES})


@app.route('/api/jenkins/job/parameters', methods=['GET'])
def get_jenkins_job_parameters():
    """返回 Jenkins 原始 parameters + 就近的 param_definitions + branch_source 是否已配置"""
    path = request.args.get('path')
    if not path:
        return jsonify({'success': False, 'error': '缺少 path 参数'}), 400
    try:
        data = jenkins_client.get_job_parameters_and_status(path)
        with get_db() as conn:
            param_config_id, param_definitions = _get_folder_param_config_for_job(conn, path)
            gitlab_config_id, gitlab_project_id = _get_branch_source_for_job(conn, path)
        if param_config_id is not None and param_definitions:
            data['param_definitions'] = param_definitions
        else:
            with get_db() as conn2:
                repo_type = _get_folder_repo_type_for_job(conn2, path)
            if repo_type:
                data['repo_type'] = repo_type
                param_names = get_param_names_for_repo_type(repo_type)
                if param_names:
                    data['param_names'] = param_names
        data['branch_source_configured'] = gitlab_config_id is not None and gitlab_project_id is not None
        if data['branch_source_configured']:
            data['gitlab_config_id'] = gitlab_config_id
            data['gitlab_project_id'] = gitlab_project_id
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"获取任务参数失败 path={path}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/plans', methods=['GET'])
def list_plans():
    """获取发版计划列表"""
    try:
        import pytz
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.*, COUNT(i.id) as item_count
                FROM release_plans p
                LEFT JOIN release_plan_items i ON p.id = i.plan_id
                GROUP BY p.id
                ORDER BY p.created_at DESC
                LIMIT 100
            ''')
            rows = cursor.fetchall()
        
        result = []
        for row in rows:
            plan_dict = {
                'id': row['id'],
                'scheduled_at': row['scheduled_at'],
                'created_at': row['created_at'],
                'status': row['status'],
                'default_branch': row['default_branch'],
                'item_count': row['item_count'],
                'execution_mode': row['execution_mode'] if 'execution_mode' in row.keys() and row['execution_mode'] else 'serial'
            }
            result.append(plan_dict)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        logger.error(f"获取计划列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/plans/<int:plan_id>', methods=['GET'])
def get_plan(plan_id):
    """获取计划详情"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM release_plans WHERE id=?', (plan_id,))
            plan_row = cursor.fetchone()
            
            if not plan_row:
                return jsonify({'success': False, 'error': '计划不存在'}), 404
            
            cursor.execute('SELECT * FROM release_plan_items WHERE plan_id=?', (plan_id,))
            item_rows = cursor.fetchall()
        
        items = []
        for item_row in item_rows:
            build_params = None
            raw = item_row['build_params'] if 'build_params' in item_row.keys() else None
            if raw:
                try:
                    build_params = json.loads(raw)
                except (ValueError, TypeError):
                    pass
            item_dict = {
                'id': item_row['id'],
                'jenkins_job_name': item_row['jenkins_job_name'],
                'branch': item_row['branch'],
                'operation': item_row['operation'],
                'pod_num': item_row['pod_num'],
                'params': build_params,
                'triggered': bool(item_row['triggered']),
                'build_number': item_row['build_number'],
                'success': bool(item_row['success']) if item_row['success'] is not None else None,
                'failure_reason': item_row['failure_reason']
            }
            items.append(item_dict)
        
        plan_dict = {
            'id': plan_row['id'],
            'scheduled_at': plan_row['scheduled_at'],
            'created_at': plan_row['created_at'],
            'status': plan_row['status'],
            'default_branch': plan_row['default_branch'],
            'execution_mode': plan_row['execution_mode'] if 'execution_mode' in plan_row.keys() and plan_row['execution_mode'] else 'serial',
            'items': items
        }
        return jsonify({'success': True, 'data': plan_dict})
    except Exception as e:
        logger.error(f"获取计划详情失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/plans/<int:plan_id>/cancel', methods=['POST', 'PATCH'])
def cancel_plan(plan_id):
    """取消待执行的计划（仅 pending 可取消）"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, status FROM release_plans WHERE id=?', (plan_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': '计划不存在'}), 404
            if row['status'] != 'pending':
                return jsonify({'success': False, 'error': '仅待执行状态可取消'}), 400
            cursor.execute('UPDATE release_plans SET status=? WHERE id=?', ('cancelled', plan_id))
            conn.commit()
        logger.info(f"计划 #{plan_id} 已取消")
        return jsonify({'success': True, 'data': {'plan_id': plan_id, 'status': 'cancelled'}})
    except Exception as e:
        logger.error(f"取消计划失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/plans/<int:plan_id>/terminate', methods=['POST', 'PATCH'])
def terminate_plan(plan_id):
    """人为终止执行中的计划（仅 running 可终止）"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, status FROM release_plans WHERE id=?', (plan_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': '计划不存在'}), 404
            if row['status'] != 'running':
                return jsonify({'success': False, 'error': '仅执行中状态可终止'}), 400
            cursor.execute('UPDATE release_plans SET status=? WHERE id=?', ('failed', plan_id))
            conn.commit()
        logger.info(f"计划 #{plan_id} 已人为终止")
        return jsonify({'success': True, 'data': {'plan_id': plan_id, 'status': 'failed'}})
    except Exception as e:
        logger.error(f"终止计划失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/plans', methods=['POST'])
def create_plan():
    """创建发版计划"""
    try:
        data = request.get_json()
        scheduled_at_str = data.get('scheduled_at')
        default_branch = data.get('default_branch', '')
        items_data = data.get('items', [])
        execution_mode = (data.get('execution_mode') or 'serial').strip().lower()
        if execution_mode not in ('serial', 'parallel'):
            execution_mode = 'serial'
        
        if not scheduled_at_str:
            return jsonify({'success': False, 'error': '缺少 scheduled_at'}), 400
        
        if not items_data:
            return jsonify({'success': False, 'error': '至少选择一个任务'}), 400
        # 仅选择参数配置即可发版；未配置 GitLab 项目时分支由用户手动填写，不再拦截

        # 解析时间（东八区）
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        scheduled_at = datetime.fromisoformat(scheduled_at_str.replace('Z', '+00:00'))
        if scheduled_at.tzinfo is None:
            # 如果没有时区信息，假设是东八区时间
            scheduled_at = tz_shanghai.localize(scheduled_at)
        else:
            scheduled_at = scheduled_at.astimezone(tz_shanghai)
        
        execute_immediately = data.get('execute_immediately') is True
        now_shanghai = datetime.now(tz_shanghai)
        # 立即发版时不校验未来时间；预约发版时校验必须为未来（允许 2 分钟容错）
        if not execute_immediately and scheduled_at < now_shanghai - timedelta(minutes=2):
            return jsonify({'success': False, 'error': '计划时间必须是未来时间'}), 400
        
        # 校验任务 path 是否在树中存在（树状接口返回 folder/job 结构）
        def _job_paths_from_tree(nodes):
            paths = set()
            for n in nodes:
                if n.get('type') == 'job':
                    paths.add(n.get('path', ''))
                elif n.get('children'):
                    paths |= _job_paths_from_tree(n['children'])
            return paths
        try:
            tree = jenkins_client.get_jobs()
            valid_paths = _job_paths_from_tree(tree) if isinstance(tree, list) else set()
            for item_data in items_data:
                path = item_data.get('jenkins_job_name')
                if valid_paths and path not in valid_paths:
                    logger.warning(f"任务 {path} 不在可用列表中，但继续创建计划")
        except Exception as e:
            logger.warning(f"无法校验任务列表: {e}，继续创建计划")
        
        # 创建计划
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO release_plans (scheduled_at, created_at, status, default_branch, execution_mode)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                scheduled_at.isoformat(),
                now_shanghai.isoformat(),
                'pending',
                default_branch or '',
                execution_mode
            ))
            plan_id = cursor.lastrowid
            
            # 创建计划项（支持按任务真实参数名传参，兼容 GitLab/云效等不同任务）
            for item_data in items_data:
                job_path = item_data.get('jenkins_job_name')
                item_params = item_data.get('params')
                if isinstance(item_params, dict) and item_params:
                    build_params_json = json.dumps(item_params)
                    branch = (item_params.get('BRANCH_TAG') or item_params.get('GIT_BRANCH') or item_params.get('REPO_BRANCH') or item_params.get('branch') or '')
                    operation = (item_params.get('请选择操作') or item_params.get('操作') or item_params.get('operation') or '')
                    pod_num = (item_params.get('pod_num') or item_params.get('POD_NUM') or '')
                else:
                    build_params_json = None
                    branch = item_data.get('branch', '') or ''
                    operation = item_data.get('operation', '') or ''
                    pod_num = item_data.get('pod_num', '') or ''
                cursor.execute('''
                    INSERT INTO release_plan_items 
                    (plan_id, jenkins_job_name, branch, operation, pod_num, build_params, triggered)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                ''', (plan_id, job_path, branch, operation, pod_num, build_params_json))
            
            conn.commit()
        
        logger.info(f"创建发版计划 #{plan_id}，计划时间: {scheduled_at}" + ("，立即执行" if execute_immediately else ""))
        if execute_immediately:
            def run_in_background():
                try:
                    scheduler.execute_plan(plan_id)
                except Exception as ex:
                    logger.error(f"创建后立即执行计划 #{plan_id} 失败: {ex}", exc_info=True)
            t = threading.Thread(target=run_in_background, daemon=True)
            t.start()
        return jsonify({'success': True, 'data': {'plan_id': plan_id}})
        
    except Exception as e:
        logger.error(f"创建计划失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
