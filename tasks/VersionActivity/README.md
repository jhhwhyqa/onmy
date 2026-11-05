# 版本活动（锦绣南行 · 学艺切磋）

版本活动槽位当前承载「锦绣南行」里的「学艺切磋」挑战。版本活动结束后不会复刻，
因此素材和代码按“版本活动通用”命名，后续换活动时直接替换素材即可。

## 流程

```
run()
 ├─ switch_soul()                              # 勾选时先回式神录切换御魂
 └─ run_version_activity()
     ├─ goto page_main → find_version_entry()   # 庭院右侧栏目最多切八轮找入口
     ├─ goto page_version_battle                 # 经大厅进入学艺切磋挑战页
     └─ while True:
         ├─ update_status()        # count >= challenge_limit → LimitCountOut
         │                         # 已运行 >= limit_time    → LimitTimeOut
         ├─ goto page_version_battle
         ├─ enter_version_battle()
         │   ├─ 读「剩x/30次」
         │   ├─ x == 0 → LimitCountOut
         │   └─ 点挑战并等待进入战斗
         ├─ random_sleep（按配置）
         └─ run_general_battle(battle_conf, exit_matcher=I_VERSION_BATTLE)
```

### 剩余次数

- 挑战页右下角区域 `(1124,664,116,32)`，文本为「剩x/30次」。
- 连续两次读不到（区域消失）视为 `x = 0`。
- 读到非空文本但解析不出 `x` 时直接抛 `GameStuckError`，不做猜测。
- `challenge_limit` 仍作为额外上限：`x == 0` 或达到配置次数，两者先到先停。
- 默认 `challenge_limit = 1`；需要多打时在配置里调高。

### 御魂切换

复用 `tasks/Component/SwitchSoul`，在开跑前执行一次：

- `switch_soul_config.enable` + `switch_group_team`（`组号,队伍号`）
- `switch_soul_config.enable_switch_by_name` + `group_name` / `team_name`

两项都不勾选则完全跳过。

### 战斗配置

只在第一场启用 `preset_enable`，并强制 `lock_team_enable=False`、
`continuous_battle=False`、`max_continuous=0`。

## 文件

| 文件 | 说明 |
|---|---|
| `script_task.py` | 流程实现（状态机写法） |
| `page.py` | 大厅/挑战页、庭院入口查找、进入失败的处置 hook |
| `config.py` | 挑战次数 / 最长运行时间 / 随机休息 / 结束后整理御魂 / 御魂切换 / 战斗设置 |
| `assets.py` | 由 `dev_tools/assets_extract.py` 从 `as/version_activity/*.json` 生成 |
| `as/version_activity/` | 版本活动通用识别素材 + `image.json` / `ocr.json` |

## 注意

- 当前不处理挑战前的确认弹窗；如果游戏出现确认框，会等待进入战斗超时并报错。
- 版本活动结束不再复刻，后续换活动时建议直接替换 `as/version_activity/` 下的素材，
  保持通用资源名不变。
