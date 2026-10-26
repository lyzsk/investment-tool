package cn.sichu.cls.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.ProcessUtils;
import utils.TradingDayUtils;

import java.nio.file.Paths;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * 夜间重算(零 token): 交易日 T 的 tzzb 账本 23:10 全部出齐后, T+1 凌晨把导师指纹 / 强势股次日 / 事件本体 / 样例库 / 规则体检 / 电报统计 /
 * 下一交易日信号参数和盘前名单等按依赖顺序重算一遍(scripts/md/nightly_recalc.py)
 * <p/>
 * 主任务 04:00 + 兜底 05:00 / 06:00 / 07:00 用同一个 handler: 脚本按状态文件只重跑失败 / 没跑完的步骤, 全部成功过就秒退
 *
 * @author sichu huang
 * @since 2026/10/25
 */
@Component("nightlyRecalcHandler")
@RequiredArgsConstructor
public class NightlyRecalcHandler implements JobHandler {
    /* 13 步串行实测合计约 40~60 分钟(电报统计 / 样例库最慢), 留余量 */
    private static final long TIMEOUT_MIN = 110;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) throws Exception {
        /* 1. 目标日 = 昨天; 昨天不是交易日(周末 / 节假日后的凌晨)直接跳过 */
        LocalDate target = LocalDate.now().minusDays(1);
        if (!TradingDayUtils.isTradingDay(target)) {
            return String.format("夜间重算: %s 不是交易日, 跳过", target);
        }
        /* 2. 调脚本(失败 / 超时抛异常, Quartz 记失败) */
        String rootDir = projectConfig.getRootDir();
        List<String> cmd = new ArrayList<>(
            Arrays.asList(ProcessUtils.venvPython(rootDir), "-X", "utf8",
                Paths.get(rootDir, "scripts", "md", "nightly_recalc.py").toString(), "--date", target.toString()));
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(rootDir).toFile());
        String tail = ProcessUtils.runChecked(pb, TIMEOUT_MIN, "nightly_recalc.py");
        /* 3. 只回末行 JSON 摘要, 每步明细在 results/_live/<下一交易日>/nightly_status.json */
        String[] lines = tail.trim().split("\n");
        String last = lines[lines.length - 1].trim();
        return last.startsWith("JSON:") ? last.substring(5) : last;
    }
}
