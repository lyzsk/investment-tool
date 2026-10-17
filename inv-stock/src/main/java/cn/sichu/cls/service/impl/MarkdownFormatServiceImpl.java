package cn.sichu.cls.service.impl;

import cn.sichu.cls.service.IMarkdownFormatService;
import cn.sichu.system.config.ProjectConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import utils.ProcessUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * @author sichu huang
 * @since 2026/01/16 16:30
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MarkdownFormatServiceImpl implements IMarkdownFormatService {
    private static final String NODE_SCRIPT_PATH = "scripts/md/format-markdown.mjs";
    private final ProjectConfig projectConfig;

    @Override
    public boolean formatMarkdownFile(Path markdownFile) {
        try {
            Path projectRoot = Paths.get(projectConfig.getRootDir());
            Path scriptPath = projectRoot.resolve(NODE_SCRIPT_PATH);

            if (!Files.exists(scriptPath)) {
                log.error("Node.js 格式化脚本不存在: {}", scriptPath);
                return false;
            }
            if (!Files.exists(markdownFile)) {
                log.error("Markdown 文件不存在: {}", markdownFile);
                return false;
            }

            ProcessBuilder pb = new ProcessBuilder("node", scriptPath.toString(),
                markdownFile.toAbsolutePath().toString());
            pb.directory(projectRoot.toFile());
            /* 健壮性 H6: 改用 ProcessUtils.run(合并 stderr、独立线程读、超时真生效); 原先先读 stdout 到 EOF 再读 stderr 再 waitFor,
               子进程卡住或 stderr 写满缓冲都会让定时线程永久挂起 */
            ProcessUtils.Result res = ProcessUtils.run(pb, 1);
            for (String line : res.tail().split("\n")) {
                if (!line.isBlank()) {
                    log.info("[Node Format OUT] {}", line);
                }
            }
            if (res.timedOut()) {
                log.error("Node.js 脚本执行超时(1min, 进程树已杀)");
                return false;
            }

            int exitCode = res.exit();
            if (exitCode == 0) {
                log.info("✅ Markdown 文件格式化成功: {}", markdownFile);
                return true;
            } else {
                log.error("❌ Node.js 脚本执行失败，退出码: {}", exitCode);
                return false;
            }

        } catch (Exception e) {
            log.error("调用 Node.js 格式化脚本异常: {}", markdownFile, e);
            if (e instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            return false;
        }
    }
}
