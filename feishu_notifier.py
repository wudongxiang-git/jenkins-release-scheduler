"""
飞书通知（文本 + 交互卡片）
"""
import requests
import logging
from config import Config

logger = logging.getLogger(__name__)


def _plan_url(plan_id):
    """发版计划详情/列表页链接（带 plan_id 时前端可据此打开对应详情）"""
    base = (Config.APP_BASE_URL or '').strip()
    if not base:
        return None
    return f"{base.rstrip('/')}/plans#plan-{plan_id}"


def _card_body(header_title, header_color, sections_md, plan_id=None):
    """组装飞书交互卡片 body。sections_md 为多段 markdown 文本列表。"""
    elements = []
    for md in sections_md:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": md}
        })
    if plan_id and _plan_url(plan_id):
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看发版计划"},
                "type": "primary",
                "url": _plan_url(plan_id)
            }]
        })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": header_color
        },
        "elements": elements
    }


class FeishuNotifier:
    """飞书通知器（支持文本与交互卡片）"""

    def __init__(self):
        self.webhook_url = Config.FEISHU_WEBHOOK_URL

    def send(self, message, webhook_url=None):
        """发送飞书文本消息"""
        url = webhook_url or self.webhook_url
        if not url:
            logger.warning("未配置飞书 Webhook URL，跳过通知")
            return
        try:
            payload = {
                "msg_type": "text",
                "content": {"text": message}
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get('code') != 0:
                logger.error("飞书通知失败: %s", result.get('msg'))
            else:
                logger.info("飞书通知发送成功")
        except Exception as e:
            logger.error("发送飞书通知异常: %s", e, exc_info=True)

    def send_card(self, card, webhook_url=None):
        """发送飞书交互卡片。card 为 card 对象（不含 msg_type）。"""
        url = webhook_url or self.webhook_url
        if not url:
            logger.warning("未配置飞书 Webhook URL，跳过卡片通知")
            return
        try:
            payload = {"msg_type": "interactive", "card": card}
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get('code') != 0:
                logger.error("飞书卡片通知失败: %s", result.get('msg'))
            else:
                logger.info("飞书卡片通知发送成功")
        except Exception as e:
            logger.error("发送飞书卡片异常: %s", e, exc_info=True)

    def card_release_start(self, plan_id, scheduled_at_str, task_count):
        """发版开始"""
        card = _card_body(
            "发版开始",
            "blue",
            [
                f"**计划 ID**：#{plan_id}",
                f"**计划时间**：{scheduled_at_str}",
                f"**任务数**：{task_count}",
                "\n正在执行构建，请留意后续完成/失败通知。"
            ],
            plan_id=plan_id
        )
        self.send_card(card)

    def card_release_complete(self, plan_id, scheduled_at_str, success_count, fail_count, total_count, details_lines):
        """发版结束（成功或部分成功）"""
        card = _card_body(
            "发版结束",
            "green",
            [
                f"**计划 ID**：#{plan_id}",
                f"**计划时间**：{scheduled_at_str}",
                f"**结果**：共 {total_count} 个任务，成功 **{success_count}** 个，失败 **{fail_count}** 个。",
                "**详情**：\n" + "\n".join(details_lines) if details_lines else ""
            ],
            plan_id=plan_id
        )
        self.send_card(card)

    def card_release_failed(self, plan_id, scheduled_at_str, total_count, details_lines):
        """发版失败（全部失败）"""
        card = _card_body(
            "发版失败",
            "red",
            [
                f"**计划 ID**：#{plan_id}",
                f"**计划时间**：{scheduled_at_str}",
                f"**结果**：共 {total_count} 个任务，全部失败。",
                "**详情**：\n" + "\n".join(details_lines) if details_lines else ""
            ],
            plan_id=plan_id
        )
        self.send_card(card)

    def card_release_stuck(self, plan_id, scheduled_at_str, running_minutes, task_count):
        """长期执行中且任务未触发，提醒并建议人工处理"""
        card = _card_body(
            "发版异常提醒",
            "orange",
            [
                f"**计划 ID**：#{plan_id}",
                f"**计划时间**：{scheduled_at_str}",
                f"**状态**：已持续执行约 **{running_minutes}** 分钟，但任务列表仍为未触发。",
                f"**任务数**：{task_count}",
                "\n请及时在「发版计划列表」中查看并处理（可终止该计划）。"
            ],
            plan_id=plan_id
        )
        self.send_card(card)
