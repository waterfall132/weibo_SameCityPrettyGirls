# -*- coding: utf-8 -*-
"""
批量图片识别脚本
真正一次发送多张图片给模型，让模型批量判断

说明：
1. 本文件为示例版，不包含真实 API Key
2. 实际项目推荐使用 pipeline.py 统一执行
3. 使用前请自行填写 INPUT_DIR / OUTPUT_DIR 或改为读取配置
"""

import os
import base64
import shutil
import json
import re
from pathlib import Path
from openai import OpenAI

INPUT_DIR = r'./photos_face'
OUTPUT_DIR = r'./young_women'
BATCH_SIZE = 10
MODEL = 'gemini-2.0-flash'
SUPPORTED_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')

client = OpenAI(
    api_key='请替换为你的 API Key',
    base_url='http://127.0.0.1:2048/v1'
)


def image_to_base64(image_path: str):
    ext = Path(image_path).suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.bmp': 'image/bmp',
        '.webp': 'image/webp',
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


def recognize_batch(file_paths):
    content = []

    for i, path in enumerate(file_paths, start=1):
        file_name = os.path.basename(path)
        b64, media_type = image_to_base64(path)
        content.append({'type': 'text', 'text': f'[{i}] {file_name}'})
        content.append({'type': 'image_url', 'image_url': {'url': f'data:{media_type};base64,{b64}'}})

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{'role': 'user', 'content': content}],
        max_tokens=1500,
    )

    raw_answer = (response.choices[0].message.content or '').strip()
    return json.loads(extract_json(raw_answer))


if __name__ == '__main__':
    print('这是脱敏示例版，请优先使用 pipeline.py')
