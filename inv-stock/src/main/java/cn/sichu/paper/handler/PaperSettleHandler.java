package cn.sichu.paper.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.ProcessUtils;
import utils.StringUtils;
import utils.TradingDayUtils;

import java.nio.file.Paths;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * paper 决策结算+反思(收盘后 15:50): decisions/<skill>.jsonl 的 T+1/T+3 机械结算(零 token, 依赖 15:35 收盘采集)
 * + 白名单 skill 的反思(chain_flags CHAIN_REFLECTION_SKILLS, 当前仅 control); 幂等, 漏跑的天下次自动补
 *
 * @author sichu huang
 * @since 2026/10/14
 */
@Component("paperSettleHandler")
@RequiredArgsConstructor
public class PaperSettleHandler implements JobHandler {
    /* 结算秒级; 反思每 skill 一次 claude -p(约 20~60s), 上限 6 次调用, 留余量 */
    private static final long TIMEOUT_MIN = 20;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) throws Exception {
        LocalDate today = LocalDate.now();
        if (!TradingDayUtils.isTradingDay(today)) {
            return "非交易日跳过 " + today;
        }
        String rootDir = projectConfig.getRootDir();
        List<String> cmd = new ArrayList<>(
            Arrays.asList(ProcessUtils.venvPython(rootDir), "-X", "utf8",
                Paths.get(rootDir, "scripts", "dfcf", "paper", "settle_decisions.py").toString()));
        /* param 可填 --reflect off(只结算不反思) / --date yyyy-MM-dd(补某天) */
        if (StringUtils.isNotEmpty(params)) {
            cmd.addAll(Arrays.asList(params.trim().split("\\s+")));
        }
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(rootDir).toFile());
        ProcessUtils.Result res = ProcessUtils.run(pb, TIMEOUT_MIN);
        String tail = res.tail().trim();
        if (res.timedOut()) {
            throw new BusinessException(
                "settle_decisions.py 超时 " + TIMEOUT_MIN + "min(进程树已杀)");
        }
        /* exit 1 = 反思调用失败, 但结算已落盘; 其余非 0 = 用法/锁错误 */
        if (res.exit() != 0) {
            throw new BusinessException(
                "settle_decisions.py 失败 exit=" + res.exit() + ", 输出尾部: " + tail);
        }
        /* 只回最后两行摘要(结算 N 个窗口 / 反思 N 条) */
        String[] lines = tail.split("\n");
        return lines.length >= 2 ?
            lines[lines.length - 2].trim() + " | " + lines[lines.length - 1].trim() : tail;
    }
}
