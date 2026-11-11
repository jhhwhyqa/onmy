# 账号切换（AccountSwitch）

一键批量切号，让多个账号轮流执行当前配置里已启用的所有任务。

## 它是干嘛的

比如你有 10 个账号，想让它们每天各自跑一遍「悬赏封印 + 觉醒 + 结界突破」。  
普通做法是手动一个个切号去点，这个功能可以自动化：

```
切到 1 号 → 触发所有已启用任务跑一遍 → 切到 2 号 → 触发所有任务 → ... → 切到 10 号
```

一轮切完后，任务会自动「1 天后」再开始新一轮，实现每天自动给所有账号做完任务。

## 核心思路

- **切号**：复用「一键协战」的切号框架，按账号列表顺序循环切号。
- **当天缓存**：和一键协战一样，每个账号第一次切号（成功或失败）时把日期记进该账号的 `switch_date`。同一天里重启 OAS、重复运行或指针被重置，都会跳过已经切过的账号，不会重复登录。
- **触发任务**：每切完一个号，会把当前配置里**所有已启用任务**（`scheduler.enable = true`）的运行时间重置为「现在」，让它们立即排队执行。
- **优先级最低**：「账号切换」自己排在调度序列最末，所以只要有别的任务没跑完，就不会抢着切下一个号——形成「切号 → 跑任务 → 再切号」的闭环。

## 怎么配置

### 1. 填写账号列表

账号列表和「一键协战」一样，只能**手改 JSON**（GUI 里没有数组控件，改不了）。

在 `config/oasX.json` 里找到 `account_switch` 段，填入账号，格式为 `account_list_1`、`account_list_2` …：

```json
"account_switch": {
    "scheduler": { "enable": true, "priority": 15, "success_interval": "00 00:00:30" },
    "account_switch_config": {
        "switch_account_count": 10,
        "trigger_all_enabled_tasks": true,
        "current_index": 0
    },
    "account_list_1": { "character": "角色名1", "svr": "服务器", "account": "邮箱@163.com", "account_alias": "", "apple_or_android": true, "last_complete_time": "2023-01-01 00:00:00" },
    "account_list_2": { "character": "角色名2", "svr": "服务器", "account": "邮箱@163.com", "account_alias": "", "apple_or_android": false, "last_complete_time": "2023-01-01 00:00:00" }
}
```

账号字段说明（详见 [SwitchAccount 说明](../Component/SwitchAccount/README.md)）：

| 字段                   | 说明                                       |
| -------------------- | ---------------------------------------- |
| `character`          | 角色名（必须填，为空则视为无效账号）                       |
| `svr`                | 服务器名                                     |
| `account`            | 账号。邮箱直接填完整邮箱；手机号按游戏内显示填（如 `153****4444`） |
| `account_alias`      | OCR 识别别名，多个用 `#` 分隔，一般留空即可               |
| `apple_or_android`   | `true` = 安卓，`false` = 苹果。同一邮箱双角色必须成对区分   |
| `last_complete_time` | 上次完成时间，脚本自动维护，无需手动改                      |

### 2. 设置账号数量（switch_account_count）

告诉脚本一共要轮换几个号。填 25 就表示有 25 个账号。

脚本会在账号列表里取前 `switch_account_count` 个有效账号，按顺序循环切换。切到最后一个后回到第 1 个。

### 3. 设置切号间隔（success_interval）

- **默认 30 秒**：切完一个号，30 秒后（等其它任务跑完后）切下一个。
- 一轮切完（指针回到第 1 个号）后，任务会**等 1 天**再开始新一轮。

### 4. 启用要跑的任务

「账号切换」触发的是「当前配置里所有已启用的任务」，所以你需要把想跑的每个任务（悬赏封印、觉醒、结界突破等）在各自页面里**打开开关**。

## 字段说明

| 字段                           | 默认    | 说明                                 |
| ---------------------------- | ----- | ---------------------------------- |
| `scheduler.enable`           | false | 开关，启用后才会切号                         |
| `scheduler.priority`         | 15    | 优先级。数字越大越靠后执行（需调度规则为 Priority 才生效） |
| `scheduler.success_interval` | 30 秒  | 切完一个号到下一次切号的间隔                     |
| `switch_account_count`       | 1     | 要轮换的账号数量                           |
| `trigger_all_enabled_tasks`  | true  | 切号后是否触发所有已启用任务                     |
| `current_index`              | 0     | 当前切号指针，脚本自动维护，不要手动改                |

## 注意事项

1. 切号依赖「一键协战」的登录流程，仅支持**正式服**，渠道服不支持。
2. 同邮箱的安卓/苹果双角色，`apple_or_android` 必须正确区分，否则登录会点错平台按钮。
3. `current_index` 是脚本自动维护的进度，改乱了会导致切号顺序异常。
4. 切号失败同样计入当天缓存并推进指针，当天不会重试该号，避免每次都卡在同一个号上；第二天会自动重新切它。
5. `switch_date` 由脚本自动维护（账号卡里不显示）。想当天强制重切某个号，把它的 `switch_date` 改成空字符串即可。
