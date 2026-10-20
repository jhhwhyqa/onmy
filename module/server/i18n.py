import json
from pathlib import Path


# 随仓库发布的中文名，是唯一的手工维护源。
SHIPPED_ZH_CN = Path.cwd() / 'assets' / 'i18n' / 'zh-CN.json'
# 运行时覆盖：由 /home/chinese_translate 写入，属于用户配置，不进版本库。
RUNTIME_ZH_CN = Path.cwd() / 'config' / 'i18n' / 'zh-CN.json'


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class Addition:
    @classmethod
    def load_additions(cls) -> dict:
        result = {}
        for name in ('en-US', 'zh-CN'):
            result[name] = _load_json(Path.cwd() / 'assets' / 'i18n' / f'{name}.json')
        return result


class I18n(Addition):
    file_shipped_zh_cn = SHIPPED_ZH_CN
    file_zh_cn = RUNTIME_ZH_CN
    _cache = None
    _cache_key = None

    @classmethod
    def _stat_key(cls) -> tuple:
        key = []
        for path in (cls.file_shipped_zh_cn, cls.file_zh_cn):
            try:
                stat = path.stat()
                key.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                key.append((str(path), 0, 0))
        return tuple(key)

    @classmethod
    def load_zh_cn(cls) -> dict:
        key = cls._stat_key()
        if cls._cache is not None and cls._cache_key == key:
            return cls._cache
        data = _load_json(cls.file_shipped_zh_cn)
        data.update(_load_json(cls.file_zh_cn))
        cls._cache = data
        cls._cache_key = key
        return data

    @classmethod
    def save_zh_cn(cls, data) -> None:
        cls.file_zh_cn.parent.mkdir(parents=True, exist_ok=True)
        with cls.file_zh_cn.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False, default=str)

    @classmethod
    def trans_zh_cn(cls, text) -> str:
        return cls.load_zh_cn().get(text, text)

    @classmethod
    def task_title(cls, text) -> str:
        """通知标题：有中文名时写成「中文名 任务名」，没有时只保留任务名。"""
        translated = cls.trans_zh_cn(text)
        return text if translated == text else f'{translated} {text}'


if __name__ == '__main__':
    print(I18n.load_zh_cn())
