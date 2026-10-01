import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks.FrogBoss.frog_oas import RELIABILITY_PRIOR, OasHistory, parse_side, same_lineup


class OasTests(unittest.TestCase):
    @staticmethod
    def smoothed(correct, total):
        """期望值走和 frog_oas 同一套拉普拉斯平滑公式，改先验强度时测试自动跟随。"""
        half = RELIABILITY_PRIOR / 2
        return (correct + half) / (total + RELIABILITY_PRIOR)

    def test_persistence_rewards_and_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.jsonl'
            store = OasHistory(path)
            decision = store.choose('0' * 512, 20, 10, [
                {'uid': 'a', 'side': 'LEFT'}, {'uid': 'b', 'side': 'RIGHT'}])
            self.assertEqual(store.reliability('a'), .5)
            self.assertEqual(store.choose('0' * 512, 10, 20, [])['id'], decision['id'])
            self.assertIsNone(store.settle('1' * 512, 'LEFT'))
            store.settle('0' * 512, 'LEFT')
            self.assertIsNone(store.settle('0' * 512, 'LEFT'))
            reloaded = OasHistory(path)
            # 平滑后单次命中不再直接给 1.0 / 0.0
            self.assertAlmostEqual(reloaded.reliability('a'), self.smoothed(1, 1))
            self.assertAlmostEqual(reloaded.reliability('b'), self.smoothed(0, 1))
            self.assertAlmostEqual(reloaded.reliability('crowd'), self.smoothed(1, 1))
            second = reloaded.choose('1' * 512, 10, 20, [
                {'uid': 'a', 'side': 'LEFT'}, {'uid': 'b', 'side': 'LEFT'}])
            self.assertAlmostEqual(second['scores']['LEFT'],
                                   self.smoothed(1, 1) + self.smoothed(0, 1))
            self.assertAlmostEqual(second['scores']['RIGHT'], self.smoothed(1, 1))
            self.assertEqual(second['mode'], 'win_rate')
            reloaded.settle('1' * 512, 'RIGHT')
            self.assertAlmostEqual(reloaded.reliability('a'), self.smoothed(1, 2))
            self.assertAlmostEqual(reloaded.reliability('b'), self.smoothed(0, 2))
            self.assertAlmostEqual(reloaded.reliability('crowd'), self.smoothed(2, 2))

    def test_fallback_and_missing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            self.assertEqual(store.choose('0' * 512, 1, 2, [])['side'], 'RIGHT')
            self.assertEqual(store.reliability('crowd'), .5)
            with patch('tasks.FrogBoss.frog_oas.random.choice', return_value='LEFT'):
                self.assertEqual(store.choose('1' * 512, 0, 0, [])['side'], 'LEFT')

    def test_cold_start_two_equal_groups(self):
        predictions = [{'uid': str(i), 'side': 'LEFT' if i < 6 else 'RIGHT'} for i in range(9)]
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            agreed = store.choose('0' * 512, 20, 10, predictions)
            self.assertEqual(agreed['side'], 'LEFT')
            self.assertEqual(agreed['scores'], {'LEFT': 2, 'RIGHT': 0})
            with patch('tasks.FrogBoss.frog_oas.random.choice', return_value='RIGHT') as choose:
                opposed = store.choose('1' * 512, 10, 20, predictions)
                self.assertEqual(opposed['scores'], {'LEFT': 1, 'RIGHT': 1})
                self.assertEqual(opposed['side'], 'RIGHT')
                choose.assert_called_once_with(('LEFT', 'RIGHT'))

    def test_bet_outcome_settlement_enters_weighted_mode(self):
        for side in ('LEFT', 'RIGHT'):
            for won in (True, False):
                with self.subTest(side=side, won=won), tempfile.TemporaryDirectory() as directory:
                    store = OasHistory(Path(directory) / 'history.jsonl')
                    left, right = (20, 10) if side == 'LEFT' else (10, 20)
                    first = store.choose('0' * 512, left, right, [{'uid': 'a', 'side': side}])
                    result = store.settle('0' * 512, bet_won=won)
                    expected = side if won else ('RIGHT' if side == 'LEFT' else 'LEFT')
                    self.assertEqual(result['winner'], expected)
                    self.assertEqual(result['id'], first['id'])
                    self.assertEqual(result['source'], 'bet_outcome')
                    self.assertAlmostEqual(
                        store.reliability('a'), self.smoothed(1, 1) if won else self.smoothed(0, 1))
                    self.assertIsNone(store.settle('0' * 512, bet_won=won))
                    reloaded = OasHistory(store.path)
                    second = reloaded.choose('1' * 512, left, right, [{'uid': 'a', 'side': side}])
                    self.assertEqual(second['mode'], 'win_rate')

    def test_bet_outcome_rejects_missing_or_ambiguous_lineup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            first = store.choose('0' * 512, 20, 10, [])
            self.assertIsNone(store.settle('1' * 512, bet_won=True))
            duplicate = dict(first)
            for key in ('kind', 'version', 'recorded_at'):
                duplicate.pop(key)
            duplicate['id'] = 'another-round'
            store.append('decision', **duplicate)
            self.assertIsNone(store.settle('0' * 512, bet_won=True))
            self.assertFalse(any(e['kind'] == 'result' for e in store.events))

    def test_winner_icons_take_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.choose('0' * 512, 20, 10, [])
            result = store.settle('0' * 512, 'RIGHT', bet_won=True)
            self.assertEqual(result['winner'], 'RIGHT')
            self.assertEqual(result['source'], 'winner_icons')

    def test_record_page_exact_round_and_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='ten', slot='2026-09-30:5', side='LEFT',
                         votes={'a': 'LEFT', 'crowd': 'LEFT'})
            store.append('decision', id='twelve', slot='2026-09-30:6', side='RIGHT',
                         votes={'a': 'RIGHT', 'crowd': 'LEFT'})
            result = store.settle_record('2026.09.30 12:00', False)
            self.assertEqual(result['id'], 'twelve')
            self.assertEqual(result['winner'], 'LEFT')
            self.assertEqual(result['source'], 'record_page')
            self.assertAlmostEqual(store.reliability('a'), self.smoothed(0, 1))
            self.assertAlmostEqual(store.reliability('crowd'), self.smoothed(1, 1))
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False))
            self.assertEqual(len([e for e in store.events if e['kind'] == 'result']), 1)
            self.assertEqual(store.settle_record('2026.09.30 10:00', True)['winner'], 'LEFT')

    def test_record_page_rejects_invalid_unknown_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='a', slot='2026-09-30:6', side='LEFT', votes={})
            for stamp in ('12:00', '2026.09.30 13:00', '2026.09.30 12:30',
                          '2026.02.30 12:00', '2099.09.30 12:00', '2026.09.29 12:00'):
                self.assertIsNone(store.settle_record(stamp, True))
            self.assertIsNone(store.settle_record('2026.09.30 12:00', None))
            self.assertIsNotNone(store.settle_record('2026.09.30 12:00', True))
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False))
            self.assertEqual(store.events[-1]['reason'], 'conflicting_record_result')

    def test_record_page_does_not_guess_between_duplicate_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            for key in ('a', 'b'):
                store.append('decision', id=key, slot='2026-09-30:6', side='LEFT', votes={})
            self.assertIsNone(store.settle_record('2026.09.30 12:00', True))
            self.assertFalse(any(e['kind'] == 'result' for e in store.events))

    def test_selected_side_verifies_bet_and_keeps_raw_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='a', slot='2026-09-30:6', side='RIGHT',
                         votes={'a': 'RIGHT', 'crowd': 'LEFT'})
            result = store.settle_record('2026.09.30 12:00', False, selected_side='RIGHT')
            self.assertEqual(result['winner'], 'LEFT')
            self.assertAlmostEqual(store.reliability('crowd'), self.smoothed(1, 1))
            self.assertAlmostEqual(store.reliability('a'), self.smoothed(0, 1))
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False, selected_side='RIGHT'))
            self.assertEqual(len([e for e in store.events if e['kind'] == 'record']), 1)
            self.assertIsNone(store.settle_record('2026.09.30 10:00', True, selected_side='LEFT'))
            self.assertEqual(len([e for e in store.events if e['kind'] == 'record']), 2)

    def test_selected_side_mismatch_does_not_update_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='a', slot='2026-09-30:6', side='LEFT', votes={'a': 'LEFT'})
            self.assertIsNone(store.settle_record('2026.09.30 12:00', False, selected_side='RIGHT'))
            self.assertEqual(store.events[-1]['reason'], 'record_bet_side_mismatch')
            self.assertEqual(store.reliability('a'), .5)

    def test_reliability_smoothing_keeps_small_samples_near_neutral(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OasHistory(Path(directory) / 'history.jsonl')
            store.append('decision', id='r', slot='2026-09-30:6', side='LEFT',
                         votes={'a': 'LEFT', 'b': 'RIGHT'})
            self.assertIsNotNone(store.settle_record('2026.09.30 12:00', True))
            # 只结算过一次：命中方 < 1.0、失手方 > 0.0，都被拉向 0.5
            self.assertAlmostEqual(store.reliability('a'), self.smoothed(1, 1))
            self.assertAlmostEqual(store.reliability('b'), self.smoothed(0, 1))
            self.assertGreater(store.reliability('a'), 0.5)
            self.assertLess(store.reliability('b'), 0.5)
            self.assertLess(store.reliability('a'), 1.0)
            self.assertGreater(store.reliability('b'), 0.0)
            # 无样本来源仍是中性 0.5
            self.assertAlmostEqual(store.reliability('从未出现'), 0.5)

    def test_parse_side_real_corpus_formats(self):
        """正文取自任务实际抓到的博主动态（data/frog_oas/*.jsonl 里的原样文本）。"""
        cases = [
            # 时间锚点 + 方向：旧实现全判 None 的写法
            ('十周年对弈竞猜第一局 10:00 左(红) 100%±0%', 'LEFT'),
            ('十周年对弈竞猜第一天 18:00 右(蓝) 64%±1%', 'RIGHT'),
            ('【对弈竞猜分析】 9月30号 10点场     左边。  福利局，左边胜率100%', 'LEFT'),
            ('【对弈竞猜分析】 9月30号 18点场   右边。  46开，左边虽然配合稀碎', 'RIGHT'),
            ('【对弈竞猜】day1 10-12点场 红 输了评论区抽个648', 'LEFT'),
            ('【对弈竞猜】day1 18-20点场 蓝 输了评论区抽个24花合战', 'RIGHT'),
            ('30日对弈竞猜20点，红！55开！但饴细工是大吉之兆啊', 'LEFT'),
            ('30日对弈竞猜18点，蓝！饴细工是大凶之兆，相信佛佛即将带领蓝方首胜', 'RIGHT'),
            ('【对弈竞猜】Day1-10：00左红  ☆ 输了评论区抽五个花合', 'LEFT'),
            ('2026年9月30日10点场福利局左红#刹那之卷# #阴阳师#', 'LEFT'),
            ('【9.30号对弈18点场】右边蓝方 希望佛爷能重现辉煌！', 'RIGHT'),
            ('【10.1号对弈】12点场，左边红方 红方需要神奇小巧思，蓝方需要鬼火', 'LEFT'),
            ('18点右，预感神无月成新的对弈鬼火冥灯，不会一天红的，bro', 'RIGHT'),
            ('10点场： 左边。 信一手烬天玉藻前会智能集火', 'LEFT'),
            ('【对弈竞猜】9月30日，10:00~12:00点，押左（🟥）', 'LEFT'),
            # 明确动词优先：先分析双方、最后一句才表态，不能被前文带偏
            ('【对弈竞猜】 12点局； 五五开 红方卑弥呼破盾就能推条，蓝方两个暴力输出，这局我蓝方三十万', 'RIGHT'),
            ('【对弈竞猜】 18点局； 五五开 红方感觉全靠大花输出了，蓝方有木魅扣鬼火，押蓝', 'RIGHT'),
            # 拿不准一律 None：只分析不表态 / 干扰词 / 两边都提
            ('■ 六四开，红方这边整体联动会更完整一些，神无月、饴细工', None),
            ('对弈竞猜——实测第1天——第5局——蓝色！ 浔浔子：这局蓝色！ 测试中红色神无月', None),
            ('感神无月成新的对弈鬼火冥灯，不会一天红的，bro，洗个澡准备开播了', None),
            ('10点场开门红福利局，这把很稳', None),          # 干扰词不能当成「红」
            ('10点场开门红，右边蓝方更稳', 'RIGHT'),          # 干扰词也不能盖住真实表态
            ('不押红，押蓝', None),
            ('押红还是押蓝', None),
        ]
        for text, expected in cases:
            with self.subTest(text=text[:26]):
                self.assertEqual(parse_side(text), expected)

    def test_ambiguous_text_and_signature(self):
        self.assertEqual(parse_side('本场押红'), 'LEFT')
        self.assertIsNone(parse_side('不押红，押蓝'))
        self.assertIsNone(parse_side('押红还是押蓝'))
        self.assertTrue(same_lineup('0' * 512, '1' * 10 + '0' * 502))
        self.assertFalse(same_lineup('0' * 512, '1' * 512))


if __name__ == '__main__':
    unittest.main()
