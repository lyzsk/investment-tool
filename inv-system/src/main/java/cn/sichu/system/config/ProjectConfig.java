package cn.sichu.system.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
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
    /* 行情库采集配置 */
    private Market market = new Market();

    private Notify notify = new Notify();

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

    @Getter
    @Setter
    public static class Market {
        private String outputDir;
        private long collectTimeoutMin = 30;
        /* 补采往日日线(腾讯逐只, 约 8000 次请求)超时 */
        private long catchUpTimeoutMin = 180;
        /* 对账起始日: 行情库上线日, 更早的日子归历史回补管, 对账不碰 */
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE)
        private LocalDate reconcileStartDate = LocalDate.of(2026, 10, 9);
        /* 开盘竞价采集上线日: 此后缺竞价才记 UNRECOVERABLE */
        @DateTimeFormat(iso = DateTimeFormat.ISO.DATE)
        private LocalDate auctionStartDate = LocalDate.of(2026, 10, 13);
        /* 对账回看交易日数 */
        private int reconcileLookbackDays = 10;
        /* 应用启动后延迟几分钟自动对账一次(停机/断电期间错过的收盘采集自动补), 0=不自动 */
        private int reconcileOnStartupDelayMin = 3;
    }

    @Getter
    @Setter
    public static class Notify {
        /* hermes 可执行文件(微信推送: hermes send --to weixin), 为空=只打日志不推送 */
        private String hermesExe;
        private String hermesTo = "weixin";
    }
}
