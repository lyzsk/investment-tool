package cn.sichu.system.config;

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
    /* 项目根目录 */
    private String rootDir;
    /* 文件上传配置 */
    // private FileUpload fileUpload = new FileUpload();
    /* 文件下载配置 */
    // private FileDownload fileDownload = new FileDownload();
    private File file = new File();
    /* markdown 配置 */
    private Markdown markdown = new Markdown();

    @Getter
    @Setter
    public static class Markdown {
        private String rootDir;
        private String templatePath;
    }

    @Getter
    @Setter
    public static class File {
        private Upload upload = new Upload();
        private Download download = new Download();
        private Result result = new Result();

        @Getter
        @Setter
        public static class Upload {
            private String rootDir;
            private String maxSize;
            private List<String> allowedTypes;
        }

        @Getter
        @Setter
        public static class Download {
            private String rootDir;
        }

        @Getter
        @Setter
        public static class Result {
            private String rootDir;
        }
    }
}
