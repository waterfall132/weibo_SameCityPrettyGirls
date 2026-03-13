# -*- coding: utf-8 -*-
"""
微博同城抓取脚本（脱敏示例版）

说明：
1. 本文件保留了 Selenium 手动验证思路
2. 上传 GitHub 时建议作为示例参考
3. 实际运行建议使用 pipeline.py + config.json 的统一入口
"""

import os
import time
import json
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

CHROME_USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome_user_data')

headers = {
    'user-agent': '请替换为你的 UA',
    'x-xsrf-token': '请替换为你的 XSRF Token'
}

cookies = {
    '_T_WM': '请替换为你的 _T_WM',
    'SUB': '请替换为你的 SUB',
    'XSRF-TOKEN': '请替换为你的 XSRF-TOKEN'
}


def sync_from_browser(driver):
    global headers, cookies
    try:
        for cookie in driver.get_cookies():
            cookies[cookie['name']] = cookie['value']
        if 'XSRF-TOKEN' in cookies:
            headers['x-xsrf-token'] = cookies['XSRF-TOKEN']
        print('已从浏览器同步 Cookie')
    except Exception as e:
        print(f'同步失败：{e}')


def handle_verification():
    options = Options()
    options.add_argument('--start-maximized')
    options.add_argument(f'--user-data-dir={CHROME_USER_DATA_DIR}')
    options.add_argument('--profile-directory=Default')

    driver = webdriver.Chrome(options=options)
    try:
        driver.get('https://m.weibo.cn')
        time.sleep(2)
        print('请在浏览器中完成微博登录、验证码或滑块验证')
        input('完成后按 Enter 继续...')
        sync_from_browser(driver)
    finally:
        driver.quit()


def get_weibo_data(containerid: str, luicode: str, lfid: str, page: int = 1):
    url = 'https://m.weibo.cn/api/container/getIndex'
    params = {
        'containerid': containerid,
        'luicode': luicode,
        'lfid': lfid,
        'page': page
    }
    return requests.get(url, params=params, headers=headers, cookies=cookies, timeout=10).json()


if __name__ == '__main__':
    print('这是脱敏示例版，请优先使用 pipeline.py')
