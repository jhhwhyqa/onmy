# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep

from cached_property import cached_property
from datetime import datetime, timedelta
import requests
import re
import json
from pathlib import Path

from module.exception import GameStuckError, TaskEnd
from module.logger import logger
from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.base.timer import Timer

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.config_base import TimeDelta
from tasks.FrogBoss.assets import FrogBossAssets
from tasks.FrogBoss.config import Strategy


# 博主动态里判断押注方向的正则（Dashen / Solo 共用）
RED_REGEX = re.compile(r'(押红|押左|压红|压左|红方|红色|我红|我左|红优|左|红六|红七|红八|红九|红十|91开|82开|73开|64开)')
BLUE_REGEX = re.compile(r'(押蓝|押右|压蓝|压右|蓝方|蓝色|我蓝|我右|蓝优|右|蓝六|蓝七|蓝八|蓝九|蓝十|19开|28开|37开|46开)')
# frog_solo：博主没表态时每隔多久重查一次
SOLO_RECHECK_SECONDS = 300

# frog_solo 解析博主动态用：方向等价类（左=红、右=蓝）
DIR_LEFT_CLASS = r'左(?:边|面|方)?|红(?:色|方|队)?'
DIR_RIGHT_CLASS = r'右(?:边|面|方)?|蓝(?:色|方|队)?'
# ① 方向"双写"（左红 / 右蓝 / 右(蓝) / 左边红方）—— 博主的表态几乎都这么写，最可靠
#    只认「左…红」「右…蓝」两种同向组合：避免「红红火火」被当成表态，
#    也避免「红蓝37开」这类比率写法被当成表态
BET_PAIR_REGEX = re.compile(
    r'(?:(左(?:边|面|方)?)[\s（(【\[]*(红(?:色|方|队)?)'
    r'|(右(?:边|面|方)?)[\s（(【\[]*(蓝(?:色|方|队)?))')
# ② 第一人称 / 推荐式表态：我押、我选、推荐…（比普通动词可靠）
BET_PRONOUN_REGEX = re.compile(
    r'(?:我|本|推荐|建议)\s*(?:押|压|选|买)?\s*(' + DIR_LEFT_CLASS + r'|' + DIR_RIGHT_CLASS + r')')
# ③ 普通表态：押红 / 压蓝（「队友全压红了」这类描述句也会命中，所以排在 ①② 之后）
#    排除「想压右边」「可能会选左」这类假设/描述句：动词前一个字是这些修饰词就不算表态
BET_VERB_REGEX = re.compile(
    r'(?<![想能会可要该被])[押压]\s*(' + DIR_LEFT_CLASS + r'|' + DIR_RIGHT_CLASS + r')')
# ④ 时间锚点：10点场 / 18:00 / 10:00~12:00点 / 10-12点场 / 22点局
BET_ANCHOR_REGEX = re.compile(
    r'(?:\d{1,2}\s*[:：]\s*\d{2}(?:\s*[-~～]\s*\d{1,2}\s*[:：]\s*\d{2})?'
    r'|\d{1,2}\s*[-~～]\s*\d{1,2}\s*(?:点|时)'
    r'|\d{1,2}\s*(?:点|时))'
    r'\s*(?:场|局|场次)?\s*[，,：:、；;。\s]*')
# 锚点后允许出现方向词的字数（「22:00 右(蓝)」= 2 字，「10点场 左边」= 3 字）
BET_ANCHOR_WINDOW = 6


def dir_side_of(token: str):
    """方向词 → 'LEFT'/'RIGHT'（左=红、右=蓝）。"""
    if not token:
        return None
    if token[0] in '左红':
        return 'LEFT'
    if token[0] in '右蓝':
        return 'RIGHT'
    return None


def parse_bet_text(body_text: str):
    flat = re.sub(r'\s+', ' ', re.sub(r'#.*?#', ' ', body_text))
    pair = BET_PAIR_REGEX.search(flat)
    if pair:
        return 'LEFT' if pair.group(1) else 'RIGHT'
    for regex in (BET_PRONOUN_REGEX, BET_VERB_REGEX):
        sides = [s for s in (dir_side_of(m.group(1)) for m in regex.finditer(flat)) if s]
        if sides:
            return sides[0] if len(set(sides)) == 1 else None
    for match in BET_ANCHOR_REGEX.finditer(flat):
        window = flat[match.end():match.end() + BET_ANCHOR_WINDOW]
        left = bool(re.search(DIR_LEFT_CLASS, window))
        right = bool(re.search(DIR_RIGHT_CLASS, window))
        if left != right:
            return 'LEFT' if left else 'RIGHT'
    red_span = RED_REGEX.search(flat)
    blue_span = BLUE_REGEX.search(flat)
    red = red_span.start() if red_span else 9999
    blue = blue_span.start() if blue_span else 9999
    if red < blue:
        return 'LEFT'
    if blue < red:
        return 'RIGHT'
    return None


class ScriptTask(RightActivity, FrogBossAssets, GeneralBattleAssets):
    def enter_frog_boss(self):
        self.screenshot()
        if self.appear(self.I_FROG_CHECK):
            return
        self.enter(self.I_FROG_BOSS_ENTER)
        if not self.wait_until_appear(self.I_FROG_CHECK, wait_time=10):
            raise GameStuckError('FrogBoss page not detected after entering activity')

    def run(self):
        self.enter_frog_boss()
        # 进入主界面
        while 1:
            self.screenshot()

            # 已经下注
            if self.appear(self.I_BETTED):
                logger.info('You have betted')
                break
            # 休息中
            if self.appear(self.I_FROG_BOSS_REST):
                logger.info('Frog Boss Rest')
                break
            # 竞猜成功
            if self.appear(self.I_BET_SUCCESS):
                logger.info('You bet win')
                self.detect()
                while 1:
                    self.screenshot()
                    # 下一局可能直接进入休息中，而不再显示左右投注入口。
                    if self.appear(self.I_FROG_BOSS_REST):
                        break
                    if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                        break
                    if self.appear_then_click(self.I_BET_SUCCESS_BOX, interval=1):
                        continue
                    if self.appear_then_click(self.I_REWARD, interval=2):
                        continue
                    if self.appear_then_click(self.I_NEXT_COMPETITION, interval=4):
                        continue
                continue
            # 竞猜失败
            if self.appear(self.I_BET_FAILURE):
                logger.info('You bet lose')
                self.ui_click_until_disappear(self.I_NEXT_COMPETITION)
                self.detect()
                continue
            # 正式竞猜
            if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                self.do_bet()
                continue

        logger.info('FrogBoss end')
        self.next_run()
        raise TaskEnd('FrogBoss')

    def next_run(self):
        time = self.config.model.frog_boss.frog_boss_config.before_end_frog
        time_delta = TimeDelta(hours=time.hour, minutes=time.minute, seconds=time.second)
        time_now = datetime.now()
        time_set = time_now.replace(minute=0, second=0, microsecond=0)
        if 10 <= time_now.hour < 12:
            time_set = time_set.replace(hour=14)
        elif 12 <= time_now.hour < 14:
            time_set = time_set.replace(hour=16)
        elif 14 <= time_now.hour < 16:
            time_set = time_set.replace(hour=18)
        elif 16 <= time_now.hour < 18:
            time_set = time_set.replace(hour=20)
        elif 18 <= time_now.hour < 20:
            time_set = time_set.replace(hour=22)
        elif 20 <= time_now.hour < 22:
            time_set = time_set.replace(hour=0) + TimeDelta(days=1)
        elif 22 <= time_now.hour < 24:
            time_set = time_set.replace(hour=12) + TimeDelta(days=1)
        else:
            time_set = time_set.replace(hour=12)

        self.set_next_run(task='FrogBoss', target=time_set - time_delta)

    def do_bet(self):
        logger.hr('do bet', level=2)
        self.screenshot()
        count_left = self.O_LEFT_COUNT.ocr(self.device.image)
        count_right = self.O_RIGHT_COUNT.ocr(self.device.image)
        match self.config.model.frog_boss.frog_boss_config.strategy_frog:
            case Strategy.Majority:
                click_image = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
            case Strategy.Minority:
                click_image = self.I_BET_LEFT if count_left < count_right else self.I_BET_RIGHT
            case Strategy.Bilibili:
                click_image = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
            case Strategy.Dashen:
                click_image = self.get_dashen(count_left, count_right)
            case Strategy.Solo:
                click_image = self.get_solo(count_left, count_right)
            case Strategy.AlwaysRed:
                click_image = self.I_BET_LEFT
            case Strategy.AlwaysBlue:
                click_image = self.I_BET_RIGHT
            case _:
                raise ValueError(f'Unknown bet mode: {self.config.model.frog_boss.frog_boss_config.strategy_frog}')
        logger.info(f'You strategy is {self.config.model.frog_boss.frog_boss_config.strategy_frog} and bet on {click_image}')
        self.ui_click_until_disappear(click_image)
        self.confirm_bet()

    def select_gold_30(self):
        if not self.appear(self.I_GOLD_30):
            return False
        # 袋子下部的奖励图标会打开说明页，只点击匹配位置的上部袋身。
        x, y, width, height = self.I_GOLD_30.roi_front
        area = (x + width // 4, y + height // 8, width // 2, height // 3)
        self.click(RuleClick(
            roi_front=area, roi_back=area, name='FB_GOLD_30_SELECT',
        ))
        return True

    def confirm_bet(self):
        logger.info('Formal bet')
        timer = Timer(20).start()
        gold_selected = False
        submit_attempts = 0
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_BETTED):
                return
            if self.appear(self.I_FROG_BOSS_REST):
                return
            # 弹窗后方的金额、鼓面仍能匹配，必须先处理弹窗并重新截图。
            if self.appear(self.I_GOLD_30_CHECK):
                logger.info('Close FrogBoss betting reward information')
                self.click(self.C_RANDOM_LEFT, interval=2)
                continue
            if self.appear_then_click(self.I_UI_CONFIRM, interval=2):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2):
                continue
            if not gold_selected:
                if self.select_gold_30():
                    gold_selected = True
                continue
            if submit_attempts < 3 and self.appear_then_click(self.I_BET_SURE, interval=3):
                submit_attempts += 1
                continue
        raise GameStuckError(
            f'FrogBoss betting confirmation timeout: gold_selected={gold_selected}, '
            f'submit_attempts={submit_attempts}'
        )

    def detect(self) -> bool:
        """
        检测是左边赢了还是右边赢的
        :return: True 左边赢了
        """
        if self.appear(self.I_SUCCESS_LEFT) and self.appear(self.I_FAILURE_RIGHT):
            result = True
            logger.info('Left win')
        elif self.appear(self.I_SUCCESS_RIGHT) and self.appear(self.I_FAILURE_LEFT):
            result = False
            logger.info('Right win')
        else:
            result = None
        return result

    def get_bilibili(self) -> RuleImage:
        """
        获取博主的策略选择
        :return:
        """
        pass

    def get_solo(self, count_left, count_right) -> RuleImage:
        cfg = self.config.model.frog_boss.frog_boss_config
        uid = (cfg.solo_uid or '').strip()
        crowd = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
        if not uid:
            logger.warning('frog_solo: solo_uid 为空，直接随大流')
            return crowd

        deadline = self.solo_deadline()
        first_check = True
        while True:
            side = self.fetch_solo_bet(uid)      # 顺带把博主昵称缓存下来（日志里显示昵称）
            name = self.solo_nick()
            if first_check:
                logger.info(f'frog_solo: 只跟 {name}，本轮最晚等到 {deadline:%H:%M:%S}')
                first_check = False
            if side == 'LEFT':
                logger.info(f'frog_solo: {name} 押红，跟随')
                return self.I_BET_LEFT
            if side == 'RIGHT':
                logger.info(f'frog_solo: {name} 押蓝，跟随')
                return self.I_BET_RIGHT
            if datetime.now() >= deadline:
                logger.warning(f'frog_solo: {name} 到截止时间仍未表态，随大流')
                return crowd
            logger.info(f'frog_solo: {name} 本轮还没表态，{SOLO_RECHECK_SECONDS // 60} 分钟后再看')
            self.wait_until_recheck(SOLO_RECHECK_SECONDS)

    @staticmethod
    def solo_deadline() -> datetime:
        now = datetime.now()
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for hour in range(10, 24, 2):
            start = day.replace(hour=hour)
            if now < start:
                return start - timedelta(minutes=5)
        # 已过 22 点场的开始时间 → 22 点场到 24 点（次日 0 点）结束
        return day + timedelta(days=1) - timedelta(minutes=5)

    def wait_until_recheck(self, seconds: float) -> None:
        """等待下一次查询博主动态；期间保持截图，下注入口消失就提前结束等待。"""
        timer = Timer(seconds).start()
        while not timer.reached():
            self.screenshot()
            if not (self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT)):
                logger.warning('frog_solo: 下注入口已消失（盘口可能切换），提前结束等待')
                return
            sleep(5)

    def solo_nick(self) -> str:
        """配置里那位博主的大神昵称（日志里显示它而不是 uid）。

        昵称就在 `getSomeOneFeeds` 的响应里（`result.userInfos[0].user.nick`），
        不用额外请求；一次运行内只查一次，查不到就退回 uid。
        """
        uid = (self.config.model.frog_boss.frog_boss_config.solo_uid or '').strip()
        if not uid:
            return '(未填写UID)'
        cached = getattr(self, '_solo_nick', None)
        if cached:
            return cached
        self._solo_nick = uid          # 先放 uid，防止查不到时反复请求
        try:
            response = requests.get(
                'https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds'
                f'?feedTypes=1,2,3,4,6,7,10,11&someOneUid={uid}', timeout=5)
            user_infos = response.json()['result'].get('userInfos') or []
            nick = user_infos[0]['user'].get('nick') if user_infos else None
            if nick:
                self._solo_nick = nick
                logger.info(f'frog_solo: 博主昵称 = {nick}')
        except Exception as exc:
            logger.warning(f'frog_solo: 查询博主昵称失败，日志里用 UID 代替（{exc}）')
        return self._solo_nick

    def fetch_solo_bet(self, uid: str) -> str or None:
        """拉指定博主最新一条动态，返回 'LEFT'/'RIGHT'；本轮没发或说不清返回 None。"""
        try:
            response = requests.get(
                'https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds'
                f'?feedTypes=1,2,3,4,6,7,10,11&someOneUid={uid}', timeout=5)
            result = response.json()['result']
            user_infos = result.get('userInfos') or []
            if user_infos and not getattr(self, '_solo_nick', None):
                nick = user_infos[0]['user'].get('nick')
                if nick:
                    self._solo_nick = nick          # 顺手拿昵称，供日志显示
                    logger.info(f'frog_solo: 博主昵称 = {nick}')
            feeds = result['feeds']
            if not feeds:
                logger.info('frog_solo: 该博主没有动态')
                return None
            response = requests.get(
                f'https://inf.ds.163.com/v1/web/feed/basic/facade?feedId={feeds[0]["id"]}', timeout=5)
            feed = response.json()['result']['feed']
            body_text = json.loads(feed['content'])['body']['text']
            create_time = feed['createTime']
        except Exception as exc:
            logger.warning(f'frog_solo: 拉取博主动态失败 {exc}')
            return None

        post_time = datetime.fromtimestamp(create_time / 1000)
        now = datetime.now()
        # 只认落在当前盘口时段内的动态（与 Dashen 的 is_time_valid 同一套判断）
        if not any(start <= post_time.hour < end and start <= now.hour < end
                   for start, end in ((10, 12), (12, 14), (14, 16), (16, 18),
                                      (18, 20), (20, 22), (22, 24))):
            logger.info(f'frog_solo: 最新动态 {post_time:%H:%M} 不在当前盘口时段内')
            return None

        side = parse_bet_text(body_text)
        if side is None:
            logger.info(f'frog_solo: 动态里没看出押哪边：{body_text[:60]}')
        return side

    def get_dashen(self, count_left, count_right) -> RuleImage:
        """
        获取博主的策略选择，整合多个博主的投注策略，并返回最终的下注建议
        :return: 'left' 或 'right' 的下注目标
        """
        logger.info('Fetching strategy from multiple Dashen UPer')
        red_regex, blue_regex = RED_REGEX, BLUE_REGEX

        # 获取 feedId 的函数
        def get_feed_id(uid):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds?feedTypes=1,2,3,4,6,7,10,11&someOneUid={uid}'
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if 'result' in data and 'feeds' in data['result'] and len(data['result']['feeds']) > 0:
                    return data['result']['feeds'][0]['id']
            return None
        
        # 获取 feed 详细信息的函数
        def get_feed_details(feed_id):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/facade?feedId={feed_id}'
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                try:
                    user_nick = data['result']['userInfos'][0]['user']['nick']
                    create_time = data['result']['feed']['createTime']
                    content_json = data['result']['feed']['content']
                    content_data = json.loads(content_json)
                    body_text = content_data['body']['text']
                    return {
                        'user_nick': user_nick,
                        'create_time': create_time,
                        'body_text': body_text
                    }
                except (KeyError, IndexError, json.JSONDecodeError):
                    return None
            return None
        
        # 检查发布时间是否符合规则
        def is_time_valid(create_time):
            # 定义时间段
            valid_time_ranges = [(10, 12), (12, 14), (14, 16), (16, 18), (18, 20), (20, 22), (22, 24)]
            now = datetime.now()
            # now = datetime(year=2024, month=10, day=3, hour=19, minute=45, second=0)  # 指定时间读取历史文章
            
            # 获取发布时间
            post_time = datetime.fromtimestamp(create_time / 1000)  # 假设 create_time 是毫秒级时间戳
            post_hour = post_time.hour
            
            # 检查发布时间是否在有效时间段内
            for start, end in valid_time_ranges:
                if start <= post_hour < end and start <= now.hour < end:
                    return True
            return False

        # 分析 body_text 来判断投注结果
        def analyze_bet(body_text):
            red_span=9999
            blue_span=9999
            if red_regex.search(body_text):
                red_span=red_regex.search(body_text).start()
            if blue_regex.search(body_text):
                blue_span=blue_regex.search(body_text).start()
            if red_span < blue_span:
                return 'LEFT'
            elif red_span > blue_span:
                return 'RIGHT'
            return 'Unknown'

        # 提供的 uid 列表
        uids = [
            {"name": "面灵气喵", "id": "462382f1127b46c5add1185d88f0ea40"},
            {"name": "余岁岁", "id": "54399446d5084a0e8878dac8f6ff56d0"},
            {"name": "七面相", "id": "840742d60e4a43208605ae68ca8c3f64"},
            {"name": "待机中的徐ok", "id": "c3c989fae4074d04b478b8ba47ae4120"},
            {"name": "雯雯", "id": "aaa923436aa440df9ac1ee3f47387b99"},
            {"name": "晨时微凉", "id": "72584a679e2f45b6859566b5523400d5"},
            {"name": "梅布斯尼", "id": "3d4726d99f2642a485729695b798cb8c"},
            {"name": "鸽海成路", "id": "1d2dcbbd7e3d481c8d0f27ba4ff0dc71"},
            {"name": "徐清林", "id": "21657a558bdd4ddfb6501298350336e7"},
            {"name": "不包邮哦亲", "id": "0e4e0c5a1e494a1fa9a58ac55de689c1"},
            {"name": "天真珈百璃", "id": "30e383c884f844a18a7a76fe3c1e888f"},
            {"name": "薛定谔家查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "嘤嘤井", "id": "e7107cd3010e418da26672669d8eeb5e"},
            {"name": "Prince班崎", "id": "74adeb1bfb2b4cf382edbbb430da2149"},
            {"name": "靠脸混饭", "id": "e87f855f36f24b34b9d8f8a4fb2d62b2"},
            {"name": "夜神月丶L", "id": "82de68c7672e4b6da65493fb829b57b6"},
            {"name": "是大荣啦", "id": "f6d6bb15d6024200a985752e2ab4c373"},
            {"name": "炒饭菌", "id": "06e2bba14a914012bc8064601cfa19ea"},
            {"name": "清流不加班", "id": "8982241de1844638b4bb455139b8dcc0"},
            {"name": "槐夏三十", "id": "a9724e98c1cb4a4e931ebc3f467ea73d"},
            {"name": "落沫颜", "id": "e9b0a16325af46628e8dfb9e7942cf1d"},
            {"name": "Mico林木森", "id": "b6b5bc8277e34f69aeca018db0081397"},
            {"name": "查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "CC南浔", "id": "74db771d92a54c28ae3e98d19aa565a3"},
            {"name": "冰七喜Den", "id": "e498e524252041e29999b38e57c4df1d"},
            {"name": "行水姑娘", "id": "30b0c2923faa483f95572c324a5bc910"},
            {"name": "更慕林", "id": "e32aedbdd8da46a5b5b497a16c4b7658"},
            {"name": "二蛋搬砖", "id": "3efc40a0a9754bd0922c3d75752beaf4"}
        ]

        # 主函数，遍历这批 uid
        count_uper_left = 0  # 统计博主投注左侧红方次数
        count_uper_right = 0  # 统计博主投注右侧蓝方次数

        for user in uids:
            uid = user['id']
            name = user['name']
            feed_id = get_feed_id(uid)
            if feed_id:
                details = get_feed_details(feed_id)
                # 检查 create_time 和 body_text
                if details and is_time_valid(int(details['create_time'])) and details['body_text']:
                    bet_result = analyze_bet(details['body_text'])
                    bet_rate = (re.compile(r"([5-9]\d%|\d+开|[一二三四五六七八九十零]+开|([红蓝][一二三四五六七八九十零,0-9])+)")
                            .search(details.get('body_text')))
                    if bet_rate:
                        bet_rate = ',' + bet_rate.group()
                    else:
                        bet_rate = ''
                    # 输出博主结论，可省略
                    # logger.info(f"{name}({details['user_nick']}) has bet on the {bet_result}{bet_rate}")

                    # 根据投注结果更新统计
                    if bet_result == 'LEFT':
                        count_uper_left += 1
                    elif bet_result == 'RIGHT':
                        count_uper_right += 1

        # 最终输出决策
        if count_uper_left > count_uper_right:
            logger.info(f"Final decision: The best bet is LEFT({count_uper_left}:{count_uper_right})")
            return self.I_BET_LEFT  # 返回下注的目标是左边
        elif count_uper_right > count_uper_left:
            logger.info(f"Final decision: The best bet is RIGHT({count_uper_right}:{count_uper_left})")
            return self.I_BET_RIGHT  # 返回下注的目标是右边
        else:
            logger.info("Final decision:Left and right bets are equal, default bet is minority")
            # 若五五开则投注少数博反压奖励
            if count_left < count_right:
                return self.I_BET_LEFT
            else:
                return self.I_BET_RIGHT


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()

