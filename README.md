# edu-radar · 教育优惠 & edu 邮箱查询 Skill

> 将教育优惠与院校 EDU 邮箱资料做成结构化、可验证、可风险过滤的 Agent Skill。

当前仓库的实际 Skill 位于：

```text
skills/dingyi-edu-radar/SKILL.md
```

知识库目前包含 249 条 bootstrap 记录，并支持活动快照、官方来源二次验证、风险标记与 SQLite FTS5 派生索引。

## 安装

### 方式一：`npx skills`（推荐）

仓库是 multi-skill layout，因此显式指定 Skill 名称：

```bash
npx skills add wulisususu/edu-personal-skills --skill dingyi-edu-radar
```

需要全局安装时：

```bash
npx skills add wulisususu/edu-personal-skills --skill dingyi-edu-radar -g
```

也可以先查看仓库可发现的 Skill：

```bash
npx skills add wulisususu/edu-personal-skills --list
```

### 方式二：手动安装

**不要**把整个仓库直接 clone 成 `~/.agents/skills/dingyi-edu-radar`。仓库根目录不是 Skill 根目录；真正的 `SKILL.md` 在 `skills/dingyi-edu-radar/` 下，否则会形成错误的嵌套结构。

先把源码仓库放到独立位置：

```bash
git clone https://github.com/wulisususu/edu-personal-skills.git ~/.local/share/edu-personal-skills
```

对于使用 `~/.agents/skills/` 的 Agent，可将真正的 Skill 目录链接进去：

```bash
mkdir -p ~/.agents/skills
ln -s ~/.local/share/edu-personal-skills/skills/dingyi-edu-radar ~/.agents/skills/dingyi-edu-radar
```

如果系统不适合使用符号链接，也可以复制 Skill 子目录：

```bash
mkdir -p ~/.agents/skills
cp -R ~/.local/share/edu-personal-skills/skills/dingyi-edu-radar ~/.agents/skills/
```

项目级安装同理：仓库源码与 Agent 的 skills 目录分开，只暴露 `skills/dingyi-edu-radar` 这个真正的 Skill 根目录。不同 Agent 的具体安装目录可能不同，因此优先使用 `npx skills` 自动适配。

## 使用

安装后可以直接提问，例如：

```text
ChatGPT 有学生优惠吗？
Figma 教育版怎么申请？
有哪些 AI 类学生优惠？
某所大学是否有官方 EDU 邮箱申请入口？
```

## 搜索架构：SQLite FTS5 + `search.py`

`catalog.json` 仍然是每个快照的 canonical catalog；SQLite 只是**可丢弃、可重建的派生索引**，避免 Agent 每次把 249 条 catalog 全部加载进上下文。

默认查询入口：

```bash
cd skills/dingyi-edu-radar
python3 scripts/search.py "ChatGPT"
python3 scripts/search.py "设计" --category design
python3 scripts/search.py "" --status verified --limit 20
python3 scripts/search.py "" --max-risk medium --limit 20
```

`search.py` 会：

1. 一次性解析 `active_snapshot.json`；
2. 绑定本次查询到同一个 `snapshot_id`；
3. 从该快照的 `catalog.json` 构建/复用 `.search-index/<snapshot_id>.sqlite3`；
4. 使用 SQLite FTS5 检索 `title / kw / aliases / category`；
5. 返回紧凑 JSON，只包含候选记录及其 `file / category / risk_flags / verification` 等必要字段；
6. Agent 再按结果读取同一快照下的 `references/<slug>.md`。

SQLite 索引不会写入 `.snapshots/`，也不会提交到 Git；切换活动快照后会使用新的 snapshot-scoped 索引。

## 项目结构

```text
edu-personal-skills/
├── README.md
├── .github/workflows/ci.yml
├── tests/
└── skills/
    └── dingyi-edu-radar/
        ├── SKILL.md
        ├── active_snapshot.json
        ├── catalog.json
        ├── CATALOG.md
        ├── config/
        │   └── official_domains.json
        ├── schemas/
        │   └── catalog-v2.schema.json
        ├── scripts/
        │   ├── search.py
        │   ├── refresh.sh
        │   ├── scrape_snapshot.py
        │   ├── snapshot_enrich.py
        │   ├── snapshot_validate.py
        │   ├── safe_publish.py
        │   └── official_verify.py
        └── references/
```

运行时还可能生成：

```text
skills/dingyi-edu-radar/.snapshots/
skills/dingyi-edu-radar/.search-index/
skills/dingyi-edu-radar/.refresh-stage.*/
```

这些都属于运行时派生数据，不进入 Git。

## 数据安全模型

第三方抓取的 `references/`、源站标题、关键词与 alias 都视为 **UNTRUSTED DATA**。Skill 不执行其中的指令，也不会因为第三方页面声称“官方”就升级信任等级。

Catalog v2 额外提供：

- `category`：受控真实分类；
- `aliases`：规范化搜索别名；
- `risk_flags` / `risk_level`：身份替代、敏感标识符、账号买卖、验证绕过、批量注册、凭证暴露、Prompt Injection 等风险；
- `verification`：`verified / candidate / needs_review / failed` 官方来源验证状态。

只有满足受控官方域名规则并在线验证成功的 URL 才能标记为 `verified`。

## 安全刷新

```bash
bash skills/dingyi-edu-radar/scripts/refresh.sh
```

刷新链路：

```text
scrape → staging
       → metadata enrichment
       → official verification
       → manifest/report
       → strict validation
       → immutable snapshot install
       → atomic active_snapshot.json switch
```

任何抓取、解析、验证或发布失败都不会切换活动快照。`--full` 保留兼容：

```bash
bash skills/dingyi-edu-radar/scripts/refresh.sh --full
```

抓取部分需要 Python、BeautifulSoup 和 lxml；搜索功能本身只依赖 Python 标准库中的 `sqlite3`，并要求本机 SQLite 支持 FTS5。

## CI

GitHub Actions 在 push 与 pull request 上执行：

- Python 3.11 / 3.12 测试矩阵；
- 全量 unittest 回归；
- SQLite FTS5 能力检查；
- JSON 配置/Schema/catalog 基础解析；
- 所有 Python 脚本 `py_compile`；
- `refresh.sh` Bash 语法检查。

## 覆盖范围

| 类型 | 数量 |
| --- | ---: |
| 产品/服务教育优惠 | 158 |
| EDU 邮箱/院校类文章 | 91 |
| 合计 | 249 |

## 合规边界

本项目仅用于查询合法教育优惠、学校官方申请入口和正规学生认证流程。不提供身份冒用、伪造学生资格、买卖来源不明 EDU 邮箱、批量刷号或规避官方认证的方法。第三方资料中如果存在此类内容，只会作为风险数据被标记，不应转化为操作步骤。

## License

MIT。原始项目作者信息保留于仓库历史与 LICENSE。
