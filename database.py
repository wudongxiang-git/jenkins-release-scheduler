"""
数据库初始化
使用 SQLite 存储发版计划
"""
import os
import sqlite3
from contextlib import contextmanager
from config import Config

_db_path = Config.DATABASE_PATH

# 确保数据库目录存在
os.makedirs(os.path.dirname(_db_path) if os.path.dirname(_db_path) else '.', exist_ok=True)

@contextmanager
def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """初始化数据库表"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 创建发版计划表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS release_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scheduled_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                default_branch TEXT,
                feishu_webhook TEXT
            )
        ''')
        
        # 创建计划项表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS release_plan_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                jenkins_job_name TEXT NOT NULL,
                branch TEXT,
                operation TEXT,
                pod_num TEXT,
                build_params TEXT,
                triggered INTEGER DEFAULT 0,
                build_number INTEGER,
                success INTEGER,
                failure_reason TEXT,
                FOREIGN KEY (plan_id) REFERENCES release_plans(id) ON DELETE CASCADE
            )
        ''')
        try:
            cursor.execute('ALTER TABLE release_plan_items ADD COLUMN build_params TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute('ALTER TABLE release_plans ADD COLUMN run_started_at TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute('ALTER TABLE release_plans ADD COLUMN stuck_reminder_sent INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_plan_status ON release_plans(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_plan_scheduled ON release_plans(scheduled_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_item_plan_id ON release_plan_items(plan_id)')

        # 旧表：文件夹代码仓库类型（后续迁移到 folder_configs）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folder_repo_config (
                folder_path TEXT PRIMARY KEY,
                repo_type TEXT NOT NULL
            )
        ''')
        # GitLab 连接配置
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gitlab_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                token TEXT NOT NULL,
                ssl_verify INTEGER DEFAULT 1
            )
        ''')
        # 配置字典（通用下拉数据源）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config_dictionaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                items TEXT NOT NULL
            )
        ''')
        # Jenkins 自定义参数配置（由 GitLab 配置衍生，param_definitions 为 JSON）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jenkins_param_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                gitlab_config_id INTEGER,
                param_definitions TEXT NOT NULL,
                FOREIGN KEY (gitlab_config_id) REFERENCES gitlab_configs(id)
            )
        ''')
        # 文件夹挂载配置（替代 folder_repo_config）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folder_configs (
                folder_path TEXT PRIMARY KEY,
                jenkins_param_config_id INTEGER NOT NULL,
                gitlab_config_id INTEGER,
                gitlab_project_id INTEGER,
                FOREIGN KEY (jenkins_param_config_id) REFERENCES jenkins_param_configs(id),
                FOREIGN KEY (gitlab_config_id) REFERENCES gitlab_configs(id)
            )
        ''')
        # 任务级 GitLab 项目覆盖
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_gitlab_override (
                jenkins_job_path TEXT PRIMARY KEY,
                gitlab_config_id INTEGER NOT NULL,
                gitlab_project_id INTEGER NOT NULL,
                FOREIGN KEY (gitlab_config_id) REFERENCES gitlab_configs(id)
            )
        ''')
        # 迁移：若存在 folder_repo_config 且尚无 folder_configs，则创建默认 Jenkins 参数配置并迁移
        cursor.execute('SELECT COUNT(*) FROM folder_configs')
        if cursor.fetchone()[0] == 0:
            cursor.execute('SELECT COUNT(*) FROM jenkins_param_configs')
            if cursor.fetchone()[0] == 0:
                import json
                default_params = json.dumps([
                    {"param_name": "BRANCH_TAG", "param_type": "dropdown", "source": "gitlab_branches", "allow_empty": False, "label": "分支"},
                    {"param_name": "请选择操作", "param_type": "dropdown", "source": None, "options": ["拉取代码-编译", "拉取代码-编译-单元测试", "重启服务", "停止服务", "扩容服务", "回滚服务"], "allow_empty": False, "label": "操作"},
                    {"param_name": "pod_num", "param_type": "number", "allow_empty": True, "label": "Pod 数量"}
                ])
                cursor.execute('INSERT INTO jenkins_param_configs (id, name, gitlab_config_id, param_definitions) VALUES (1, ?, NULL, ?)', ('GitLab 默认', default_params))
            cursor.execute('SELECT folder_path, repo_type FROM folder_repo_config')
            for row in cursor.fetchall():
                cursor.execute('INSERT OR IGNORE INTO folder_configs (folder_path, jenkins_param_config_id, gitlab_config_id, gitlab_project_id) VALUES (?, 1, NULL, NULL)', (row[0],))

# SQLAlchemy 风格的会话管理（简化版）
class DBSession:
    def __init__(self):
        self.conn = sqlite3.connect(_db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
    
    def query(self, model_class):
        """模拟 SQLAlchemy query"""
        return Query(self.conn, model_class)
    
    def add(self, obj):
        """添加对象到会话"""
        if not hasattr(self, '_pending'):
            self._pending = []
        self._pending.append(obj)
    
    def flush(self):
        """刷新会话"""
        if hasattr(self, '_pending'):
            for obj in self._pending:
                obj.save(self.conn)
            self._pending = []
    
    def commit(self):
        """提交事务"""
        self.flush()
        self.conn.commit()
    
    def rollback(self):
        """回滚事务"""
        if hasattr(self, '_pending'):
            self._pending = []
        self.conn.rollback()
    
    def remove(self):
        """关闭连接"""
        self.conn.close()

class Query:
    def __init__(self, conn, model_class):
        self.conn = conn
        self.model_class = model_class
        self._filters = []
        self._order_by = None
        self._limit = None
    
    def filter_by(self, **kwargs):
        """添加过滤条件"""
        self._filters.append(kwargs)
        return self
    
    def order_by(self, order_expr):
        """排序"""
        self._order_by = order_expr
        return self
    
    def limit(self, n):
        """限制数量"""
        self._limit = n
        return self
    
    def first(self):
        """获取第一条"""
        results = self.all()
        return results[0] if results else None
    
    def all(self):
        """获取所有结果"""
        return self.model_class.query_all(self.conn, self._filters, self._order_by, self._limit)

db_session = DBSession()
