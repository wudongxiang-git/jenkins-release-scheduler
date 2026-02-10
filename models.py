"""
数据模型
"""
from datetime import datetime
import pytz
from database import get_db

class ReleasePlan:
    """发版计划"""
    def __init__(self, scheduled_at=None, created_at=None, status='pending', 
                 default_branch=None, feishu_webhook=None, id=None):
        self.id = id
        self.scheduled_at = scheduled_at
        self.created_at = created_at
        self.status = status
        self.default_branch = default_branch
        self.feishu_webhook = feishu_webhook
        self.items = []
    
    def save(self, conn):
        """保存到数据库"""
        cursor = conn.cursor()
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        
        if self.id is None:
            # 插入
            cursor.execute('''
                INSERT INTO release_plans (scheduled_at, created_at, status, default_branch, feishu_webhook)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                self.scheduled_at.isoformat() if isinstance(self.scheduled_at, datetime) else self.scheduled_at,
                self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
                self.status,
                self.default_branch or '',
                self.feishu_webhook or ''
            ))
            self.id = cursor.lastrowid
        else:
            # 更新
            cursor.execute('''
                UPDATE release_plans
                SET scheduled_at=?, status=?, default_branch=?, feishu_webhook=?
                WHERE id=?
            ''', (
                self.scheduled_at.isoformat() if isinstance(self.scheduled_at, datetime) else self.scheduled_at,
                self.status,
                self.default_branch or '',
                self.feishu_webhook or '',
                self.id
            ))
    
    @classmethod
    def query_all(cls, conn, filters=None, order_by=None, limit=None):
        """查询所有"""
        cursor = conn.cursor()
        query = 'SELECT * FROM release_plans'
        params = []
        
        if filters:
            conditions = []
            for filter_dict in filters:
                for key, value in filter_dict.items():
                    conditions.append(f'{key}=?')
                    params.append(value)
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
        
        if order_by:
            # 简化处理，假设是 "created_at.desc()" 这样的格式
            if 'desc' in str(order_by).lower():
                query += ' ORDER BY created_at DESC'
            elif 'asc' in str(order_by).lower():
                query += ' ORDER BY created_at ASC'
        
        if limit:
            query += f' LIMIT {limit}'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        results = []
        for row in rows:
            plan = cls(
                id=row['id'],
                scheduled_at=datetime.fromisoformat(row['scheduled_at']),
                created_at=datetime.fromisoformat(row['created_at']),
                status=row['status'],
                default_branch=row['default_branch'] or None,
                feishu_webhook=row['feishu_webhook'] or None
            )
            # 加载关联的 items
            plan.items = ReleasePlanItem.query_by_plan_id(conn, plan.id)
            results.append(plan)
        
        return results

class ReleasePlanItem:
    """计划项"""
    def __init__(self, plan_id=None, jenkins_job_name=None, branch=None, 
                 operation=None, pod_num=None, triggered=False, 
                 build_number=None, success=None, failure_reason=None, id=None):
        self.id = id
        self.plan_id = plan_id
        self.jenkins_job_name = jenkins_job_name
        self.branch = branch
        self.operation = operation
        self.pod_num = pod_num
        self.triggered = bool(triggered)
        self.build_number = build_number
        self.success = success
        self.failure_reason = failure_reason
    
    def save(self, conn):
        """保存到数据库"""
        cursor = conn.cursor()
        
        if self.id is None:
            # 插入
            cursor.execute('''
                INSERT INTO release_plan_items 
                (plan_id, jenkins_job_name, branch, operation, pod_num, triggered, build_number, success, failure_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.plan_id,
                self.jenkins_job_name,
                self.branch or '',
                self.operation or '',
                self.pod_num or '',
                1 if self.triggered else 0,
                self.build_number,
                1 if self.success else (0 if self.success is False else None),
                self.failure_reason or ''
            ))
            self.id = cursor.lastrowid
        else:
            # 更新
            cursor.execute('''
                UPDATE release_plan_items
                SET triggered=?, build_number=?, success=?, failure_reason=?
                WHERE id=?
            ''', (
                1 if self.triggered else 0,
                self.build_number,
                1 if self.success else (0 if self.success is False else None),
                self.failure_reason or '',
                self.id
            ))
    
    @classmethod
    def query_by_plan_id(cls, conn, plan_id):
        """根据 plan_id 查询所有 items"""
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM release_plan_items WHERE plan_id=?', (plan_id,))
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            item = cls(
                id=row['id'],
                plan_id=row['plan_id'],
                jenkins_job_name=row['jenkins_job_name'],
                branch=row['branch'] or None,
                operation=row['operation'] or None,
                pod_num=row['pod_num'] or None,
                triggered=bool(row['triggered']),
                build_number=row['build_number'],
                success=bool(row['success']) if row['success'] is not None else None,
                failure_reason=row['failure_reason'] or None
            )
            results.append(item)
        
        return results
