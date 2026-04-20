# GeneralBattle FSM

`GeneralBattle` 现在按 4 个战斗阶段驱动：

- `_handle_prepare(context, config)`
- `_handle_in_battle(context, config)`
- `_handle_result(context, config)`
- `_handle_reward(context, config)`

`run_general_battle(config, buff, battle_key)` 会在单一循环里截图、识别 `page_battle_prepare` / `page_battle` / `page_battle_result` / `page_reward`，再把处理分派到对应 handler。

## 快速结束识别

`run_general_battle(config, buff, battle_key, exit_matcher=None)` 支持在结算/奖励之后用任务自身页面特征提前结束，不再一律等待 `reward_no_battle_ts` 的 2 秒兜底。

- `exit_matcher` 参数优先级高于 `_exit_matcher()` 钩子。
- `_exit_matcher()` 适合整任务固定返回页。
- `exit_matcher=` 适合同一任务不同场景返回不同页面。
- 支持类型：`Matcher`、`RecognizerLike`、`Page`。
- `RecognizerLike` 在这里就是 `RuleImage`、`RuleOcr`、`RuleGif` 或自定义 `callable(task) -> bool`。
- 仅当上一轮页面是 `page_battle_result` 或 `page_reward`，且 `continuous_battle=False` 时才会触发快速结束。
- 未声明 matcher 时，行为与之前一致，继续走 2 秒兜底。

### 选择原则

- 优先选“战后调用方本来就会等到的稳定特征”，例如房间页入口按钮、返回按钮、任务主界面标题。
- 不要选战斗中、结算动画中也可能短暂出现的元素，否则虽然主循环有限制窗口，仍会增加误判成本。
- 同一任务所有战斗都回同一个页面时，覆写 `_exit_matcher()` 最省事。
- 同一任务不同模式回不同页面时，用 `run_general_battle(..., exit_matcher=...)` 在调用点传参。
- 如果需要组合条件，直接用 `any_of(...)` / `all_of(...)`，不要在任务里重复造判断轮子。
- 连战场景会自动跳过 exit matcher；不要指望它在 `continuous_battle=True` 时帮你提前结束。

### 运行时行为

- `exit_matcher` 命中时会打印 `Exit matcher hit, battle confirmed ended`。
- 命中后直接返回最近一次结算得到的胜负，不会改写 `context.is_win`。
- `exit_matcher` 未命中时不会有额外副作用，仍按旧逻辑等待 2 秒兜底。

### 钩子示例

```python
from tasks.Component.GeneralBattle.general_battle import ExitMatcher

def _exit_matcher(self) -> ExitMatcher:
    return self.I_BACK_RED
```

上面的写法适合 `RealmRaid`、`AreaBoss` 这类“每次战斗都回同一个任务页”的场景。

### 参数示例

```python
self.run_general_battle(
    config=self.config.orochi.general_battle_config,
    battle_key=self._orochi_battle_key(),
    exit_matcher=self.I_OROCHI_FIRE,
)

self.run_general_battle(
    config=self.config.orochi.general_battle_config,
    battle_key=self._orochi_battle_key(),
    exit_matcher=self.I_CHECK_TEAM,
)
```

上面的写法适合 `Orochi`、`FallenSun` 这类同一任务里同时存在单刷、组队、野队等多种返回页的场景。

## `battle_key`

- `battle_key` 用来标识“同一种战斗类型”的共享上下文。
- 同一个 `battle_key` 会复用共享行为状态；默认情况下，切预设 / 开 buff 只做一次。
- 绿标默认按单次 `run_general_battle()` 调用执行；同一 `battle_key` 下再次调用时会重新绿标。
- 连战会复用同一次调用的 `call_behavior_state`，因此默认不会在下一轮连战中重复绿标。
- 不同战斗类型应传不同 key，避免互相污染。
- 全局接管固定使用 `__legacy_takeover__`。

## 行为作用域

- `BATTLE_KEY`：同一 `battle_key` 下跨多次 `run_general_battle()` 调用只执行一次。
- `CALL`：单次 `run_general_battle()` 调用中只执行一次；连战轮次继续复用该状态。
- 基类默认策略是 `preset -> BATTLE_KEY`、`buff -> BATTLE_KEY`、`green -> CALL`。
- 子任务可以覆写 `_get_battle_behavior_scopes(config, battle_key)` 调整某个行为的执行频率，而不必重写整个 prepare/battle handler。
- 当前 `BattleContext` 同时保存运行时字段、共享行为状态、调用级行为状态与 `buff` 配置。
- 在 handler 或子任务扩展逻辑里，直接调用 `_run_battle_behavior_once("green", lambda: ...)` 即可复用当前通用战斗调用的上下文，不需要再手动透传行为状态。

## 自定义页面识别

子任务不要改全局 `PageRegistry`，而是在 `_register_custom_pages()` 里改当前 session 的页面副本：

```python
from tasks.GameUi.page import any_of, page_reward

def _register_custom_pages(self) -> None:
    reward_page = self.navigator.resolve_page(page_reward)
    if reward_page is None:
        return
    reward_page.recognizer = any_of(self.I_GREED_GHOST, self.I_REWARD, self.I_REWARD_GOLD)
```

## Orochi 示例

```python
from tasks.Component.GeneralBattle.general_battle import BattleAction

def _register_custom_pages(self) -> None:
    reward_page = self.navigator.resolve_page(page_reward)
    if reward_page is not None:
        reward_page.recognizer = any_of(self.I_GREED_GHOST, self.I_REWARD, self.I_REWARD_GOLD)

def _handle_reward(
    self,
    context,
    config,
) -> BattleAction:
    if self.appear(self.I_GREED_GHOST):
        context.reward_no_battle_ts = None
        self.click(random.choice([self.C_REWARD_1, self.C_REWARD_2, self.C_REWARD_3]), interval=1.0)
        return BattleAction.CONTINUE
    return super()._handle_reward(context, config)
```
