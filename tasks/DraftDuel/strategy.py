"""从《协同分析.xlsx》生成的资料中选择式神和推荐搭配。

本模块不依赖游戏画面。调用方传入当前可选式神及已选队伍，
仅在 OCR 能可靠识别名称后才调用 choose_pick。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


CATALOG_PATH = Path(__file__).with_name('catalog.json')
ENCYCLOPEDIA_PATH = Path(__file__).with_name('encyclopedia.json')
TIER_POINTS = {'特等': 40, '上等': 30, '中等': 20, '下等': 10}
ENCYCLOPEDIA_POINTS = {'SS': 12, 'S': 8, 'A': 4, 'B': 0,
                       'C': -4, 'D': -8, 'E': -12}
USER_RATINGS = {
    '梦山白藏主': 'S',
    '灼华桃花妖': 'S',
    '蚀月吸血姬': 'S',
    '天火命铃彦姬': 'S',
}
USER_TIERS = {'莹草': '特等', '云间不见岳': '特等'}
SUMMON_SLOT_USERS = frozenset({'猫川', '千姬', '雪御前', '跳跳妹妹', '惠比寿'})
USER_ROLES = {
    '梦山白藏主': {'support'},
    '灼华桃花妖': {'sustain'},
    '蚀月吸血姬': {'sustain', 'damage'},
    '天火命铃彦姬': {'damage'},
}
ROLE_POINTS = {'fire': 12, 'sustain': 10, 'shield': 7, 'control': 6,
               'damage': 8, 'tempo': 6, 'support': 4}
SOUL_NAMES = (
    '伤魂鸟', '轮入道', '青女房', '返魂香', '雪幽魂', '钓瓶火',
    '遗念火', '招财', '火灵', '蚌精', '木魅', '薙魂', '地藏',
    '针女', '破势', '狂骨', '网切', '树妖', '珍珠', '狰',
    '魅妖', '魍魉', '钟灵', '日女', '共潜', '共浅', '镜姬',
    '贝吹坊', '出世螺', '隐念', '海月', '三味', '镇墓兽',
)


@dataclass(frozen=True)
class Entry:
    name: str
    rarity: str
    role: str
    strength: str
    weakness: str
    notes: str
    souls: str
    tier: str
    source_row: int


@dataclass(frozen=True)
class Pick:
    name: str
    score: float
    reasons: tuple[str, ...]
    suggested_souls: tuple[str, ...]


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Entry]:
    data = json.loads(path.read_text(encoding='utf-8'))
    return {row['name']: Entry(**row) for row in data['entries']}


CATALOG = load_catalog()


def load_encyclopedia(path: Path = ENCYCLOPEDIA_PATH) -> tuple[dict, dict, dict]:
    if not path.exists():
        return {}, {}, {}
    rows = json.loads(path.read_text(encoding='utf-8'))['entries']
    grouped = {}
    aliases = {}
    for row in rows:
        canonical = row['canonical_name']
        grouped.setdefault(canonical, []).append(row)
        aliases[re.sub(r'[\s·•・&＆:：【】\[\]（）()]', '', row['name'])] = canonical
    # 云外镜有黑、白两行；用样本量较多的一行作评分依据，定位则可合并。
    primary = {
        name: max(items, key=lambda item: (
            (item['wins'] or 0) + (item['losses'] or 0),
            ENCYCLOPEDIA_POINTS.get(item['rating'], -99)))
        for name, items in grouped.items()
    }
    return primary, aliases, grouped


ENCYCLOPEDIA, NAME_ALIASES, ENCYCLOPEDIA_VARIANTS = load_encyclopedia()


def normalize_name(name: str, catalog: Mapping[str, Entry] = CATALOG) -> str | None:
    """接受完整名称或 OCR 前后混入少量属性字的唯一名称。"""
    if '?' in (name or '') or '？' in (name or ''):
        return None
    value = re.sub(r'[\s·•・&＆:：【】\[\]（）()]', '', name or '')
    if value in catalog:
        return value
    if value in NAME_ALIASES and NAME_ALIASES[value] in catalog:
        return NAME_ALIASES[value]
    value = re.sub(r'^(?:SP|SSR|SR|UR|R|联动)', '', value, flags=re.I)
    if value in catalog:
        return value
    if value in NAME_ALIASES and NAME_ALIASES[value] in catalog:
        return NAME_ALIASES[value]
    matches = [candidate for candidate in catalog if candidate in value]
    if not matches:
        return None
    length = max(map(len, matches))
    longest = [candidate for candidate in matches if len(candidate) == length]
    return longest[0] if len(longest) == 1 else None


def role_tags(entry: Entry, *, defense: int | None = None) -> set[str]:
    if entry.name in USER_ROLES:
        return set(USER_ROLES[entry.name])
    if entry.name == '云外镜':
        # 白镜侧重驱散与拉条；防御面板不明时按黑镜保守估值。
        return {'support', 'tempo'} if defense is not None and defense >= 900 else {'damage'}
    role = entry.role
    tags = set()
    if '火机' in role or '鬼火' in role:
        tags.add('fire')
    if any(word in role for word in ('奶', '治疗', '复活')):
        tags.add('sustain')
    if any(word in role for word in ('盾', '减伤', '保单核', '抗单体')):
        tags.add('shield')
    if any(word in role for word in ('控制', '推条')):
        tags.add('control')
    if '输出' in role or '增伤' in role:
        tags.add('damage' if '输出' in role else 'support')
    if '拉条' in role:
        tags.add('tempo')
    if '辅助' in role or '驱散' in role or '解控' in role:
        tags.add('support')
    extra = ENCYCLOPEDIA.get(entry.name, {}).get('role', '')
    if extra == '打火':
        tags.add('fire')
    elif extra == '治疗':
        tags.add('sustain')
    elif extra == '护卫':
        tags.add('shield')
    elif extra == '控制':
        tags.add('control')
    elif extra == '输出':
        tags.add('damage')
    elif extra == '拉条':
        tags.add('tempo')
    elif extra == '综合':
        tags.add('support')
    return tags


def encyclopedia_points(name: str, *, team: Iterable[str] = (),
                        defense: int | None = None) -> float:
    """百科评级和胜率是辅助信号；小样本胜率向 50% 收缩。"""
    row = ENCYCLOPEDIA.get(name)
    if name == '云外镜':
        variant = '云外镜（白）' if defense is not None and defense >= 900 else '云外镜（黑）'
        row = next((item for item in ENCYCLOPEDIA_VARIANTS.get(name, ())
                    if item['name'] == variant), row)
    if not row:
        return 0.0
    samples = (row['wins'] or 0) + (row['losses'] or 0)
    rating = row['rating']
    if name in USER_RATINGS:
        rating = USER_RATINGS[name]
    if name == '茨木童子':
        rating = 'S' if '云间不见岳' in team else 'A'
    grade = ENCYCLOPEDIA_POINTS.get(rating, 0)
    user_rating = name in USER_RATINGS or name == '茨木童子'
    grade_weight = 1.0 if user_rating else min(1.0, max(0.5, samples / 300)) if samples else 0.5
    shrunk_winrate = ((row['wins'] or 0) + 50) / (samples + 100)
    winrate_points = max(-5, min(5, (shrunk_winrate - 0.5) * 40)) if samples else 0
    return grade * grade_weight + winrate_points


def tier_points(entry: Entry, team: Iterable[str] = (), *, speed: int | None = None,
                defense: int | None = None) -> int:
    """条件未满足时取保守等级；未知等级不凭稀有度加分。"""
    if entry.name in USER_TIERS:
        return TIER_POINTS[USER_TIERS[entry.name]]
    if entry.name == '梦山白藏主':
        return 40
    label = entry.tier
    if label in TIER_POINTS:
        return TIER_POINTS[label]
    if label in ('?', '？', ''):
        return 0
    names = set(team)
    if entry.name == '云外镜':
        return 40 if defense is not None and defense >= 900 else 20
    if entry.name == '茨木童子':
        return 40 if '云间不见岳' in names else 30
    if '220以上特等' in label and speed is not None:
        return 40 if speed >= 220 else 30 if speed >= 210 else 20
    if '220以上上等' in label and speed is not None:
        return 30 if speed >= 220 else 20 if speed >= 210 else 10
    if '170上等' in label and speed is not None:
        return 30 if speed >= 170 else 20
    if '火山队特等' in label or '火系特等' in label:
        return 40 if '火山队' in names else 30 if '上等' in label else 10
    if '有季特等' in label:
        return 40 if '季' in names else 30
    if 'SP千姬上等' in label:
        return 30 if '鲸汐千姬' in names else 20
    if '伤魂鸟上等' in label:
        return 30 if '伤魂鸟' in names else 20
    if '破势特等' in label:
        return 40 if '破势' in names else 30
    if '上等到特等之间' in label or '上等特等之间' in label:
        return 35
    if '单上中等' in label or '120速中等' in label:
        return 20
    if '中等' in label:
        return 20
    if '上等' in label:
        return 30
    if '特等' in label:
        return 40
    if '下等' in label:
        return 10
    return 0


def suggested_souls(entry: Entry) -> tuple[str, ...]:
    found = [(entry.souls.index(soul), soul) for soul in SOUL_NAMES
             if soul in entry.souls]
    result = [soul for _, soul in sorted(found)[:3]]
    extra = ENCYCLOPEDIA.get(entry.name)
    if extra and len(result) < 3:
        text = str(extra['summary']) + '\n' + str(extra['panel'])
        for soul in SOUL_NAMES:
            if soul in text and soul not in result:
                result.append(soul)
                if len(result) == 3:
                    break
    return tuple(result)


def team_score(names: Iterable[str], catalog: Mapping[str, Entry] = CATALOG,
               speeds: Mapping[str, int] | None = None,
               defenses: Mapping[str, int] | None = None) -> float:
    team = list(names)
    if len(team) != len(set(team)):
        raise ValueError('阵容中不能重复选择同名式神')
    unknown = [name for name in team if name not in catalog]
    if unknown:
        raise ValueError(f'未知式神: {unknown}')
    speeds = speeds or {}
    defenses = defenses or {}
    tags = [role_tags(catalog[name], defense=defenses.get(name)) for name in team]
    score = sum(tier_points(catalog[name], team, speed=speeds.get(name),
                            defense=defenses.get(name))
                + encyclopedia_points(name, team=team, defense=defenses.get(name))
                for name in team)
    for role, value in ROLE_POINTS.items():
        count = sum(role in item for item in tags)
        if count:
            score += value
            if role == 'damage' and count >= 2:
                score += 4
    if len(team) >= 3 and not any('damage' in item for item in tags):
        score -= 25
    if len(team) >= 4 and not any('fire' in item for item in tags):
        score -= 16
    if len(team) >= 4 and not any({'sustain', 'shield'} & item for item in tags):
        score -= 12
    score -= 20 * max(0, len(SUMMON_SLOT_USERS.intersection(team)) - 1)
    # 表中明确写出的正向搭配。仅命中实际同队名称才加分。
    pairs = (
        ({'初音未来', '鲸汐千姬'}, 9),
        ({'桃花妖', '季'}, 8),
        ({'桃花妖', '云外镜'}, 8),
        ({'桃花妖', '镜音铃连'}, 8),
        ({'稻荷神御馔津', '纺愿缘结神'}, 8),
        ({'歌留多', '龙珏'}, 10),
        ({'犬神', '季'}, 8),
    )
    score += sum(points for pair, points in pairs if pair <= set(team))
    return float(score)


def choose_pick(offers: Iterable[str], team: Iterable[str] = (), *,
                team_size: int = 5, speeds: Mapping[str, int] | None = None,
                defenses: Mapping[str, int] | None = None,
                catalog: Mapping[str, Entry] = CATALOG) -> Pick:
    """在当前候选中选一个；候选识别不完整时由界面层重试 OCR。"""
    current = tuple(team)
    if not 1 <= team_size <= 8 or len(current) >= team_size:
        raise ValueError('队伍人数配置无效或已满')
    resolved = [normalize_name(name, catalog) for name in offers]
    candidates = sorted({name for name in resolved if name and name not in current})
    if not candidates:
        raise ValueError('没有可识别且未入队的候选式神')
    existing_roles = set().union(*(
        role_tags(catalog[name], defense=(defenses or {}).get(name)) for name in current
    )) if current else set()
    need_fire = len(current) >= 3 and 'fire' not in existing_roles
    fire_candidates = [name for name in candidates
                       if 'fire' in role_tags(catalog[name], defense=(defenses or {}).get(name))]
    if need_fire and fire_candidates:
        candidates = fire_candidates
    baseline = team_score(current, catalog, speeds, defenses)
    ranked = []
    for name in candidates:
        entry = catalog[name]
        gain = team_score((*current, name), catalog, speeds, defenses) - baseline
        new_roles = role_tags(entry, defense=(defenses or {}).get(name)) - existing_roles
        reasons = [f'等级：{USER_TIERS.get(name, entry.tier)}']
        extra = ENCYCLOPEDIA.get(name)
        if extra:
            samples = (extra['wins'] or 0) + (extra['losses'] or 0)
            rating = extra['rating']
            if name in USER_RATINGS:
                rating = USER_RATINGS[name]
            if name == '茨木童子':
                rating = 'S' if '云间不见岳' in current else 'A'
            if name == '云外镜':
                rating = '白镜 A' if (defenses or {}).get(name, 0) >= 900 else '黑镜 D（形态未明按黑镜）'
            reasons.append(f'对弈百科：{rating}，{samples}场')
        if need_fire and fire_candidates:
            reasons.append('前三手后缺少打火机，优先补鬼火')
        if new_roles:
            labels = {'fire': '鬼火', 'sustain': '治疗', 'shield': '护盾',
                      'control': '控制', 'damage': '输出', 'tempo': '拉条',
                      'support': '辅助'}
            reasons.append('补位：' + '、'.join(labels[role] for role in sorted(new_roles)))
        ranked.append((gain, tier_points(entry, current, speed=(speeds or {}).get(name),
                                        defense=(defenses or {}).get(name)),
                       name, tuple(reasons)))
    gain, _, name, reasons = max(ranked, key=lambda item: (item[0], item[1], item[2]))
    return Pick(name, gain, reasons, suggested_souls(catalog[name]))


def plan_lineup(available: Iterable[str], *, team_size: int = 5,
                locked: Iterable[str] = (), speeds: Mapping[str, int] | None = None,
                defenses: Mapping[str, int] | None = None,
                catalog: Mapping[str, Entry] = CATALOG) -> tuple[str, ...]:
    """给定完整候选池时搜索高分阵容；locked 中的成员必须保留。"""
    required = tuple(locked)
    if not 1 <= team_size <= 8 or len(required) > team_size:
        raise ValueError('队伍人数配置无效')
    if len(required) != len(set(required)) or any(name not in catalog for name in required):
        raise ValueError('已选阵容含重复或未知式神')
    if len(SUMMON_SLOT_USERS.intersection(required)) > 1:
        raise ValueError('已选阵容占用多个我方召唤位')
    candidates = sorted({name for raw in available
                         if (name := normalize_name(raw, catalog)) and name not in required})
    if len(candidates) + len(required) < team_size:
        raise ValueError('可识别候选不足以组成队伍')
    # 保留多种中途组合，让火机、盾和输出的搭配可以在后几手形成。
    states = [required]
    for _ in range(team_size - len(required)):
        next_states = {}
        for state in states:
            for name in candidates:
                if name not in state:
                    lineup = (*state, name)
                    if len(SUMMON_SLOT_USERS.intersection(lineup)) > 1:
                        continue
                    key = tuple(sorted(lineup))
                    next_states[key] = lineup
        if not next_states:
            raise ValueError('召唤位互斥后候选不足以组成阵容')
        states = sorted(next_states.values(),
                        key=lambda lineup: (team_score(lineup, catalog, speeds, defenses), lineup),
                        reverse=True)[:128]
    return states[0]
