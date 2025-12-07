package cn.sichu.ocr.init;

import config.ProjectConfig;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;

/**
 * @author sichu huang
 * @since 2025/11/23 06:00
 */
@Component
@Slf4j
public class TessdataExtractor {

    private final Path tempTessdataDir;

    @Autowired
    public TessdataExtractor(ProjectConfig projectConfig) throws IOException {
        String projectName = projectConfig.getName();
        if (projectName == null || projectName.trim().isEmpty()) {
            throw new IllegalArgumentException("project.name 未配置");
        }
        /* 创建基于项目名称的临时目录路径 */
        this.tempTessdataDir =
            Paths.get(System.getProperty("java.io.tmpdir"), "tessdata-" + projectName);
        init();
    }

    public String getTessdataPath() {
        return tempTessdataDir.toString();
    }

    /**
     * update: 2025/12/07 20:35:49 deleteOnExit() 只在 JVM 正常退出时生效(如 main 方法结束, System.exit()), 而IDEA点击STOP实际是发送 SIGKILL, 不会触发 shutdown hooks 会导致 deleteOnExit() 失效
     * <br/>
     * 使用固定路径 + 启动时自动清理旧目录
     *
     * @author sichu huang
     * @since 2025/12/07 18:01:08
     */
    private void init() throws IOException {
        /* 删除旧的目录 */
        if (Files.exists(tempTessdataDir)) {
            deleteDirectoryRecursively(tempTessdataDir);
        }
        /* 创建新的目录 */
        Files.createDirectories(tempTessdataDir);
        /* 从 classpath 复制 tessdata 目录 */
        copyFromClasspath("tessdata/chi_sim.traineddata", "chi_sim.traineddata");
        log.info("提取 Tessdata 到: {}", tempTessdataDir);
    }

    private void deleteDirectoryRecursively(Path path) throws IOException {
        Files.walkFileTree(path, new SimpleFileVisitor<Path>() {
            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs)
                throws IOException {
                Files.delete(file);
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult postVisitDirectory(Path dir, IOException exc)
                throws IOException {
                if (exc == null) {
                    Files.delete(dir);
                    return FileVisitResult.CONTINUE;
                } else {
                    throw exc;
                }
            }
        });
    }

    private void copyFromClasspath(String resourcePath, String targetFileName) throws IOException {
        try (InputStream is = getClass().getClassLoader().getResourceAsStream(resourcePath)) {
            if (is == null) {
                throw new RuntimeException("Resource not found: " + resourcePath);
            }
            Path target = tempTessdataDir.resolve(targetFileName);
            Files.copy(is, target, StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
