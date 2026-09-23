# k3-inv × Quartz 工程落地指南（手写代码用)

> 目标读者： 你自己手写。我只讲**建什么、为什么这么建、代码长什么样、怎么接线、怎么验证**。
> 前提： 回测已验证(k3-v0.1: -0.70% vs 上证 -1.71%; 桃哥 pilot-2week: +6.39%), 现在把"数据层+调度层"先落地， AI 裁决层仍在 Claude/hermes 侧。

---

## 0. 全局图： 哪些该进 Java, 哪些不该

```
财联社API ──> cls_telegraph (已有 clsRedTelegraphHandler, 每30秒)
                │
                ▼
        k3inv_signal  ←── 信号蒸馏(AI读电报→结构化信号)  ★ Claude/hermes 做, Java 只存
                │
                ▼
        k3inv_watch   ←── 质量筛+威科夫状态             ★ Claude/hermes 做, Java 只存
                │
                ▼
   k3inv_strategy/run/decision/trade  ←── 回测与(未来)模拟盘结果落库  ★ 结算脚本/Claude 产出, Java 只存+查
```

**原则： Java 后端 = 存储 + 调度 + 查询； AI 判断不进 Java。** 原因： 信号蒸馏/威科夫识别/仲裁是 LLM 活， 硬编码进 Java 既写不出来也失去 walk-forward 的灵活性。Java 要做的是让这些数据**有表可存、有定时任务可驱动、有接口可查**。

桃哥管线同理： 转写/纠错/注入是 node+python 脚本， Java 侧只需要一个 handler 用 `ProcessBuilder` 调脚本(项目里已有先例： `MarkdownFormatServiceImpl` 调 `node scripts/format-markdown.mjs`)。

---

## 1. 建表(sql/k3inv.sql 已写好， 直接执行)

```bash
mysql -uroot -proot investment_tool < sql/k3inv.sql
```

6 张表分三组， 设计意图：

### 1.1 信息层(防未来函数是第一设计目标)
- **`k3inv_signal`** — 电报催化信号。核心列： `signal_time`(电报发布时间， **信息可用性以它为界**)、`cls_id`(溯源 cls_telegraph)、`signal_type`(auction/sector_move/policy/overnight/review — 回测证明 overnight 类最有效， 必须可分类统计)、`strength`(AI 评分 1-5)。索引 `(signal_date, signal_time)` 是为了"取 T 日 T 时刻之前的所有信号"这个回测核心查询。
- **`k3inv_watch`** — 信号→个股观察名单。`quality_pass`+`quality_reason` 是李大霄筛的留痕(为什么这只票能买/不能买， 复盘时必须能回答); `wyckoff_phase` 是结构状态； `watch_state`(open/triggered/expired) 让观察名单有生命周期， 不会越积越多。

### 1.2 回测四件套(版本可追溯)
- **`k3inv_strategy`** — 策略版本注册。`strategy_code`(如 k3-v0.1) 唯一键 + `spec_text`(STRATEGY.md 全文) + `params`(单票3成/总仓6成/-4%止损... 存 JSON)。**为什么存全文**: 回测结果脱离策略文本就没有意义， 三个月后你必须能回答"这个 -0.70% 是按哪版规则跑的"。
- **`k3inv_run`** — 一次回测/模拟盘/实盘的总账。`run_type` 区分 backtest/paper/live, 同一套表服务三个阶段。
- **`k3inv_decision`** — 每一次买/卖/hold/watch 的决策留痕。**`info_cutoff` 是灵魂**: 记录"做这个决策时我只允许看到哪个时刻之前的信息", 这是防未来函数的证据链， 与桃哥规则的 `learned_before` 同一思想。
- **`k3inv_trade`** — 成交流水(买卖价/量/盈亏), 从 decision 中 buy→sell 配对产生。

### 1.3 为什么全部继承 BaseEntity 10 列
项目所有表统一 `status/create_by/create_time/update_by/update_time/is_deleted/delete_by/delete_time/remark`, `MyMetaObjectHandler` 自动填充(userId 硬编码 1L), 逻辑删除走 `is_deleted`。新表照抄 = 白嫖自动填充+统一查询条件， 不要搞特殊。

> taoge.sql 的 9 张表(视频/转写/解读/规则等)同理已存在, 实体还没写 — 等 k3inv 这套走完一遍流程后照葫芦画瓢。

---

## 2. Java 代码清单(模仿 cn.sichu.cls 域， 放 inv-stock 模块)

新建包 `cn.sichu.k3inv`, 文件树(×6 实体， 套路完全一致):

```
inv-stock/src/main/java/cn/sichu/k3inv/
├── entity/     K3invSignal.java K3invWatch.java K3invStrategy.java K3invRun.java K3invDecision.java K3invTrade.java
├── mapper/     K3invSignalMapper.java ... (×6)
├── service/    IK3invSignalService.java ... (×6)
├── service/impl/ K3invSignalServiceImpl.java ... (×6)
└── handler/    K3invDailyReportHandler.java  (第3节细讲)
```

### 2.1 完整范例： K3invSignal(其余 5 个照抄改字段)

**entity** — 注意三个项目惯例： `@Data`+`@EqualsAndHashCode(callSuper=true)`、每列 `@TableField`、JSON 列用 `JacksonTypeHandler`:

```java
package cn.sichu.k3inv.entity;

import base.BaseEntity;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * @author sichu huang
 * @since 2026/09/19 17:30
 */
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("k3inv_signal")
public class K3invSignal extends BaseEntity {

    @TableField("signal_date")
    private LocalDate signalDate;

    @TableField("signal_time")
    private LocalDateTime signalTime;

    @TableField("cls_id")
    private Long clsId;

    @TableField("sector")
    private String sector;

    /** 点名个股 [{code,name}] — json 列, 照抄 ClsTelegraph.images 的写法 */
    @TableField(value = "stocks", typeHandler = JacksonTypeHandler.class)
    private List<Map<String, String>> stocks;

    @TableField("direction")
    private String direction;

    @TableField("signal_type")
    private String signalType;

    @TableField("summary")
    private String summary;

    @TableField("strength")
    private Integer strength;
}
```

**mapper** — 大多数表空接口即可(BaseMapper 已带全部 CRUD), 只有自定义查询才加方法:

```java
package cn.sichu.k3inv.mapper;

import cn.sichu.k3inv.entity.K3invSignal;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author sichu huang
 * @since 2026/09/19 17:31
 */
@Mapper
public interface K3invSignalMapper extends BaseMapper<K3invSignal> {
}
```

**service 接口** — 继承 `IService<T>` 白嫖 CRUD, 只声明业务方法:

```java
package cn.sichu.k3inv.service;

import cn.sichu.k3inv.entity.K3invSignal;
import com.baomidou.mybatisplus.extension.service.IService;

import java.time.LocalDateTime;
import java.util.List;

/**
 * @author sichu huang
 * @since 2026/09/19 17:32
 */
public interface IK3invSignalService extends IService<K3invSignal> {

    /**
     * 查某时刻之前的全部信号(回测 walk-forward 核心查询: info_cutoff 的物理实现)
     *
     * @param cutoff LocalDateTime
     * @return java.util.List<cn.sichu.k3inv.entity.K3invSignal>
     * @author sichu huang
     * @since 2026/09/19 17:32:00
     */
    List<K3invSignal> listBefore(LocalDateTime cutoff);
}
```

**impl** — 惯例： `@Service`+`@RequiredArgsConstructor`+`@Slf4j`, 继承 `ServiceImpl<Mapper, Entity>`, 查询用 `LambdaQueryWrapper`(类型安全， 字段改名编译期报错):

```java
package cn.sichu.k3inv.service.impl;

import cn.sichu.k3inv.entity.K3invSignal;
import cn.sichu.k3inv.mapper.K3invSignalMapper;
import cn.sichu.k3inv.service.IK3invSignalService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * @author sichu huang
 * @since 2026/09/19 17:33
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class K3invSignalServiceImpl extends ServiceImpl<K3invSignalMapper, K3invSignal>
    implements IK3invSignalService {

    @Override
    public List<K3invSignal> listBefore(LocalDateTime cutoff) {
        return list(new LambdaQueryWrapper<K3invSignal>()
            .le(K3invSignal::getSignalTime, cutoff)
            .orderByAsc(K3invSignal::getSignalTime));
    }
}
```

其余 5 个实体照此复制。只有这些差异：
- `K3invStrategy.specText` → `@TableField("spec_text") private String specText;`(text 列无需 TypeHandler); `params` json → `Map<String, Object>` + JacksonTypeHandler
- `K3invRun.report` → longtext, String
- `K3invDecision.infoCutoff` → `LocalDateTime`, **非空**, 它是防未来函数证据
- `K3invTrade.pnl/pnlRatio` → `BigDecimal`(decimal 列不要用 double, 金额精度问题)

**为什么不用写 XML**: MyBatis-Plus 的 BaseMapper + LambdaQueryWrapper 覆盖 90% 查询； `ClsTelegraphMapper.selectRedTelegraphs` 那种才需要 XML(多条件区间查询)。你先不写 XML, 遇到再补。

---

## 3. Quartz 接线(本项目的调度是 DB 驱动， 不是 @Scheduled)

### 3.1 机制(为什么是这样)

```
sys_job 表(DB)  ──启动时──>  JobInitializationRunner 逐行注册到 Quartz Scheduler
     │                            (JDBC JobStore, 集群安全)
     ▼
cron 触发 ──> JobHandlerInvoker (QuartzJobBean, @DisallowConcurrentExecution)
                  │ 1. 按 job_handler_name 从 Spring 容器 getBean
                  │ 2. 调 handler.execute(param)
                  │ 3. 异步写 sys_job_log(入参/返回值/异常/耗时)
                  ▼
            你的 Handler Bean
```

**为什么 DB 驱动而不是 `@Scheduled`**:
1. **可暂停/改 cron 不用改代码重启** — `sys_job.status=1` 即暂停(status 注释： 0-运行 1-暂停), 交易日历调整时你会频繁用到；
2. **每次执行有 sys_job_log** — 调度可追溯， "今天电报抓没抓"查表就知道；
3. **JDBC JobStore 集群安全** + `@DisallowConcurrentExecution` 防止上一次没跑完下一次又触发(抓数据任务必须串行);
4. `misfire_policy`(默认2=放弃执行): 机器关机错过 09:00 的任务， 开机后**不补跑** — 对行情任务这是对的(补跑抓的是过期数据), 如果你想补跑改 0/1。

### 3.2 你要写的 Handler(第一个， 完整可抄)

以"每日收盘后生成 k3 信号日报"为例 — 它查当天所有 signal + watch, 汇总写日志(未来可扩展成写 md/推送)。这是最小可验证单元：

```java
package cn.sichu.k3inv.handler;

import cn.sichu.k3inv.entity.K3invSignal;
import cn.sichu.k3inv.entity.K3invWatch;
import cn.sichu.k3inv.service.IK3invSignalService;
import cn.sichu.k3inv.service.IK3invWatchService;
import cn.sichu.system.quartz.handler.JobHandler;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.List;

/**
 * @author sichu huang
 * @since 2026/09/19 17:40
 */
@Component("k3invDailyReportHandler")   // ← Bean 名 = sys_job.job_handler_name, 必须显式命名
@RequiredArgsConstructor
@Slf4j
public class K3invDailyReportHandler implements JobHandler {
    private final IK3invSignalService signalService;
    private final IK3invWatchService watchService;

    @Override
    public String execute(String params) {
        LocalDate today = LocalDate.now();   // 严谨版: 用 TradingDayUtils 对齐交易日, 照抄 ClsRedTelegraphHandler
        List<K3invSignal> signals = signalService.list(
            new LambdaQueryWrapper<K3invSignal>().eq(K3invSignal::getSignalDate, today));
        List<K3invWatch> watches = watchService.list(
            new LambdaQueryWrapper<K3invWatch>().eq(K3invWatch::getWatchDate, today));
        long triggered = watches.stream().filter(w -> "triggered".equals(w.getWatchState())).count();
        log.info("k3 日报 {}: 信号 {} 条, 观察 {} 只, 触发 {} 只", today, signals.size(), watches.size(), triggered);
        return String.format("k3日报 %s: 信号%d 观察%d 触发%d", today, signals.size(), watches.size(), triggered);
        // 返回值会写进 sys_job_log — 一定要返回可读摘要, 别返回 null
    }
}
```

要点：
- `@Component("k3invDailyReportHandler")` **显式命名** — JobHandlerInvoker 按这个名字 getBean, 不命名就用类名首字母小写， 显式命名防重构改名翻车；
- `execute` 返回 String — 进 sys_job_log, 是你唯一的执行回执；
- 抛异常也会被记进 log(参考 ClsRedTelegraphHandler 抛 BusinessException), 任务失败不用自己 try-catch 吞掉。

### 3.3 注册进调度(插 sys_job 行)

```sql
INSERT INTO sys_job (job_name, job_group, job_handler_name, job_handler_param,
                     cron_expression, misfire_policy, status, remark)
VALUES ('k3信号日报', 'k3inv', 'k3invDailyReportHandler', NULL,
        '0 30 15 ? * MON-FRI', 2, 0, '每交易日15:30汇总当日信号与观察名单');
```

- `status=0` 是**运行**(注释反人类： 0-运行 1-暂停， 插错任务永远不触发);
- cron 是 Quartz 格式(6/7 段， 秒在前): `0 30 15 ? * MON-FRI` = 周一到周五 15:30:00; 节假日不触发没关系， handler 查到空数据正常返回即可(桃哥管线的 TradingDayUtils.isTradingDay 可以在 handler 内部再过滤);
- 改完重启应用生效(JobInitializationRunner 是启动时读的)。

### 3.4 桃哥管线的每日自动化(同一个套路)

转写是 python/node 脚本， Java handler 用 ProcessBuilder 调 — **照抄 `MarkdownFormatServiceImpl` 里调 `node scripts/format-markdown.mjs` 的写法**, 把命令换成:

```
# 伪流程(一个 handler 串起来, 或拆成多个 handler 用不同 cron 串)
node scripts/bilibili-taoge/fetch_taoge.mjs          # 有新视频?
#   → 下音频 + venv python transcribe.py             # ASR
#   → venv python correct_names.py                   # 纠错
#   → node inject_md.mjs --dir ...                   # 注入 md
```

建议**拆成两个 handler**: `taogeFetchHandler`(每 30 分钟探测有无新视频， 轻量) + `taogePipelineHandler`(有新产品时才跑重活, 或晚间 21:00/23:00 各跑一次兜底)。原因： 重任务挂在轻探测的 cron 上会拖累调度线程， 且失败重试粒度太粗。

---

## 4. 实施顺序(每步都可独立验证， 不要一次全写)

| 步 | 动作 | 验证 |
|---|---|---|
| 1 | 执行 sql/k3inv.sql | `show tables like 'k3inv%';` 6 张表 |
| 2 | 只写 K3invSignal 四层(entity/mapper/service/impl) | 启动不报错； 写个 ClsTelegraphServiceImplTest 那样的测试插一条查一条 |
| 3 | 用 SQL 手工 INSERT 几条 signal(把回测的 9/04 存储催化、9/01 银行报道录进去) | `select * from k3inv_signal;` |
| 4 | 写 K3invDailyReportHandler + 插 sys_job 行(cron 先设成 2 分钟后触发做实验) | 到点看 sys_job_log 有记录， 返回值正确 |
| 5 | 把 cron 改成正式的 15:30, 补其余 5 个实体的四层 | 同上 |
| 6 | 把 settle_k3_v01.mjs 的结算结果 INSERT 进 strategy/run/decision/trade(先手工 SQL, 让历史回测有档可查) | 按 run_code 能 join 出完整决策链 |
| 7 | (后续) taoge 两个 handler | sys_job_log |

## 5. 常见坑(这个项目里实测过的)

1. **status 0/1 反直觉**: sys_job 0=运行 1=暂停; 业务表的 status 0=成功 1=失败。两个体系别混。
2. **json 列必须加 JacksonTypeHandler**, 否则插入报错或读出 String; 且实体字段类型用 `List<Map<String,String>>`/`Map<String,Object>`, 不要用 String。
3. **datetime(6) 对应 LocalDateTime**, date 对应 LocalDate; 不要用 java.util.Date。
4. **金额用 BigDecimal**(decimal 列), 收益率也用 BigDecimal; double 会在 0.1+0.2 上咬你。
5. Handler 里要做重活(调脚本/网络)注意 Quartz 线程被占 — 项目现状是单调度线程也够， 但重活任务之间 cron 错开几分钟。
6. **MyMetaObjectHandler userId 硬编码 1L** — create_by/update_by 都会是 1, 不是 bug 是项目现状。
7. 新增 handler 忘了插 sys_job 行 = 永远不会触发(没有任何报错), 排查先看 sys_job 再看 sys_job_log。

---

*相关文件： sql/k3inv.sql(建表), scripts/k3-inv/STRATEGY.md(策略规格), scripts/k3-inv/backtest/runs/k3-v0.1-20260901_0918/(回测结果), 参考实现 cn.sichu.cls.* 全域。*
