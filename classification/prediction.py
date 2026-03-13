# -*- coding: utf-8 -*-
"""
人脸图片筛选脚本（脱敏发布版）
使用训练好的 face_classifier.pth 对指定文件夹中所有图片进行分类
将识别为人脸的图片复制到输出文件夹

说明：
1. 本文件公开推理流程代码
2. 默认不附带权重文件 face_classifier.pth
3. 若要运行，请自行准备训练好的权重并放到 classification/ 目录下
"""

import shutil
from pathlib import Path

import torch
import torch.nn as nn
from PIL import Image
from torchvision import transforms, models
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = BASE_DIR / 'classification' / 'face_classifier.pth'
INPUT_DIR = BASE_DIR / 'weibo_images'
OUTPUT_DIR = BASE_DIR / 'photos_face'
THRESHOLD = 0.5
IMG_SIZE = (224, 224)

SUPPORTED_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f'{stem}_{counter}{suffix}')
        if not candidate.exists():
            return candidate
        counter += 1


def load_model(model_path: Path):
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
    print(f'模型加载成功：{model_path}')
    print(f'运行设备：{DEVICE}')
    return model


transform = transforms.Compose([
    transforms.Resize(IMG_SIZE),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])


def preprocess(image_path: Path):
    img = Image.open(image_path).convert('RGB')
    return transform(img).unsqueeze(0).to(DEVICE)


def classify_and_copy(model, input_dir: Path, output_dir: Path):
    all_files = [
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
    ]

    if not all_files:
        print('未找到任何图片，请检查 INPUT_DIR 路径。')
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f'输入文件夹：{input_dir}（共 {len(all_files)} 张图片）')
    print(f'输出文件夹：{output_dir}')

    face_count = 0
    error_count = 0

    with torch.no_grad():
        for file_path in tqdm(all_files, desc='分类进度', ncols=80):
            try:
                tensor = preprocess(file_path)
                prob = torch.sigmoid(model(tensor).squeeze()).item()
                is_face = prob > THRESHOLD

                if is_face:
                    shutil.copy2(file_path, unique_path(output_dir / file_path.name))
                    face_count += 1
            except Exception as e:
                tqdm.write(f'处理失败：{file_path.name} -> {e}')
                error_count += 1

    print('-' * 40)
    print(f'总图片数：{len(all_files)}')
    print(f'识别为人脸：{face_count} 张 -> 已复制到 {output_dir}')
    print(f'识别为非人脸：{len(all_files) - face_count - error_count} 张')
    if error_count:
        print(f'处理失败：{error_count} 张')
    print('-' * 40)


def main():
    print('=' * 50)
    print('人脸图片筛选工具（EfficientNet-B0）')
    print('=' * 50)

    if not MODEL_PATH.exists():
        print(f'未找到模型权重：{MODEL_PATH}')
        print('请自行准备 face_classifier.pth 并放到 classification 目录下')
        return

    model = load_model(MODEL_PATH)
    classify_and_copy(model, INPUT_DIR, OUTPUT_DIR)
    print('完成')


if __name__ == '__main__':
    main()
