"""飞书机器人通知服务"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx

from apps.api.app.core.config import get_feishu_webhook_url

log = logging.getLogger("quant.feishu")

# 飞书发送专用线程池：fire-and-forget，避免阻塞 quote_loop
_feishu_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="feishu")


def _do_send(payload: dict, title: str, webhook_url: str) -> bool:
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0 or data.get("StatusCode") == 0:
            log.info("飞书消息发送成功: %s", title)
            return True
        log.warning("飞书消息发送失败: %s", data)
        return False
    except Exception as e:
        log.warning("飞书发送异常: %s", e)
        return False


def send_feishu(title: str, content: str, color: str = "blue") -> bool:
    """
    发送飞书卡片消息（异步 fire-and-forget）。
    返回值仅表示「已提交到发送队列」，实际网络请求在后台线程执行。
    """
    webhook_url = get_feishu_webhook_url()
    if not webhook_url:
        log.debug("飞书 webhook 未配置，跳过发送")
        return False

    color_map = {
        "blue": "blue", "green": "green", "red": "red",
        "orange": "orange", "yellow": "yellow",
    }
    header_color = color_map.get(color, "blue")

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": header_color,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                {
                    "tag": "note",
                    "elements": [{
                        "tag": "plain_text",
                        "content": f"AlphaAgent · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    }],
                },
            ],
        },
    }

    # fire-and-forget 提交到后台线程
    _feishu_pool.submit(_do_send, payload, title, webhook_url)
    return True


def send_buy_alert(symbol: str, name: str, price: float, buy_low: float, buy_high: float,
                   stop_loss: float, take_profit: float, reason: str, confidence: int) -> bool:
    """发送买入提醒"""
    title = f"🟢 买入信号 — {name}（{symbol}）"
    content = (
        f"**当前价格：** ¥{price:.2f}\n"
        f"**建议买入区间：** ¥{buy_low:.2f} ~ ¥{buy_high:.2f}\n"
        f"**止损价：** ¥{stop_loss:.2f}（跌破请卖出）\n"
        f"**止盈价：** ¥{take_profit:.2f}\n"
        f"**置信度：** {confidence}%\n\n"
        f"**分析理由：**\n{reason}"
    )
    return send_feishu(title, content, color="green")


def send_sell_alert(symbol: str, name: str, price: float, avg_cost: float,
                    pnl_pct: float, reason: str) -> bool:
    """发送卖出/止损提醒"""
    emoji = "🔴" if pnl_pct < 0 else "🟡"
    title = f"{emoji} 卖出提醒 — {name}（{symbol}）"
    pnl_str = f"{pnl_pct:+.2f}%"
    content = (
        f"**当前价格：** ¥{price:.2f}\n"
        f"**持仓成本：** ¥{avg_cost:.2f}\n"
        f"**浮动盈亏：** {pnl_str}\n\n"
        f"**提醒原因：**\n{reason}"
    )
    color = "red" if pnl_pct < 0 else "orange"
    return send_feishu(title, content, color=color)


def send_price_alert(symbol: str, name: str, price: float, target: float,
                     alert_type: str) -> bool:
    """发送价格到达提醒"""
    if alert_type == "price_above":
        title = f"📈 价格突破 — {name}（{symbol}）"
        content = f"**当前价格：** ¥{price:.2f}\n**已突破目标价：** ¥{target:.2f}"
        color = "green"
    else:
        title = f"📉 价格跌破 — {name}（{symbol}）"
        content = f"**当前价格：** ¥{price:.2f}\n**已跌破目标价：** ¥{target:.2f}"
        color = "red"
    return send_feishu(title, content, color=color)


def shutdown():
    """优雅关闭飞书发送线程池"""
    log.info("正在关闭飞书消息发送线程池...")
    _feishu_pool.shutdown(wait=True)
