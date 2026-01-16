package cn.sichu.cls.service.impl;

import cn.sichu.cls.service.IMarkdownFormatService;
import config.ProjectConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.TimeUnit;

/**
 * @author sichu huang
 * @since 2026/01/16 16:30
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MarkdownFormatServiceImpl implements IMarkdownFormatService {
    private static final String NODE_SCRIPT_PATH = "scripts/format-markdown.mjs";
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
            Process process = pb.start();

            try (BufferedReader stdout = new BufferedReader(
                new InputStreamReader(process.getInputStream()))) {
                String line;
                while ((line = stdout.readLine()) != null) {
                    log.info("[Node Format OUT] {}", line);
                }
            }

            try (BufferedReader stderr = new BufferedReader(
                new InputStreamReader(process.getErrorStream()))) {
                String line;
                while ((line = stderr.readLine()) != null) {
                    log.error("[Node Format ERR] {}", line);
                }
            }

            boolean finished = process.waitFor(10, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                log.error("Node.js 脚本执行超时");
                return false;
            }

            int exitCode = process.exitValue();
            if (exitCode == 0) {
                log.info("✅ Markdown 文件格式化成功: {}", markdownFile);
                return true;
            } else {
                log.error("❌ Node.js 脚本执行失败，退出码: {}", exitCode);
                return false;
            }

        } catch (IOException | InterruptedException e) {
            log.error("调用 Node.js 格式化脚本异常: {}", markdownFile, e);
            Thread.currentThread().interrupt();
            return false;
        }
    }
}
