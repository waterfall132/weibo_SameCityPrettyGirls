# -*- coding: utf-8 -*-
"""
图片归集脚本
将指定文件夹下所有子文件夹中的图片，全部移动到根文件夹
默认处理当前项目下的 weibo_images
"""

import os
import shutil
from pathlib import Path

from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR / 'weibo_images'
SUPPORTED_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp', '.gif')


def collect_images(root_dir: Path):
    to_move = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        current_dir = Path(dirpath)
        if current_dir == root_dir:
            continue
        for filename in filenames:
            if filename.lower().endswith(SUPPORTED_EXT):
                to_move.append(current_dir / filename)

    if not to_move:
        print('没有需要移动的图片。')
        return

    print(f'共找到 {len(to_move)} 张图片需要移动')

    moved, skipped, conflict = 0, 0, 0

    for src_path in tqdm(to_move, desc='移动进度', ncols=80):
        filename = src_path.name
        dst_path = root_dir / filename

        if dst_path.exists():
            name, ext = os.path.splitext(filename)
            counter = 1
            while dst_path.exists():
                dst_path = root_dir / f'{name}_{counter}{ext}'
                counter += 1
            conflict += 1

        try:
            shutil.move(str(src_path), str(dst_path))
            moved += 1
        except Exception as e:
            print(f'移动失败：{src_path} -> {e}')
            skipped += 1

    removed_dirs = 0
    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=False):
        current_dir = Path(dirpath)
        if current_dir == root_dir:
            continue
        if not os.listdir(current_dir):
            os.rmdir(current_dir)
            removed_dirs += 1

    print('-' * 40)
    print(f'成功移动：{moved} 张')
    if conflict:
        print(f'重命名处理：{conflict} 张（文件名冲突）')
    if skipped:
        print(f'移动失败：{skipped} 张')
    print(f'清理空文件夹：{removed_dirs} 个')
    print(f'完成，所有图片已归集到：{root_dir}')


if __name__ == '__main__':
    print('图片归集工具')
    print(f'根目录：{ROOT_DIR}')
    collect_images(ROOT_DIR)
