# -*- coding: utf-8 -*-
"""
微博同城图片抓取 + 去重 + 人脸筛选 + 大模型细粒度识别

"""

import argparse
import base64
import datetime
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pandas as pd
import requests
import torch
import torch.nn as nn
from dotenv import load_dotenv
from jsonpath import jsonpath
from openai import OpenAI
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from torchvision import models, transforms

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / 'config.json'
ENV_FILE = BASE_DIR / '.env'
SUPPORTED_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp', '.gif')
IMG_SIZE = (224, 224)
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
CHROME_USER_DATA_DIR = BASE_DIR / 'chrome_user_data'

COLS = [
    '微博id', '微博作者', '微博作者uid', '发布时间',
    '微博内容', '图片链接', '转发数', '评论数', '点赞数'
]

LOGGER = logging.getLogger('weibo_pipeline')
PRED_TRANSFORM = transforms.Compose([
    transforms.Resize(IMG_SIZE),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])


def load_env():
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    else:
        load_dotenv()


def resolve_env_placeholders(value):
    if isinstance(value, dict):
        return {k: resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_placeholders(v) for v in value]
    if isinstance(value, str):
        pattern = re.compile(r'\$\{([A-Z0-9_]+)\}')

        def repl(match):
            env_name = match.group(1)
            return os.getenv(env_name, match.group(0))

        return pattern.sub(repl, value)
    return value


def normalize_config_types(config: Dict[str, Any]) -> Dict[str, Any]:
    runtime = config.get('runtime', {})
    llm = config.get('llm_recognition', {})

    if 'pages' in runtime:
        runtime['pages'] = int(runtime['pages'])
    if 'interval' in runtime:
        runtime['interval'] = int(runtime['interval'])
    if 'threshold' in runtime:
        runtime['threshold'] = float(runtime['threshold'])
    if 'sleep_seconds_between_pages' in runtime:
        runtime['sleep_seconds_between_pages'] = float(runtime['sleep_seconds_between_pages'])

    if 'enabled' in llm:
        llm['enabled'] = str(llm['enabled']).lower() in ('1', 'true', 'yes', 'y', 'on')
    if 'batch_size' in llm:
        llm['batch_size'] = int(llm['batch_size'])
    if 'max_tokens' in llm:
        llm['max_tokens'] = int(llm['max_tokens'])

    return config


def load_config() -> Dict[str, Any]:
    load_env()
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f'未找到配置文件：{CONFIG_FILE}。请先将 config.example.json 复制为 config.json。'
        )
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    config = resolve_env_placeholders(config)
    config = normalize_config_types(config)
    return config


def resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def setup_logging(log_file: Path):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)


def ensure_dirs(*paths: Path):
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def trans_time(v_str: str) -> str:
    fmt = '%a %b %d %H:%M:%S +0800 %Y'
    time_array = datetime.datetime.strptime(v_str, fmt)
    return time_array.strftime('%Y-%m-%d %H:%M:%S')


def md5_text(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def md5_file(file_path: Path, chunk_size: int = 8192) -> str:
    digest = hashlib.md5()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f'{stem}_{counter}{suffix}')
        if candidate.exists():
            counter += 1
            continue
        return candidate


def safe_print(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('gbk', errors='replace').decode('gbk'))


def get_long_text(v_id: str, headers: Dict[str, str], cookies: Dict[str, str], proxies: Dict[str, Any]) -> str:
    url = f'https://m.weibo.cn/statuses/extend?id={v_id}'
    r = requests.get(url, headers=headers, cookies=cookies, proxies=proxies, timeout=15)
    r.raise_for_status()
    json_data = r.json()
    long_text = json_data.get('data', {}).get('longTextContent', '')
    dr = re.compile(r'<[^>]+>', re.S)
    return dr.sub('', long_text)


def extract_pic_urls(mblog: dict) -> str:
    pics = mblog.get('pics')
    if not pics:
        return ''

    urls = []
    for pic in pics:
        url = None
        if isinstance(pic, dict):
            large = pic.get('large')
            if isinstance(large, dict):
                url = large.get('url')
            if not url:
                url = pic.get('url')
        elif isinstance(pic, str):
            url = pic

        if isinstance(url, str) and url.strip():
            urls.append(url.strip())

    return ','.join(urls)


def is_blocked(json_resp: dict) -> bool:
    if json_resp is None:
        return True
    if json_resp.get('ok') != 1:
        return True
    msg = str(json_resp.get('msg', '') or json_resp.get('message', ''))
    if any(kw in msg.lower() for kw in ['验证', 'verify', 'captcha', 'block']):
        return True
    return False


def sync_from_browser(driver, headers: Dict[str, str], cookies: Dict[str, str]) -> None:
    try:
        logs = driver.get_log('performance')
        for entry in reversed(logs):
            msg = json.loads(entry['message'])['message']
            if msg.get('method') != 'Network.requestWillBeSent':
                continue
            req = msg.get('params', {}).get('request', {})
            if 'm.weibo.cn' not in req.get('url', ''):
                continue
            real_headers = req.get('headers', {})

            for k, v in real_headers.items():
                kl = k.lower()
                if kl == 'x-xsrf-token':
                    headers['x-xsrf-token'] = v
                elif kl == 'user-agent':
                    headers['user-agent'] = v
                elif kl == 'cookie':
                    for pair in v.split(';'):
                        pair = pair.strip()
                        if '=' in pair:
                            ck, cv = pair.split('=', 1)
                            cookies[ck.strip()] = cv.strip()
            LOGGER.info('已从浏览器同步最新请求头与 Cookie')
            return
    except Exception as e:
        LOGGER.warning(f'性能日志提取失败：{e}')

    try:
        xsrf = driver.execute_script(
            "return document.cookie.split('; ').find(r => r.startsWith('XSRF-TOKEN='))?.split('=')[1];"
        )
        if xsrf:
            headers['x-xsrf-token'] = xsrf
        ua = driver.execute_script('return navigator.userAgent;')
        if ua:
            headers['user-agent'] = ua
    except Exception as e:
        LOGGER.warning(f'JS 提取失败：{e}')

    try:
        for cookie in driver.get_cookies():
            cookies[cookie['name']] = cookie['value']
        if 'XSRF-TOKEN' in cookies:
            headers['x-xsrf-token'] = cookies['XSRF-TOKEN']
    except Exception as e:
        LOGGER.warning(f'get_cookies 同步失败：{e}')


def handle_verification(weibo_cfg: Dict[str, Any]) -> None:
    headers = weibo_cfg['headers']
    cookies = weibo_cfg['cookies']

    LOGGER.warning('检测到微博反爬拦截，正在打开浏览器，请手动完成验证/滑块')

    options = Options()
    options.add_argument('--start-maximized')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument(f'--user-data-dir={CHROME_USER_DATA_DIR}')
    options.add_argument('--profile-directory=Default')
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    driver = webdriver.Chrome(options=options)

    try:
        driver.get('https://m.weibo.cn')
        time.sleep(2)
        safe_print('=' * 55)
        safe_print('请在浏览器中完成微博登录、验证码或滑块验证')
        safe_print('全部完成后，在终端按 Enter 键继续...')
        safe_print('=' * 55)
        input()
        sync_from_browser(driver, headers, cookies)
        LOGGER.info('验证完成，Cookie 与 Header 已同步')
    finally:
        driver.quit()


def get_weibo_data(page: int, weibo_cfg: Dict[str, Any]):
    params = {
        'containerid': weibo_cfg['containerid'],
        'luicode': weibo_cfg['luicode'],
        'lfid': weibo_cfg['lfid'],
        'page': page
    }
    proxies = weibo_cfg.get('proxies', {'http': None, 'https': None})
    try:
        response = requests.get(
            'https://m.weibo.cn/api/container/getIndex',
            params=params,
            headers=weibo_cfg['headers'],
            cookies=weibo_cfg['cookies'],
            proxies=proxies,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        LOGGER.error(f'请求发生错误，第 {page} 页：{e}')
        return None


def parse_cards_to_df(cards: List[Dict[str, Any]], weibo_cfg: Dict[str, Any]) -> pd.DataFrame:
    if not cards:
        return pd.DataFrame(columns=COLS)

    headers = weibo_cfg['headers']
    cookies = weibo_cfg['cookies']
    proxies = weibo_cfg.get('proxies', {'http': None, 'https': None})

    text_list = jsonpath(cards, '$..mblog.text') or []
    time_list = jsonpath(cards, '$..mblog.created_at') or []
    time_list = [trans_time(i) for i in time_list]
    author_list = jsonpath(cards, '$..mblog.user.screen_name') or []
    author_list_uid = jsonpath(cards, '$..mblog.user.id') or []
    id_list = jsonpath(cards, '$..mblog.id') or []
    is_long_text_list = jsonpath(cards, '$..mblog.isLongText') or []
    reposts_count_list = jsonpath(cards, '$..mblog.reposts_count') or []
    comments_count_list = jsonpath(cards, '$..mblog.comments_count') or []
    attitudes_count_list = jsonpath(cards, '$..mblog.attitudes_count') or []

    all_mblogs = jsonpath(cards, '$..mblog') or []
    pic_urls = [extract_pic_urls(m) for m in all_mblogs]

    max_len = len(id_list)
    text_list = text_list[:max_len]
    time_list = time_list[:max_len]
    author_list = author_list[:max_len]
    author_list_uid = author_list_uid[:max_len]
    reposts_count_list = reposts_count_list[:max_len]
    comments_count_list = comments_count_list[:max_len]
    attitudes_count_list = attitudes_count_list[:max_len]
    pic_urls = pic_urls[:max_len]

    dr = re.compile(r'<[^>]+>', re.S)
    text_list = [dr.sub('', text) for text in text_list]

    for idx, is_long in enumerate(is_long_text_list[:max_len]):
        if is_long and idx < len(id_list):
            try:
                long_text = get_long_text(id_list[idx], headers, cookies, proxies)
                if long_text:
                    text_list[idx] = long_text
            except Exception as exc:
                LOGGER.warning(f'获取长微博失败，微博id={id_list[idx]}：{exc}')

    return pd.DataFrame({
        '微博id': id_list,
        '微博作者': author_list,
        '微博作者uid': author_list_uid,
        '发布时间': time_list,
        '微博内容': text_list,
        '图片链接': pic_urls,
        '转发数': reposts_count_list,
        '评论数': comments_count_list,
        '点赞数': attitudes_count_list,
    })


def fetch_pages(total_pages: int, sleep_seconds: float, weibo_cfg: Dict[str, Any]) -> pd.DataFrame:
    all_data = []
    for page in range(1, total_pages + 1):
        LOGGER.info(f'正在爬取第 {page} 页数据...')

        json_resp = None
        for attempt in range(2):
            json_resp = get_weibo_data(page=page, weibo_cfg=weibo_cfg)
            if is_blocked(json_resp):
                if attempt == 0:
                    handle_verification(weibo_cfg)
                    time.sleep(1)
                    continue
                LOGGER.warning(f'第 {page} 页验证后仍失败，跳过')
                json_resp = None
            break

        if not json_resp:
            continue

        cards = json_resp.get('data', {}).get('cards', [])
        page_df = parse_cards_to_df(cards, weibo_cfg)
        if not page_df.empty:
            all_data.append(page_df)
            LOGGER.info(f'第 {page} 页解析完成，共 {len(page_df)} 条')
        else:
            LOGGER.info(f'第 {page} 页没有解析到内容')

        time.sleep(sleep_seconds)

    if not all_data:
        return pd.DataFrame(columns=COLS)

    final_df = pd.concat(all_data, ignore_index=True)
    final_df = final_df.reindex(columns=COLS)
    final_df['微博id'] = final_df['微博id'].astype(str)
    return final_df


def merge_posts_to_csv(new_df: pd.DataFrame, csv_path: Path) -> pd.DataFrame:
    if csv_path.exists():
        old_df = pd.read_csv(csv_path, dtype={'微博id': str})
    else:
        old_df = pd.DataFrame(columns=COLS)

    merged_df = pd.concat([old_df, new_df], ignore_index=True)
    merged_df.drop_duplicates(subset=['微博id'], keep='last', inplace=True)
    merged_df = merged_df.reindex(columns=COLS)
    merged_df.to_csv(csv_path, index=False, encoding='utf_8_sig')
    LOGGER.info(f'微博去重完成，当前总数：{len(merged_df)}')
    return merged_df


def load_download_records(record_file: Path) -> pd.DataFrame:
    if record_file.exists():
        return pd.read_csv(record_file, dtype=str).fillna('')
    return pd.DataFrame(columns=['weibo_id', 'img_url', 'img_url_md5', 'file_md5', 'saved_path'])


def save_download_records(df: pd.DataFrame, record_file: Path):
    df.to_csv(record_file, index=False, encoding='utf_8_sig')


def guess_extension_from_url(url: str) -> str:
    clean_url = url.split('?')[0].lower()
    ext = os.path.splitext(clean_url)[1]
    if ext in SUPPORTED_EXT:
        return ext
    return '.jpg'


def download_new_images(posts_df: pd.DataFrame, output_root: Path, record_file: Path, headers: Dict[str, str], proxies: Dict[str, Any]):
    records_df = load_download_records(record_file)
    known_url_md5: Set[str] = set(records_df['img_url_md5'].tolist()) if not records_df.empty else set()
    known_file_md5: Set[str] = set(records_df['file_md5'].tolist()) if not records_df.empty else set()
    new_records = []
    new_files = []

    for _, row in posts_df.iterrows():
        img_field = row.get('图片链接', '')
        if not isinstance(img_field, str) or not img_field.strip():
            continue

        weibo_id = str(row.get('微博id', 'unknown'))
        urls = [u.strip() for u in img_field.split(',') if u.strip()]

        for idx, url in enumerate(urls, start=1):
            url_md5 = md5_text(url)
            if url_md5 in known_url_md5:
                continue

            ext = guess_extension_from_url(url)
            target_name = f'{weibo_id}_{idx}{ext}' if len(urls) > 1 else f'{weibo_id}{ext}'
            target_path = unique_path(output_root / target_name)
            tmp_path = target_path.with_suffix(target_path.suffix + '.tmp')

            try:
                resp = requests.get(url, headers=headers, proxies=proxies, timeout=20)
                resp.raise_for_status()
                with open(tmp_path, 'wb') as f:
                    f.write(resp.content)

                file_md5 = md5_file(tmp_path)
                if file_md5 in known_file_md5:
                    tmp_path.unlink(missing_ok=True)
                    continue

                tmp_path.replace(target_path)
                new_records.append({
                    'weibo_id': weibo_id,
                    'img_url': url,
                    'img_url_md5': url_md5,
                    'file_md5': file_md5,
                    'saved_path': str(target_path.relative_to(BASE_DIR))
                })
                known_url_md5.add(url_md5)
                known_file_md5.add(file_md5)
                new_files.append(target_path)
                LOGGER.info(f'已下载图片：{target_path.name}')
            except Exception as e:
                tmp_path.unlink(missing_ok=True)
                LOGGER.error(f'下载失败 {url}：{e}')

    if new_records:
        all_records = pd.concat([records_df, pd.DataFrame(new_records)], ignore_index=True)
        save_download_records(all_records, record_file)

    return new_files


def build_prediction_model(model_path: Path):
    model = models.efficientnet_b0(weights=None)
    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.5),
        nn.Linear(in_features, 256),
        nn.BatchNorm1d(256),
        nn.ReLU(),
        nn.Dropout(p=0.3),
        nn.Linear(256, 128),
        nn.ReLU(),
        nn.Linear(128, 1)
    )
    model.load_state_dict(torch.load(model_path, map_location=DEVICE))
    model.to(DEVICE)
    model.eval()
    return model


def predict_is_face(model, image_path: Path, threshold: float = 0.5):
    img = Image.open(image_path).convert('RGB')
    tensor = PRED_TRANSFORM(img).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        prob = torch.sigmoid(model(tensor).squeeze()).item()
    return prob > threshold, prob


def classify_new_images(model, image_paths: List[Path], output_dir: Path, threshold: float = 0.5) -> List[Path]:
    matched_paths = []
    for image_path in image_paths:
        try:
            is_face, prob = predict_is_face(model, image_path, threshold=threshold)
            if is_face:
                dst = unique_path(output_dir / image_path.name)
                shutil.copy2(image_path, dst)
                matched_paths.append(dst)
                LOGGER.info(f'识别为人脸：{image_path.name} | prob={prob:.4f}')
        except Exception as e:
            LOGGER.error(f'分类失败 {image_path}：{e}')
    return matched_paths


def image_to_base64(image_path: str) -> Tuple[str, str]:
    ext = Path(image_path).suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.bmp': 'image/bmp',
        '.webp': 'image/webp', '.gif': 'image/gif', '.tiff': 'image/tiff'
    }
    media_type = mime_map.get(ext, 'image/jpeg')
    with open(image_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    return b64, media_type


def extract_json(text: str) -> str:
    text = re.sub(r'```(?:json)?', '', text).strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        return match.group(0)
    return text


def recognize_batch(file_paths: List[Path], llm_cfg: Dict[str, Any]) -> Dict[str, Tuple[bool, str]]:
    content = []

    for i, path in enumerate(file_paths, start=1):
        file_name = path.name
        b64, media_type = image_to_base64(str(path))
        content.append({'type': 'text', 'text': f'[{i}] {file_name}'})
        content.append({'type': 'image_url', 'image_url': {'url': f'data:{media_type};base64,{b64}'}})

    file_names = [p.name for p in file_paths]
    content.append({
        'type': 'text',
        'text': (
            f'以上共 {len(file_paths)} 张图片。\n'
            '请逐一判断每张图片中是否包含年轻女性（18-35岁左右）。\n'
            '请严格只返回 JSON 数组，格式如下，不要包含任何其他文字：\n'
            '[\n'
            '  {"filename": "文件名", "is_young_female": true, "reason": "说明"},\n'
            '  {"filename": "文件名", "is_young_female": false, "reason": "说明"}\n'
            ']\n'
            f'文件名列表（按顺序）：{json.dumps(file_names, ensure_ascii=False)}'
        )
    })

    client = OpenAI(api_key=llm_cfg['api_key'], base_url=llm_cfg['base_url'])
    try:
        response = client.chat.completions.create(
            model=llm_cfg['model'],
            messages=[{'role': 'user', 'content': content}],
            max_tokens=llm_cfg.get('max_tokens', 1500),
        )
        raw_answer = (response.choices[0].message.content or '').strip()
        json_str = extract_json(raw_answer)
        results_list = json.loads(json_str)

        results = {}
        for item in results_list:
            results[item.get('filename', '')] = (
                item.get('is_young_female', False),
                item.get('reason', '')
            )
        return results
    except Exception as e:
        LOGGER.warning(f'大模型识别失败：{e}')
        return {p.name: (False, '识别失败或返回不可解析') for p in file_paths}


def filter_young_women(face_image_paths: List[Path], output_dir: Path, llm_cfg: Dict[str, Any]):
    if not llm_cfg.get('enabled', False):
        LOGGER.info('大模型细粒度识别未启用，跳过')
        return []
    if not face_image_paths:
        return []

    ensure_dirs(output_dir)
    batch_size = int(llm_cfg.get('batch_size', 10))
    matched_paths = []

    for batch_idx in range(0, len(face_image_paths), batch_size):
        batch_files = face_image_paths[batch_idx: batch_idx + batch_size]
        results = recognize_batch(batch_files, llm_cfg)

        for file_path in batch_files:
            is_match, reason = results.get(file_path.name, (False, '未返回结果'))
            if is_match:
                dst = unique_path(output_dir / file_path.name)
                shutil.copy2(file_path, dst)
                matched_paths.append(dst)
                LOGGER.info(f'年轻女性命中：{file_path.name} | {reason}')
            else:
                LOGGER.info(f'年轻女性未命中：{file_path.name} | {reason}')

    return matched_paths


def run_once(config: Dict[str, Any], pages: int = None, threshold: float = None):
    runtime_cfg = config['runtime']
    paths_cfg = config['paths']
    weibo_cfg = config['weibo']
    llm_cfg = config.get('llm_recognition', {})

    csv_file = resolve_path(paths_cfg['csv_file'])
    output_root = resolve_path(paths_cfg['output_root'])
    face_output_dir = resolve_path(paths_cfg['face_output_dir'])
    young_women_output_dir = resolve_path(paths_cfg['young_women_output_dir'])
    state_dir = resolve_path(paths_cfg['state_dir'])
    record_file = resolve_path(paths_cfg['download_record_file'])
    model_path = resolve_path(paths_cfg['model_path'])

    ensure_dirs(output_root, face_output_dir, young_women_output_dir, state_dir, record_file.parent)

    total_pages = pages if pages is not None else runtime_cfg['pages']
    face_threshold = threshold if threshold is not None else runtime_cfg['threshold']
    sleep_seconds = runtime_cfg.get('sleep_seconds_between_pages', 0.5)

    LOGGER.info('=' * 80)
    LOGGER.info(f'开始执行任务：{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    LOGGER.info('=' * 80)

    posts_df = fetch_pages(total_pages=total_pages, sleep_seconds=sleep_seconds, weibo_cfg=weibo_cfg)
    if posts_df.empty:
        LOGGER.info('本轮未抓取到任何微博')
        return

    merged_df = merge_posts_to_csv(posts_df, csv_file)
    new_files = download_new_images(
        merged_df,
        output_root,
        record_file,
        weibo_cfg['headers'],
        weibo_cfg.get('proxies', {'http': None, 'https': None})
    )

    if not new_files:
        LOGGER.info('本轮没有新增图片')
        return

    if not model_path.exists():
        LOGGER.error(f'未找到模型权重：{model_path}')
        LOGGER.error('请自行准备 classification/face_classifier.pth')
        return

    model = build_prediction_model(model_path)
    face_files = classify_new_images(model, new_files, face_output_dir, threshold=face_threshold)
    filter_young_women(face_files, young_women_output_dir, llm_cfg)
    LOGGER.info('本轮任务结束')


def main():
    config = load_config()
    log_file = resolve_path(config['paths']['log_file'])
    setup_logging(log_file)

    parser = argparse.ArgumentParser(description='微博同城抓取 + 人脸筛选 + 年轻女性识别')
    parser.add_argument('--pages', type=int, default=None, help='覆盖配置中的抓取页数')
    parser.add_argument('--interval', type=int, default=None, help='覆盖配置中的轮询间隔；0 表示只运行一次')
    parser.add_argument('--threshold', type=float, default=None, help='覆盖配置中的人脸阈值')
    args = parser.parse_args()

    interval = args.interval if args.interval is not None else config['runtime']['interval']

    if interval <= 0:
        run_once(config=config, pages=args.pages, threshold=args.threshold)
        return

    LOGGER.info(f'进入常驻模式：每隔 {interval} 秒执行一次')
    while True:
        try:
            run_once(config=config, pages=args.pages, threshold=args.threshold)
            LOGGER.info(f'休眠 {interval} 秒后开始下一轮')
            time.sleep(interval)
        except KeyboardInterrupt:
            LOGGER.info('用户中断，程序退出')
            break
        except Exception as e:
            LOGGER.exception(f'任务异常：{e}')
            LOGGER.info(f'将在 {interval} 秒后重试')
            time.sleep(interval)


if __name__ == '__main__':
    main()
