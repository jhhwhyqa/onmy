# 版本活动（月华流光）

限时活动分组下的「版本活动」槽位，当前承载**月华流光**的挑战流程。

## 流程

`script_task.py` 按本地 `BaseAct`（`tasks/ActivityShikigami/base_act.py`）的状态机
写法实现，用异常做流程控制：

```
run()
 ├─ switch_soul()                              # 勾选时先回式神录切换御魂（见下）
 └─ run_moonlight()
     ├─ goto page_main → find_moonlight_entry()   # 庭院右侧栏目最多切八轮找入口
     ├─ goto page_moon_battle                     # 经大厅进入挑战页
     └─ while True:
         ├─ update_status()        # 次数 >= challenge_limit → LimitCountOut
         │                         # 已运行 >= limit_time    → LimitTimeOut
         ├─ goto page_moon_battle
         ├─ enter_moonlight_battle()   # 读资源→点挑战→处理弹窗，返回 False 表示资源不足
         ├─ random_sleep（按配置）
         └─ run_general_battle(battle_conf, exit_matcher=I_MOON_BATTLE)
```

### 御魂切换

复用 `tasks/Component/SwitchSoul`（多数任务共用的组件），在开跑前执行一次：

- `switch_soul_config.enable` + `switch_group_team`（`组号,队伍号`，如 `1,2`）按编号切换
- `switch_soul_config.enable_switch_by_name` + `group_name` / `team_name` 按 OCR 名称切换

两项都不勾选则完全跳过（不会进式神录），步骤失败会抛给框架按失败间隔重排。

`finish_activity_task()` 回到庭院、按 `active_souls_clean` 安排御魂整理，
并 `set_next_run(task='VersionActivity', success=True, finish=True)`。

### 判定细节（与上游一致）

- **资源阈值 6**：`O_MOON_RESOURCE` 连续两次读数都低于 6 才停止（资源有刷新延迟）
- **奖励上限弹窗**：只有 OCR 明确读到「奖励已达获取上限」+「继续挑战」才点确认；
  其它未知确认框一律**取消**并安全退出，不做盲点击
- **战斗配置覆盖**：只在第一场启用 `preset_enable`，并强制
  `lock_team_enable=False`、`continuous_battle=False`、`max_continuous=0`

## 文件

| 文件 | 说明 |
|---|---|
| `script_task.py` | 流程实现（状态机写法） |
| `page.py` | 大厅/挑战两级页面、庭院入口查找、进入失败的处置 hook |
| `config.py` | 挑战次数 / 最长运行时间 / 随机休息 / 结束后整理御魂 / 御魂切换 / 战斗设置 |
| `assets.py` | 由 `dev_tools/assets_extract.py` 从 `as/moonlight/*.json` 生成 |
| `as/moonlight/` | 月华流光的 5 张识别素材 + `image.json` / `ocr.json` |

## 素材来源

取自 [tomoe1-1/OnmyojiAutoScript](https://github.com/tomoe1-1/OnmyojiAutoScript)
的提交 `d52612c135c0cfacf32f21b9884929e169c16064`（feat(活动): 新增月华流光独立任务
`tasks/Moonlight`），**只取其月华流光部分的资产**。

两点说明：

1. 该提交的 `tasks/Moonlight/assets.py` 里有两条 RuleOcr（`moon_resource`、
   `moon_reward_notice`），但它仓库里**没有对应的 json 源**。这里补了
   `as/moonlight/ocr.json`，保证本地生成器能产出、且 json 与 `assets.py` 一致。
2. 素材文件夹与资产名沿用上游的 `as/moonlight/`、`I_MOON_*` / `O_MOON_*`，
   便于对照上游实现。

## 与上游实现的差异

上游那条流程依赖它自己的 action_type 活动框架，本地**没有**这些 API，
所以流程按本地架构重写（判定条件与素材保持一致）：

- `BaseAct` 的 `action_limit` / `prepare_next_action` / `record_action` /
  `finish_activity_task` / `time_limit_reached` / `action_count` /
  `scheduled_task_name` / `battle_config`
- `C_SAFE_RANDOM_CLICK_AREA_ACT`（`RuleScatter`，需要 `module/atom/scatter.py`）
- `device.performance.timeout(...)`（改用本地 `Timer`）
- `tasks/ActivityShikigami.page` 的 `handle_activity_reward` / `handle_activity_close`
  / `handle_activity_story`（改用本地 `add_enter_failure_hooks` 的等价写法）

## 未验证项

本机跑不起 OAS，以上只做到导入级 / 结构级验证，**实机行为未经确认**：

- 庭院入口查找依赖「最多切八轮栏目」，若实际栏目更多可能找不到
- 大厅页的 enter-failure hook 依赖导航器的重试预算（流程里已用
  `find_moonlight_entry` 先显式定位，hook 只作兜底）
- `O_MOON_REWARD_NOTICE` 的文案匹配（「奖励已达获取上限」「继续挑战」）需实机复核
- 御魂切换复用已在其它任务使用的 `SwitchSoul` 组件，但「本任务里先切换再进活动」
  的顺序（含切换后从式神录导航回庭院）未实机验证
