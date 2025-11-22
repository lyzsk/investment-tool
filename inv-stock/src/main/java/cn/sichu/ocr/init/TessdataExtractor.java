package cn.sichu.ocr.init;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/**
 * @author sichu huang
 * @since 2025/11/23 06:00
 */
@Component
@Slf4j
public class TessdataExtractor {
    private Path tempTessdataDir;

    public String getTessdataPath() {
        return tempTessdataDir.toString();
    }

    @PostConstruct
    public void init() throws IOException {
        /* 创建临时目录 */
        tempTessdataDir = Files.createTempDirectory("tessdata-");
        /* JVM 退出时删除 */
        tempTessdataDir.toFile().deleteOnExit();
        /* 从 classpath 复制 traineddata 文件 */
        copyFromClasspath("tessdata/chi_sim.traineddata", "chi_sim.traineddata");
        log.info("Tessdata extracted to: {}", tempTessdataDir);
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
