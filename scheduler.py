"""
定时调度器
每分钟扫描待执行的计划，到点触发并轮询结果
"""
import json
import threading
import time
import logging
from datetime import datetime, timedelta
import pytz
from config import Config
from database import get_db

logger = logging.getLogger(__name__)

class Scheduler:
    """定时调度器"""
    
    def __init__(self, jenkins_client, feishu_notifier):
        self.jenkins_client = jenkins_client
        self.feishu_notifier = feishu_notifier
        self.tz_shanghai = pytz.timezone('Asia/Shanghai')
        self.running = False
        self.thread = None
        self.poll_interval = Config.POLL_INTERVAL
        self.poll_timeout = Config.POLL_TIMEOUT
    
    def start(self):
        """启动调度器"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("调度器已启动")
    
    def stop(self):
        """停止调度器"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("调度器已停止")
    
    def _run(self):
        """调度器主循环"""
        interval = Config.SCHEDULER_INTERVAL
        
        while self.running:
            try:
                self._scan_and_execute()
                self._check_stuck_plans()
            except Exception as e:
                logger.error(f"调度器执行出错: {e}", exc_info=True)
            
            time.sleep(interval)
    
    def _check_stuck_plans(self):
        """检测长期执行中且全部未触发的计划，发送飞书提醒（仅提醒一次）"""
        try:
            now_shanghai = datetime.now(self.tz_shanghai)
            threshold = now_shanghai - timedelta(minutes=Config.STUCK_REMINDER_MINUTES)
            threshold_str = threshold.isoformat()
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, scheduled_at, run_started_at
                    FROM release_plans
                    WHERE status = ? AND run_started_at IS NOT NULL
                      AND (stuck_reminder_sent IS NULL OR stuck_reminder_sent = 0)
                      AND run_started_at < ?
                ''', ('running', threshold_str))
                rows = cursor.fetchall()
            for row in rows:
                plan_id = row['id']
                run_started = datetime.fromisoformat(row['run_started_at'])
                if run_started.tzinfo is None:
                    run_started = self.tz_shanghai.localize(run_started)
                running_minutes = int((now_shanghai - run_started).total_seconds() / 60)
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT id, triggered FROM release_plan_items WHERE plan_id=?', (plan_id,))
                    item_rows = cursor.fetchall()
                if not item_rows:
                    continue
                if all(r['triggered'] == 0 for r in item_rows):
                    scheduled_at = datetime.fromisoformat(row['scheduled_at'])
                    if scheduled_at.tzinfo is None:
                        scheduled_at = self.tz_shanghai.localize(scheduled_at)
                    self.feishu_notifier.card_release_stuck(
                        plan_id,
                        scheduled_at.strftime('%Y-%m-%d %H:%M:%S'),
                        running_minutes,
                        len(item_rows)
                    )
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            'UPDATE release_plans SET stuck_reminder_sent=1 WHERE id=?',
                            (plan_id,)
                        )
                        conn.commit()
                    logger.info(f"计划 #{plan_id} 已发送长期未触发提醒")
        except Exception as e:
            logger.error(f"卡住计划检测失败: {e}", exc_info=True)

    def _scan_and_execute(self):
        """扫描并执行待执行的计划"""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # 查询待执行的计划（东八区时间比较）
            now_shanghai = datetime.now(self.tz_shanghai)
            now_str = now_shanghai.isoformat()
            
            cursor.execute('''
                SELECT * FROM release_plans
                WHERE status = 'pending' AND scheduled_at <= ?
            ''', (now_str,))
            
            rows = cursor.fetchall()
            
            for row in rows:
                plan_id = row['id']
                try:
                    self._execute_plan(plan_id)
                except Exception as e:
                    logger.error(f"执行计划 #{plan_id} 失败: {e}", exc_info=True)
    
    def execute_plan(self, plan_id):
        """供外部调用的立即执行接口（如创建计划后立即发版）。与定时扫描共用同一执行逻辑。"""
        try:
            self._execute_plan(plan_id)
        except Exception as e:
            logger.error(f"立即执行计划 #{plan_id} 失败: {e}", exc_info=True)
            raise
    
    def _execute_plan(self, plan_id):
        """执行一个计划"""
        logger.info(f"开始执行计划 #{plan_id}")
        
        # 加载计划
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM release_plans WHERE id=?', (plan_id,))
            plan_row = cursor.fetchone()
            
            if not plan_row:
                logger.error(f"计划 #{plan_id} 不存在")
                return
            
            plan_row = dict(plan_row)
            
            # 更新状态为 running 并记录开始时间（用于卡住检测与提醒）
            now_str = datetime.now(self.tz_shanghai).isoformat()
            cursor.execute(
                'UPDATE release_plans SET status=?, run_started_at=? WHERE id=?',
                ('running', now_str, plan_id)
            )
            conn.commit()
            
            # 加载计划项
            cursor.execute('SELECT * FROM release_plan_items WHERE plan_id=?', (plan_id,))
            item_rows = cursor.fetchall()
        
        # 发版开始：飞书卡片通知
        try:
            scheduled_at = datetime.fromisoformat(plan_row['scheduled_at'])
            if scheduled_at.tzinfo is None:
                scheduled_at = self.tz_shanghai.localize(scheduled_at)
            self.feishu_notifier.card_release_start(
                plan_id,
                scheduled_at.strftime('%Y-%m-%d %H:%M:%S'),
                len(item_rows)
            )
        except Exception as e:
            logger.warning(f"发版开始通知发送失败: {e}")
        
        # 触发所有任务（优先使用 build_params 以支持 GitLab/云效等不同参数名）
        items = []
        for row in item_rows:
            item_row = dict(row)
            item_id = item_row['id']
            jenkins_job_name = item_row['jenkins_job_name']
            build_params_raw = item_row.get('build_params')
            if build_params_raw:
                try:
                    params = json.loads(build_params_raw)
                except (ValueError, TypeError):
                    params = {}
            else:
                branch = item_row['branch'] or ''
                operation = item_row['operation'] or ''
                pod_num = item_row['pod_num'] or ''
                params = {}
                if branch:
                    params['BRANCH_TAG'] = branch
                elif plan_row.get('default_branch'):
                    params['BRANCH_TAG'] = plan_row['default_branch']
                if operation:
                    params['请选择操作'] = operation
                if pod_num:
                    params['pod_num'] = pod_num
            
            triggered = False
            build_number = None
            failure_reason = None
            
            try:
                # 触发构建
                build_number = self.jenkins_client.trigger_build(jenkins_job_name, params)
                
                if build_number:
                    triggered = True
                    logger.info(f"计划 #{plan_id} - 任务 {jenkins_job_name} 触发成功，构建号: #{build_number}")
                else:
                    triggered = False
                    failure_reason = "触发构建失败：无法获取构建号"
                    logger.error(f"计划 #{plan_id} - 任务 {jenkins_job_name} 触发失败")
            
            except Exception as e:
                triggered = False
                failure_reason = f"触发构建失败：{str(e)}"
                logger.error(f"计划 #{plan_id} - 任务 {jenkins_job_name} 触发异常: {e}", exc_info=True)
            
            # 立即保存触发状态
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE release_plan_items
                    SET triggered=?, build_number=?, failure_reason=?
                    WHERE id=?
                ''', (
                    1 if triggered else 0,
                    build_number,
                    failure_reason or '',
                    item_id
                ))
                conn.commit()
            
            items.append({
                'id': item_id,
                'jenkins_job_name': jenkins_job_name,
                'triggered': triggered,
                'build_number': build_number,
                'success': None,
                'failure_reason': failure_reason
            })
        
        # 轮询所有任务的构建结果
        self._poll_build_results(plan_id, items)
        
        # 所有任务完成后，发送飞书通知
        self._send_notification(plan_id)
    
    def _poll_build_results(self, plan_id, items):
        """轮询所有任务的构建结果"""
        logger.info(f"开始轮询计划 #{plan_id} 的构建结果")
        
        start_time = time.time()
        completed_item_ids = set()
        
        while len(completed_item_ids) < len(items):
            # 检查超时
            if time.time() - start_time > self.poll_timeout:
                logger.warning(f"计划 #{plan_id} 轮询超时")
                break
            
            for item in items:
                item_id = item['id']
                if item_id in completed_item_ids:
                    continue
                
                if not item['triggered'] or not item['build_number']:
                    # 未触发或没有构建号，标记为完成（失败）
                    item['success'] = False
                    completed_item_ids.add(item_id)
                    
                    # 更新数据库
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE release_plan_items
                            SET success=0
                            WHERE id=?
                        ''', (item_id,))
                        conn.commit()
                    continue
                
                try:
                    status = self.jenkins_client.get_build_status(
                        item['jenkins_job_name'],
                        item['build_number']
                    )
                    
                    if not status['building']:
                        # 构建完成
                        item['success'] = (status['result'] == 'SUCCESS')
                        if not item['success']:
                            item['failure_reason'] = f"构建失败：{status['result']}"
                        completed_item_ids.add(item_id)
                        
                        logger.info(
                            f"计划 #{plan_id} - 任务 {item['jenkins_job_name']} #{item['build_number']} "
                            f"构建完成，结果: {'成功' if item['success'] else '失败'}"
                        )
                        
                        # 保存结果
                        with get_db() as conn:
                            cursor = conn.cursor()
                            cursor.execute('''
                                UPDATE release_plan_items
                                SET success=?, failure_reason=?
                                WHERE id=?
                            ''', (
                                1 if item['success'] else 0,
                                item.get('failure_reason', '') or '',
                                item_id
                            ))
                            conn.commit()
                
                except Exception as e:
                    logger.error(
                        f"计划 #{plan_id} - 任务 {item['jenkins_job_name']} #{item['build_number']} "
                        f"轮询状态失败: {e}"
                    )
                    # 继续轮询，不标记为完成
            
            # 如果还有未完成的，等待后继续
            if len(completed_item_ids) < len(items):
                time.sleep(self.poll_interval)
        
        # 更新计划状态
        with get_db() as conn:
            cursor = conn.cursor()
            
            # 统计成功/失败数量
            success_count = sum(1 for item in items if item.get('success') is True)
            fail_count = sum(1 for item in items if item.get('success') is False)
            
            if fail_count == len(items):
                status = 'failed'
            elif success_count == len(items):
                status = 'completed'
            else:
                status = 'completed'  # 部分成功也算 completed
            
            cursor.execute('UPDATE release_plans SET status=? WHERE id=?', (status, plan_id))
            conn.commit()
        
        logger.info(f"计划 #{plan_id} 执行完成，状态: {status}")
    
    def _send_notification(self, plan_id):
        """发送飞书卡片通知（发版结束 / 发版失败）"""
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM release_plans WHERE id=?', (plan_id,))
                plan_row = cursor.fetchone()
                cursor.execute('SELECT * FROM release_plan_items WHERE plan_id=?', (plan_id,))
                item_rows = cursor.fetchall()
            
            scheduled_at = datetime.fromisoformat(plan_row['scheduled_at'])
            if scheduled_at.tzinfo is None:
                scheduled_at = self.tz_shanghai.localize(scheduled_at)
            scheduled_at_str = scheduled_at.strftime('%Y-%m-%d %H:%M:%S')
            
            success_count = sum(1 for r in item_rows if r['success'] == 1)
            fail_count = sum(1 for r in item_rows if r['success'] == 0)
            total_count = len(item_rows)
            
            details = []
            for item_row in item_rows:
                job_name = item_row['jenkins_job_name']
                build_number = item_row['build_number']
                success = item_row['success']
                failure_reason = (item_row['failure_reason'] or '').strip()
                if success == 1:
                    details.append(f"- {job_name} #{build_number} 成功")
                elif success == 0:
                    details.append(f"- {job_name} #{build_number or 'N/A'} 失败：{failure_reason}")
                else:
                    if item_row['triggered']:
                        details.append(f"- {job_name} #{build_number or 'N/A'} 状态未知")
                    else:
                        details.append(f"- {job_name} 触发失败：{failure_reason}")
            
            if fail_count == total_count:
                self.feishu_notifier.card_release_failed(
                    plan_id, scheduled_at_str, total_count, details
                )
            else:
                self.feishu_notifier.card_release_complete(
                    plan_id, scheduled_at_str, success_count, fail_count, total_count, details
                )
            logger.info(f"计划 #{plan_id} 飞书通知已发送")
        except Exception as e:
            logger.error(f"发送飞书通知失败: {e}", exc_info=True)
