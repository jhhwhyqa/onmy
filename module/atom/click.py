# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import numpy as np

from module.base.decorator import cached_property
from module.base.utils.utils import random_normal_distribution_int
from module.logger import logger


class RuleClick:

    def __init__(self, roi_front: tuple, roi_back: tuple, name: str = None,
                 functional: bool = True, profile: str = None) -> None:
        """
        初始化
        :param roi_front:
        :param roi_back:
        :param name:
        :param functional: 该点击是否属于功能操作，供任务层点击记录区分
        :param profile: 点击落点密度档位，生成规则会携带；本地落点算法不使用该参数
        """
        self.roi_front = roi_front
        self.roi_back = roi_back
        if name:
            self.name = name
        else:
            self.name = 'click'
        self.functional = functional
        self.profile = profile

    def coord(self) -> tuple:
        """
        获取坐标, 从roi_front随机获取坐标
        :return:
        """
        x, y, w, h = self.roi_front
        x = random_normal_distribution_int(x, x + w)
        y = random_normal_distribution_int(y, y + h)
        return x, y

    def coord_more(self) -> tuple:
        """
        从roi_back随机获取坐标
        :return:
        """
        x, y, w, h = self.roi_back
        x = random_normal_distribution_int(x, x + w)
        y = random_normal_distribution_int(y, y + h)
        return x, y

    @property
    def center(self) -> tuple:
        """
        返回roi_front的中心坐标
        :return:
        """
        x, y, w, h = self.roi_front
        return x + w // 2, y + h // 2

    def move(self, x: int, y: int) -> None:
        """
        移动roi_front, 需要限幅x是0-1280, y是0-720
        :param x:
        :param y:
        :return:
        """
        x, y, w, h = self.roi_front
        x += x
        y += y
        if x <= 0:
            x = 0
        elif x >= 1280:
            x = 1280

        if y <= 0:
            y = 0
        elif y >= 720:
            y = 720

        self.roi_front = x, y, w, h

    def __repr__(self):
        return self.name
