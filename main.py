# -*- coding: utf-8 -*-
"""
项目统一入口（GitHub 发布版）

示例：
1. 只运行一轮：
   python main.py --pages 3 --interval 0

2. 每小时运行一次：
   python main.py --pages 3 --interval 3600
"""

from pipeline import main


if __name__ == '__main__':
    main()
