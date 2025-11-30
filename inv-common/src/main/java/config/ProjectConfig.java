package config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * @author sichu huang
 * @since 2025/11/30 07:39
 */
@Component
@ConfigurationProperties(prefix = "project")
@Getter
@Setter
public class ProjectConfig {
    /* 项目名称 */
    private String name;

    /* 版本 */
    private String version;

    /* 文件上传配置 */
    private FileUpload file = new FileUpload();

    @Getter
    @Setter
    public static class FileUpload {
        private String rootDir = System.getProperty("user.home") + "/dev/investment-tool/uploads";
        private String maxSize = "10MB";
        private List<String> allowedTypes = List.of("image/jpeg", "image/jpg", "image/png");
    }
}
