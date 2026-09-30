DASHEN_SOURCES = [
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

DASHEN_UIDS = list(dict.fromkeys(source["id"] for source in DASHEN_SOURCES))

# 显示用映射：uid -> 博主名（重复 uid 取第一次出现的名字）
# 「crowd」是大众票这个伪来源，不是 uid
NAME_BY_UID = {"crowd": "大众"}
for _source in DASHEN_SOURCES:
    NAME_BY_UID.setdefault(_source["id"], _source["name"])


def source_label(source) -> str:
    """日志显示用：uid 换成博主名；未知来源原样返回（例如尚未登记的 uid）。"""
    return NAME_BY_UID.get(source, source)


def format_sources(values) -> str:
    """把 {uid: 值} 渲染成「博主名=值, 博主名=值」，用于日志；空字典返回空串。"""
    return ', '.join(f'{source_label(key)}={value}' for key, value in values.items())
