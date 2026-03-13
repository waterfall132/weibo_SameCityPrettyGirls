# -*- coding: utf-8 -*-
"""
二分类深度学习：人脸识别（face vs non-face）- PyTorch 版本
数据集结构：所有图片平铺在同一文件夹下
    dataset/
        Human835.png  ← face
        Dog001.png    ← non_face
        ...

说明：
1. 本文件仅公开模型结构与训练流程代码
2. 默认数据集路径为示例路径，使用前请自行修改
3. 预训练权重 face_classifier.pth 不包含在 GitHub 脱敏发布包中
"""

import os
import re
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from PIL import Image
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, models

warnings.filterwarnings("ignore")

DATASET_DIR = r"请替换为你的数据集路径"
IMG_SIZE = (224, 224)
BATCH_SIZE = 16
EPOCHS = 20
LR = 1e-4
MODEL_SAVE = "face_classifier.pth"
FACE_LABEL = "Human"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"使用设备：{DEVICE}")

SUPPORTED_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff')


def load_images_binary(dataset_dir: str, face_label: str = "Human"):
    filepaths, labels = [], []

    for file_name in sorted(os.listdir(dataset_dir)):
        file_path = os.path.join(dataset_dir, file_name)

        if os.path.isdir(file_path):
            continue
        if not file_name.lower().endswith(SUPPORTED_EXT):
            continue

        fname = file_name.split('.')[0]

        if fname.isdigit():
            label = 0
        else:
            category = re.sub(r'[^a-zA-Z]', '', fname)
            label = 1 if face_label.lower() in category.lower() else 0

        filepaths.append(file_path)
        labels.append(label)

    return filepaths, labels


def split_data(dataset_dir: str):
    files, labels = load_images_binary(dataset_dir, FACE_LABEL)
    df = pd.DataFrame({'filepaths': files, 'labels': labels})

    print("\n类别分布：")
    print(df['labels'].value_counts().rename({0: 'non_face', 1: 'face'}))

    train_df, tmp_df = train_test_split(
        df, train_size=0.8, shuffle=True,
        random_state=42, stratify=df['labels']
    )
    valid_df, test_df = train_test_split(
        tmp_df, train_size=0.5, shuffle=True,
        random_state=42, stratify=tmp_df['labels']
    )

    print(f"训练集：{len(train_df)} | 验证集：{len(valid_df)} | 测试集：{len(test_df)}")
    return train_df, valid_df, test_df


class FaceDataset(Dataset):
    def __init__(self, df: pd.DataFrame, transform=None):
        self.filepaths = df['filepaths'].values
        self.labels = df['labels'].values.astype(np.float32)
        self.transform = transform

    def __len__(self):
        return len(self.filepaths)

    def __getitem__(self, idx):
        img = Image.open(self.filepaths[idx]).convert("RGB")
        if self.transform:
            img = self.transform(img)
        label = torch.tensor(self.labels[idx], dtype=torch.float32)
        return img, label


def create_dataloaders(train_df, valid_df, test_df):
    train_transform = transforms.Compose([
        transforms.Resize(IMG_SIZE),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(15),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    val_transform = transforms.Compose([
        transforms.Resize(IMG_SIZE),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    train_loader = DataLoader(FaceDataset(train_df, train_transform), batch_size=BATCH_SIZE, shuffle=True, num_workers=2, pin_memory=True)
    valid_loader = DataLoader(FaceDataset(valid_df, val_transform), batch_size=BATCH_SIZE, shuffle=False, num_workers=2, pin_memory=True)
    test_loader = DataLoader(FaceDataset(test_df, val_transform), batch_size=BATCH_SIZE, shuffle=False, num_workers=2, pin_memory=True)

    return train_loader, valid_loader, test_loader


def build_model():
    model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)

    for param in model.parameters():
        param.requires_grad = False

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

    return model.to(DEVICE)


def train_one_epoch(model, loader, criterion, optimizer):
    model.train()
    total_loss, correct, total = 0.0, 0, 0

    for imgs, labels in loader:
        imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
        optimizer.zero_grad()
        outputs = model(imgs).squeeze(1)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * imgs.size(0)
        preds = (torch.sigmoid(outputs) > 0.5).float()
        correct += (preds == labels).sum().item()
        total += imgs.size(0)

    return total_loss / total, correct / total


@torch.no_grad()
def validate(model, loader, criterion):
    model.eval()
    total_loss, correct, total = 0.0, 0, 0

    for imgs, labels in loader:
        imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
        outputs = model(imgs).squeeze(1)
        loss = criterion(outputs, labels)

        total_loss += loss.item() * imgs.size(0)
        preds = (torch.sigmoid(outputs) > 0.5).float()
        correct += (preds == labels).sum().item()
        total += imgs.size(0)

    return total_loss / total, correct / total


def train_model(model, train_loader, valid_loader):
    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=LR)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=3)

    history = {'train_loss': [], 'train_acc': [], 'val_loss': [], 'val_acc': []}
    best_val_loss = float('inf')
    patience_counter = 0
    early_stop_patience = 5

    for epoch in range(1, EPOCHS + 1):
        tr_loss, tr_acc = train_one_epoch(model, train_loader, criterion, optimizer)
        vl_loss, vl_acc = validate(model, valid_loader, criterion)
        scheduler.step(vl_loss)

        history['train_loss'].append(tr_loss)
        history['train_acc'].append(tr_acc)
        history['val_loss'].append(vl_loss)
        history['val_acc'].append(vl_acc)

        print(f"Epoch {epoch:02d}/{EPOCHS} | Train Loss: {tr_loss:.4f} Acc: {tr_acc:.4f} | Val Loss: {vl_loss:.4f} Acc: {vl_acc:.4f}")

        if vl_loss < best_val_loss:
            best_val_loss = vl_loss
            torch.save(model.state_dict(), MODEL_SAVE)
            print(f"最优模型已保存（val_loss={vl_loss:.4f}）")
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= early_stop_patience:
                print(f"Early Stopping（连续 {early_stop_patience} 轮无改善）")
                break

    model.load_state_dict(torch.load(MODEL_SAVE))
    return history


def plot_history(history):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ax, (tr_key, vl_key), title in zip(
        axes,
        [('train_acc', 'val_acc'), ('train_loss', 'val_loss')],
        ['Accuracy', 'Loss']
    ):
        ax.plot(history[tr_key], label=f'Train {title}')
        ax.plot(history[vl_key], label=f'Val {title}')
        ax.set_title(f'Model {title}')
        ax.set_xlabel('Epochs')
        ax.set_ylabel(title)
        ax.legend()

    plt.tight_layout()
    plt.savefig('training_curves.png', dpi=150)
    plt.show()


@torch.no_grad()
def evaluate_model(model, test_loader):
    model.eval()
    all_preds, all_labels = [], []

    for imgs, labels in test_loader:
        imgs = imgs.to(DEVICE)
        outputs = torch.sigmoid(model(imgs).squeeze(1))
        preds = (outputs > 0.5).float().cpu().numpy()
        all_preds.extend(preds)
        all_labels.extend(labels.numpy())

    all_preds = np.array(all_preds, dtype=int)
    all_labels = np.array(all_labels, dtype=int)

    print(classification_report(all_labels, all_preds, target_names=['non_face', 'face']))

    cm = confusion_matrix(all_labels, all_preds)
    plt.figure(figsize=(6, 5))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=['non_face', 'face'], yticklabels=['non_face', 'face'])
    plt.title('Confusion Matrix')
    plt.xlabel('Predicted')
    plt.ylabel('True')
    plt.tight_layout()
    plt.savefig('confusion_matrix.png', dpi=150)
    plt.show()


def predict_image(model, image_path: str, threshold: float = 0.5):
    transform = transforms.Compose([
        transforms.Resize(IMG_SIZE),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    img = Image.open(image_path).convert('RGB')
    tensor = transform(img).unsqueeze(0).to(DEVICE)

    model.eval()
    with torch.no_grad():
        prob = torch.sigmoid(model(tensor).squeeze()).item()

    label = 'face' if prob > threshold else 'non_face'
    confidence = prob if label == 'face' else 1 - prob
    print(f'图片：{image_path}')
    print(f'预测：{label} | 置信度：{confidence:.2%}')
    return label, confidence


def main():
    print('=' * 50)
    print('人脸二分类训练程序（PyTorch + EfficientNet-B0）')
    print('=' * 50)

    train_df, valid_df, test_df = split_data(DATASET_DIR)
    train_loader, valid_loader, test_loader = create_dataloaders(train_df, valid_df, test_df)

    model = build_model()
    print('开始训练...')
    history = train_model(model, train_loader, valid_loader)

    plot_history(history)
    evaluate_model(model, test_loader)


if __name__ == '__main__':
    main()
