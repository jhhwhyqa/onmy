# This Python file uses the following encoding: utf-8
"""邀请好友打鬼王：召唤 → 集结 → 邀请指定好友 → 等待结算。"""
import time
from difflib import SequenceMatcher

from module.logger import logger

# 点完集结后等面板动画的时间
GATHER_WAIT = 1.0
# 邀请面板出现的兜底轮询上限
PANEL_TIMEOUT = 5.0


class FriendInviter:
    """混入 ScriptTask 使用，依赖宿主的 Rule 对象与点击方法。"""

    def find_friend(self) -> bool:
        """OCR 好友列表逐条比对，匹配到指定好友并点击选中。"""
        name_ocr = getattr(self, 'O_MD_FRIENDS', None)
        if name_ocr is None:
            logger.warning('No friend list ocr rule, cannot invite')
            return False
        conf = self.conf.meta_demon_invite
        target = conf.friend_name.strip()
        if not target:
            logger.warning('Friend name is empty, cannot invite')
            return False
        boxed_results = name_ocr.detect_and_ocr(self.device.image, logDisplay=False)
        best_score, best_area = 0.0, None
        for result in boxed_results:
            text = str(result.ocr_text or '').strip()
            if not text:
                continue
            score = SequenceMatcher(None, target, text).ratio()
            logger.info(f'Match friend "{text}" -> "{target}" [{score:.0%}]')
            if score > best_score:
                best_score = score
                best_area = (
                    result.box[0, 0] + name_ocr.roi[0],
                    result.box[0, 1] + name_ocr.roi[1],
                    result.box[1, 0] - result.box[0, 0],
                    result.box[2, 1] - result.box[0, 1],
                )
        if best_area is None or best_score < conf.name_match_ratio_v:
            logger.info(f'No friend matched (best {best_score:.0%}, need {conf.name_match_ratio}%)')
            return False
        x, y, w, h = best_area
        # 坐标点击必须用 device.click，self.click 只收 Rule 对象
        self.device.click(x=int(x + w / 2), y=int(y + h / 2),
                          control_name=f'friend:{target}')
        logger.info(f'Friend "{target}" clicked [{best_score:.0%}]')
        return True

    def invite_friend(self) -> bool:
        """点集结 → 邀请 → 选好友；成功返回 True。"""
        logger.hr('Invite friend')
        self.screenshot()
        if not self.appear(self.I_MD_INVITE):
            logger.warning('No gather button, cannot invite')
            return False
        self.click(self.I_MD_INVITE, interval=0.6)
        time.sleep(GATHER_WAIT)
        # 面板动画兜底轮询
        deadline = time.time() + PANEL_TIMEOUT
        while time.time() < deadline:
            self.screenshot()
            if self.appear(self.I_MD_INVITE_FRIENDS):
                break
            time.sleep(0.5)
        else:
            logger.warning('Invite friends panel did not appear')
            self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
            return False
        # 先选中好友再点邀请；先点邀请只会弹「请选中好友」提示
        # 列表可能要滚动，两屏内找不到就放弃
        for scroll in range(2):
            self.screenshot()
            if self.find_friend():
                # 点邀请把选中的好友拉进队伍
                self.ui_click_until_disappear(self.I_MD_INVITE_FRIENDS, interval=0.6)
                return True
            if scroll == 0:
                self.swipe(self.S_MD_SWIPE_FRIEND_UP, interval=1.0)
        logger.warning('Friend not found in list, give up this invite')
        self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
        return False

    def wait_friend_finish(self) -> bool:
        """等好友接受邀请（「已分享:1人」）再等鬼王被打完，超时返回 False。"""
        conf = self.conf.meta_demon_invite
        deadline = time.time() + conf.wait_timeout * 60
        logger.info(f'Wait for friend (up to {conf.wait_timeout}min)')
        accepted = False
        while time.time() < deadline:
            if self.State.done:
                return False
            # 长等待不点击, stuck 看门狗 60 帧无操作就抛 GameStuckError, 必须定期清记录
            self.device.stuck_record_clear()
            self.screenshot()
            if not accepted and self.appear(self.I_MD_ASSIST_ALONE):
                accepted = True
                logger.info('Friend accepted invite (shared marker), wait boss finish')
            # 挑战按钮消失 = 鬼王被打掉；标记出现前消失是异常兜底
            if not self.appear(self.I_MD_FIRE):
                if accepted:
                    logger.info('Boss finished by friend, invite done')
                else:
                    logger.info('Boss gone before friend joined')
                return True
            time.sleep(conf.poll_interval)
        logger.warning('Wait for friend timed out')
        return False
