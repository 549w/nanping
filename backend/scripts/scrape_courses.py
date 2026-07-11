"""教务系统课程抓取脚本。

从 ehallapp.nju.edu.cn 抓取指定学年学期的课程信息，含教学班粒度数据。
用法：
    1. 在 backend/.env 中填写 OFFICIAL_COOKIES
    2. 修改本脚本中的 SEMESTER 常量（默认 2026-2027-1 即 2026 秋季）
    3. python backend/scripts/scrape_courses.py
"""

import os
import sys
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

# 加载 backend/.env
load_dotenv(Path(__file__).parent.parent / ".env")

# ---------- 配置 ----------

SEMESTER = "2026-2027-1"          # 2026-2027学年 第1学期（2026秋）
SEMESTER_DISPLAY = "2026-2027学年 第1学期"

API_URL = "https://ehallapp.nju.edu.cn/jwapp/sys/kcbcx/modules/qxkcb/qxfbkccx.do"
PAGE_SIZE = 500          # 每页条数（调大以减少请求次数）
SLEEP_SECONDS = 1.5      # 页间休眠，降低服务器压力
OUTPUT_DIR = f"data/raw_courses_{SEMESTER}-bb"

# 查询参数：限定学年学期（XNXQDM），仅过滤任务状态
QUERY_SETTING = json.dumps([
    {
        "name": "XNXQDM",
        "caption": "学年学期",
        "linkOpt": "AND",
        "builderList": "cbl_m_List",
        "builder": "m_value_equal",
        "value": SEMESTER,
        "value_display": SEMESTER_DISPLAY,
    },
    [
        [{"name": "RWZTDM", "value": "1", "linkOpt": "and", "builder": "equal"},
         {"name": "RWZTDM", "linkOpt": "or", "builder": "isNull"}],
    ],
    {"name": "CXYH", "value": True, "linkOpt": "AND", "builder": "equal"},
    {"name": "*order", "value": "+KKDWDM,+KCH,+KXH", "linkOpt": "AND", "builder": "m_value_equal"},
], ensure_ascii=False)

HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "x-requested-with": "XMLHttpRequest",
    "Referer": "https://ehallapp.nju.edu.cn/jwapp/sys/kcbcx/*default/index.do",
}


def load_cookies() -> str:
    """从 .env 文件读取 cookies。"""
    cookies = os.getenv("OFFICIAL_COOKIES", "")
    if not cookies:
        print("错误：请在 backend/.env 中设置 OFFICIAL_COOKIES")
        print("从浏览器复制完整 cookie 字符串，填入 backend/.env：")
        print("  OFFICIAL_COOKIES=你的cookie字符串")
        sys.exit(1)
    return cookies


def fetch_page(page_number: int, cookies: str) -> dict:
    """请求单页课程数据。

    Args:
        page_number: 页码（从 1 开始）
        cookies: 认证 cookie 字符串

    Returns:
        API 返回的 JSON 数据

    Raises:
        requests.RequestException: 网络请求失败
    """
    body_data = {
        "CXYH": "true",
        "querySetting": QUERY_SETTING,
        "*order": "+KKDWDM,+KCH,+KXH",
        "pageSize": str(PAGE_SIZE),
        "pageNumber": str(page_number),
    }

    response = requests.post(
        API_URL,
        headers={**HEADERS, "cookie": cookies},
        data=urlencode(body_data),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main():
    """主流程：逐页抓取，保存为 JSON。"""
    cookies = load_cookies()
    total: int = 0
    page = 1

    print(f"开始抓取 {SEMESTER}（{SEMESTER_DISPLAY}）课程，每页 {PAGE_SIZE} 条...")

    while True:
        print(f"  第 {page} 页 ...", end=" ", flush=True)

        try:
            data = fetch_page(page, cookies)
        except requests.RequestException as e:
            print(f"\n请求失败：{e}")
            print("可能 cookies 已过期，请重新获取。")
            sys.exit(1)

        rows = data.get("datas", {}).get("qxfbkccx", {}).get("rows", [])
        print(f"{len(rows)} 条")

        if not rows:
            break


        # ---------- 写入文件 ----------
        os.makedirs(os.path.dirname(f'{OUTPUT_DIR}/page_{page:03d}.json'), exist_ok=True)
        with open(f'{OUTPUT_DIR}/page_{page:03d}.json', "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)

        total += len(rows)

        print(f"\n完成！本次抓取 {len(rows)} 条记录，保存至 {f'{OUTPUT_DIR}/page_{page:03d}.json'}，截至目前共抓取 {total} 条教学班记录。")
        
        page += 1

        # 如果返回条数少于 pageSize，说明是最后一页
        if len(rows) < PAGE_SIZE:
            break

        time.sleep(SLEEP_SECONDS)

    print("===END===")

if __name__ == "__main__":
    main()
