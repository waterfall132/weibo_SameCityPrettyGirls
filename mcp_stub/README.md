# MCP Stub 设计说明

## 目标

本目录用于给后续 MCP Server 封装做占位设计。

当前项目建议拆成以下 MCP tools：

### 1. fetch_weibo_local_posts
输入：
- containerid
- luicode
- lfid
- pages

输出：
- 微博数据 CSV
- 帖子条数
- 图片链接列表

### 2. download_weibo_images
输入：
- csv_file

输出：
- 下载图片目录
- 新增图片数量

### 3. classify_face_images
输入：
- image_dir
- model_path
- threshold

输出：
- 人脸图片目录
- 命中数量

### 4. recognize_young_women
输入：
- image_dir
- api_key
- base_url
- model
- batch_size

输出：
- 年轻女性图片目录
- 命中数量

### 5. run_full_pipeline
输入：
- config_path
- pages
- interval
- threshold

输出：
- 全流程执行摘要

---

## 推荐实现方式

未来可使用：

- Python + FastMCP
- Python + 自定义本地 RPC
- Python + subprocess 包装现有 pipeline.py

---

## 当前最简方案

在没有真正 MCP 框架的情况下，智能体可以先通过命令行直接调用：

```bash
python main.py --pages 3 --interval 0
```

把这个视为临时的 `run_full_pipeline` 能力。
