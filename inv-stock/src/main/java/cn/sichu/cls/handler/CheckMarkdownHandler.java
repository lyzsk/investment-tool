package cn.sichu.cls.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.ProcessUtils;
import utils.StringUtils;

import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 *
 * @author sichu huang
 * @since 2026/10/13
 */
@Component("checkMarkdownHandler")
@RequiredArgsConstructor
public class CheckMarkdownHandler implements JobHandler {
    /* 一轮最长: 上一交易日遗留 + 当天(三 UP sum+distill / tzzb 推测层 / tzzb distill)串行, 预估 1~2.5h, 留余量 */
    /* 10/17 晚 审计② Q-5/S8: 240→120——每小时一轮且有全局锁, 卡一次原来会连堵 4 轮(含 22:30/23:40 的 07 轮); 实测最长 47 分钟 */
    private static final long TIMEOUT_MIN = 120;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) throws Exception {
        String rootDir = projectConfig.getRootDir();
        List<String> cmd = new ArrayList<>(
            Arrays.asList(ProcessUtils.venvPython(rootDir), "-X", "utf8",
                Paths.get(rootDir, "scripts", "md", "check_md_daily.py").toString()));
        if (StringUtils.isNotEmpty(params)) {
            cmd.addAll(Arrays.asList(params.trim().split("\\s+")));
        }
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(rootDir).toFile());
        String tail = ProcessUtils.runChecked(pb, TIMEOUT_MIN, "check_md_daily.py");
        /* 只回末行 JSON 摘要(各步 完成/未就绪/跳过), 完整过程在 scripts/md/logs/check_md_<日期>.log */
        String[] lines = tail.trim().split("\n");
        String last = lines[lines.length - 1].trim();
        return last.startsWith("JSON:") ? last.substring(5) : last;
    }
}
