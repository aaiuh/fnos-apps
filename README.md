# aaiuh 飞牛应用集合源

飞牛 fnOS 第三方应用集合。**免费开源，跟随各应用上游更新。**

## 怎么用

在飞牛「应用中心 → FnDepot → 源管理 → 添加源」里填**仓库地址**：

```
https://github.com/aaiuh/fnos-apps
```

FnDepot 会自动找仓库根目录的 `fnpack.json`。取不到时改用完整文件地址：

```
https://raw.githubusercontent.com/aaiuh/fnos-apps/main/fnpack.json
```

## 现有应用

| 应用 | 说明 | 最新版本 | 分类 |
|---|---|---|---|
| DeepSeek Harness | DeepSeek AI 开源的插件化智能体框架（命令行 dsh）。 | 0.2.1-5 | AI赋能 |
| fnMusic 音源扩展 | 飞牛音乐第三方音源扩展：零侵入接管官方音乐入口，提供 musicdl 聚合、网易云、洛雪自定义源在线搜索… | 2.10.2 | 影音娱乐 |
| Hindsight 记忆库 | Agent 长期记忆系统，原生运行于飞牛 fnOS，不依赖 Docker。 | 1.1.0 | AI赋能 |
| Octop | 腾讯开源的多用户多智能体 AI 助手平台，支持 Web 控制台、CLI、IM 渠道与定时任务， | 1.0.3b1 | AI赋能 |
| Wild Work | wild-work 账号池代理（自封装版）。提供 OpenAI 兼容 API（/v1）与内置 Web 控… | 2.9.6-1 | AI赋能 |

共 **5** 个应用。本表由 CI 从 `fnpack.json` 自动生成，**请勿手改**。

## 这是怎么工作的

```
apps.txt              成员清单，每行一个仓库
build/merge.py        抓各仓库的 fnpack.json，合并成一个索引
fnpack.json           自动生成的集合索引（不要手改）
```

CI 每 6 小时跑一次，也支持手动触发。它做的事：

1. 遍历 `apps.txt`，读取每个仓库根目录的 `fnpack.json`
2. 合并各自的应用条目
3. 把 `./xxx` 这类相对路径改写成指向**该应用仓库**的绝对地址
   （不改写的话图标和说明会按索引仓库去取，全部 404）
4. 对每个安装包做一次 HEAD 可达性检查，取不到就丢弃该版本
5. 重新计算 sha256 与体积，以实测值为准（与声明不符会告警）
6. 提交更新后的 `fnpack.json`

所以：**应用元数据由各应用仓库自己维护**，本仓库只负责汇总与校验。

## 加一个新应用

1. 该应用有自己的 GitHub 仓库，根目录有 `fnpack.json`（可只含自己的应用）
2. 该应用的 Release 里有 `.fpk` 安装包
3. 在 `apps.txt` 里加一行 `owner/repo`，提交

CI 跑完索引就更新了，不需要改本仓库的其他文件。

## 与单个应用源的关系

每个应用仓库自己的 `fnpack.json` 也仍然是一个合法的独立源，可以单独添加。
但**建议只加这个集合源** —— 同时加两个会让 FnDepot 提示「外部源内容重叠」。

## 示例

`apps.txt`：

```
aaiuh/hindsight-fnos
```

## 授权

本仓库的索引脚本以 MIT 发布。各应用本身的许可见其各自仓库。
