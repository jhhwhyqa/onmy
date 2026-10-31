# This Python file uses the following encoding: utf-8

from __future__ import annotations

import cv2
import numpy as np

from module.atom.image import RuleImage
from module.image.rpc import get_image_client
from module.logger import logger


def match_highlight_rule(rule_image: RuleImage, image: np.ndarray, frame_id: str | None = None) -> bool:
    original_roi_front = list(rule_image.roi_front)
    result = get_image_client().match_rule_with_brightness_window(
        rule_data=rule_image.to_service_payload(),
        image=image,
        frame_id=frame_id,
    )
    matched = rule_image._apply_match_result(result)
    if not matched:
        rule_image.roi_front = original_roi_front
    return matched


def match_button_enabled(
    rule_image: RuleImage,
    image: np.ndarray,
    min_brightness_ratio: float = 0.92,
) -> bool:
    """模板命中后校验平均亮度: 未解锁的按钮(如"前往")整体变暗,
    归一化模板匹配对亮度不敏感分数照样高, 用亮度比拦住。

    :param min_brightness_ratio: 源区域平均亮度 / 模板平均亮度 的下限
    """
    template = cv2.imdecode(
        np.fromfile(rule_image.file, dtype=np.uint8), cv2.IMREAD_COLOR
    )
    if template is None:
        logger.warning(f'{rule_image.name} 模板加载失败')
        return False
    template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
    x, y, w, h = rule_image.roi_back
    source = image[y : y + h, x : x + w]
    if source.shape[0] < template.shape[0] or source.shape[1] < template.shape[1]:
        return False
    res = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val <= rule_image.threshold:
        return False
    rx = int(max_loc[0] + x)
    ry = int(max_loc[1] + y)
    tw, th = template.shape[1], template.shape[0]
    region = image[ry : ry + th, rx : rx + tw]
    ratio = float(region.mean()) / max(float(template.mean()), 1.0)
    if ratio < min_brightness_ratio:
        logger.info(
            f'{rule_image.name} brightness ratio {ratio:.3f} < {min_brightness_ratio}, '
            'treat as locked'
        )
        return False
    logger.debug(f'{rule_image.name} brightness ratio {ratio:.3f}')
    rule_image.roi_front = [rx, ry, tw, th]
    return True
