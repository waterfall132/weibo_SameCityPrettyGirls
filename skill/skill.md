# Skill: weibo-local-image-filter

## Skill 简介

这个 Skill 用于执行以下任务：

1. 抓取微博同城帖子
2. 下载微博图片
3. 识别人脸图片
4. 用大模型进一步筛选年轻女性图片

适用于智能体在本地自动化运行该项目。

---

## 适用场景

当用户表达以下需求时，可以调用本 Skill：

- 抓取某个城市的微博同城内容
- 下载微博配图
- 从图片中筛出人脸
- 从人脸图中筛出年轻女性
- 周期性监控某个城市同城微博

---

## 输入参数建议

### 必填
- `pages`: 抓取页数

### 可选
- `interval`: 轮询间隔秒数，0 表示只运行一次
- `threshold`: 人脸分类阈值
- `city_config`: 微博同城抓取参数对象
  - `containerid`
  - `luicode`
  - `lfid`

---

## 前置条件

智能体在调用前应确认：

1. 本地已经存在 `config.json`
2. `config.json` 中已填写真实微博 Cookie 与 XSRF Token
3. 若启用大模型识别，则已配置真实 API Key
4. 若首次运行微博抓取，用户可能需要手动完成微博验证码/滑块
5. 本地已安装 Chrome 与对应 ChromeDriver（或 Selenium 可正常启动 Chrome）

---

## 建议执行步骤

### Step 1：检查配置文件
确认 `config.json` 存在，并至少包含：

- 微博同城参数
- Cookie
- XSRF Token
- 路径配置
- 大模型配置（如果启用）

### Step 2：运行主流程
执行：

```bash
python main.py --pages 3 --interval 0
```

或者由智能体根据参数动态替换：

```bash
python main.py --pages {pages} --interval {interval}
```

### Step 3：若触发验证
如果程序提示微博验证：

- 提醒用户查看浏览器
- 请用户手动登录微博
- 请用户完成滑块/验证码
- 再让用户回到终端按 Enter

### Step 4：读取结果目录
输出结果目录：

- 原始图片：`weibo_images/`
- 人脸图片：`photos_face/`
- 年轻女性图片：`young_women/`

---

## 输出结果建议

智能体可以返回给用户：

- 本轮抓取微博条数
- 本轮下载图片数量
- 本轮识别出的人脸图片数量
- 本轮识别出的年轻女性图片数量
- 输出目录位置

---

## 失败处理建议

### 微博抓取失败
检查：
- Cookie 是否失效
- XSRF Token 是否失效
- 是否需要重新登录微博
- `containerid` 是否正确

### Selenium 启动失败
检查：
- 是否安装 Chrome
- Selenium 版本是否正确
- ChromeDriver 是否可用

### 大模型识别失败
检查：
- API Key 是否正确
- `base_url` 是否可访问
- 模型名称是否正确
- 返回是否是有效 JSON

---

## 安全注意事项

智能体不得：

- 将真实 Cookie 输出到日志
- 将真实 API Key 输出到日志
- 将 `config.json` 原文上传到公共仓库
- 暴露 `chrome_user_data/` 内容

---

## 推荐封装名

- `weibo-local-image-filter`
- `weibo-local-city-crawler`
- `young-women-image-recognition-pipeline`
