#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy_checkin.py — GitHub Actions 版 WorkBuddy 每日自动签到
================================================================
运行在 GitHub 云端 runner（ubuntu-latest），电脑关机也照跑，实现「关电脑也签」。

token 来源：环境变量 WORKBUDDY（由 GitHub Actions Secret 注入，不在代码里）。
格式（多账号换行隔开）：  ACCESS_TOKEN#UID#备注
示例：
  eyJxxx.aaa.bbb#u_123456#主号
  eyJyyy.ccc.ddd#u_654321#小号A

安全红线：
  - token 只发往官方域名 codebuddy.cn，绝不打印/外传。
  - 脚本本身不含任何 token。

接口（2026 实测）：
  查状态  POST https://www.codebuddy.cn/v2/billing/meter/checkin-activity-status
  领取    POST https://www.codebuddy.cn/v2/billing/meter/daily-checkin
响应以 code 字段为准：0=成功、10001=今日已签（领取接口常走 HTTP 400 包体）。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://www.codebuddy.cn/v2/billing/meter"
STATUS_URL = API_BASE + "/checkin-activity-status"
CHECKIN_URL = API_BASE + "/daily-checkin"
MAX_RETRY = 1


def parse_accounts():
    raw = os.environ.get("WORKBUDDY") or os.environ.get("WB_ACCESS_TOKEN") or ""
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#")
        token = parts[0].strip()
        uid = parts[1].strip() if len(parts) > 1 else ""
        note = parts[2].strip() if len(parts) > 2 else ""
        if token:
            out.append((token, uid, note))
    return out


def parse_code(body):
    try:
        j = json.loads(body)
    except Exception:
        return {"ok": False, "reason": "bad_json", "raw": body[:200]}
    code = j.get("code")
    if code == 0:
        return {"ok": True, "code": 0, "data": j.get("data") or {}}
    if code == 10001:
        return {"ok": True, "already": True, "code": 10001, "msg": j.get("msg") or "今天已签到"}
    return {"ok": False, "code": code, "msg": j.get("msg")}


def _post(token, uid, url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8")


def call(token, uid, url, payload):
    last = None
    for i in range(MAX_RETRY + 1):
        try:
            return _post(token, uid, url, payload)
        except Exception as e:
            last = e
            if i < MAX_RETRY:
                time.sleep(2)
                continue
            break
    return json.dumps({"code": None, "msg": f"net_error:{last}"})


def check_one(token, uid, note):
    print(f"\n=== 账号[{note or uid}] ===")
    st = parse_code(call(token, uid, STATUS_URL, {"uid": uid}))
    if not st.get("ok") or "data" not in st:
        print(f"  状态查询失败：{st.get('msg') or st}")
        return
    d = st["data"]
    if d.get("today_checked_in"):
        print(f"  今日已签（连续 {d.get('streak_days')} 天，累计 {d.get('total_credits')} 分）— 幂等跳过")
        return
    cl = parse_code(call(token, uid, CHECKIN_URL, {"uid": uid}))
    if cl.get("already"):
        print("  今日已签（接口返回 10001）")
        return
    if not cl.get("ok"):
        print(f"  领取失败：{cl.get('msg') or cl}")
        return
    re = parse_code(call(token, uid, STATUS_URL, {"uid": uid}))
    rd = re.get("data") or {}
    if rd.get("today_checked_in"):
        print(f"  签到成功：连续 {rd.get('streak_days')} 天，累计 {rd.get('total_credits')} 分 | 本次 +{rd.get('today_credit')}")
    else:
        print("  领取返回成功但复核未签到，请稍后手动确认")


def main():
    accounts = parse_accounts()
    if not accounts:
        print("未找到 WORKBUDDY / WB_ACCESS_TOKEN 环境变量（格式：ACCESS_TOKEN#UID#备注，多账号换行）")
        sys.exit(1)
    print(f"共 {len(accounts)} 个账号，开始签到")
    for token, uid, note in accounts:
        check_one(token, uid, note)
    print("\n全部账号处理完毕。")


if __name__ == "__main__":
    main()
