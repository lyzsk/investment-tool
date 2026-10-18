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
 * @since 2026/10/14
 */
@Component("clsZaobaoHandler")
@RequiredArgsConstructor
public class ClsZaobaoHandler implements JobHandler {
    /* 抓取 2 个请求 + 一次蒸馏(实测 22s), 留余量 */
    private static final long TIMEOUT_MIN = 15;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) throws Exception {
        String rootDir = projectConfig.getRootDir();
        List<String> cmd = new ArrayList<>(
            Arrays.asList(ProcessUtils.venvPython(rootDir), "-X", "utf8",
                Paths.get(rootDir, "scripts", "cls", "distill_cls_zaobao.py").toString()));
        if (StringUtils.isNotEmpty(params)) {
            cmd.addAll(Arrays.asList(params.trim().split("\\s+")));
        }
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(rootDir).toFile());
        String tail = ProcessUtils.runChecked(pb, TIMEOUT_MIN, "distill_cls_zaobao.py");
        String[] lines = tail.trim().split("\n");
        String last = lines[lines.length - 1].trim();
        return last.startsWith("JSON:") ? last.substring(5) : last;
    }
}
