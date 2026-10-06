package cn.sichu.bilibili.handler;

import cn.sichu.bilibili.entity.BilibiliVideo;
import cn.sichu.bilibili.service.IBilibiliVideoService;
import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/09/27 00:16
 */

@Component("bilibiliVideoHandler")
@RequiredArgsConstructor
public class BilibiliVideoHandler implements JobHandler {
    private static final ObjectMapper OM = new ObjectMapper();
    private static final long TIMEOUT_MIN = 3;
    private final IBilibiliVideoService bilibiliVideoService;
    private final ProjectConfig projectConfig;

    @Override
    public String execute(String params) {
        Path script =
            Paths.get(projectConfig.getRootDir(), "scripts", "fetch_bilibili.mjs");
        /* 多UP化: job 的 job_handler_param 透传给脚本(如 "--mid 550494308 --name 卢本圆复盘"),
           桃哥 job param 为空=默认(向后兼容); 脚本侧 --mid/--name 决定发现目标 */
        java.util.List<String> cmd = new java.util.ArrayList<>();
        cmd.add("node"); cmd.add(script.toString()); cmd.add("--list");
        if (params != null && !params.isBlank()) {
            cmd.addAll(java.util.Arrays.asList(params.trim().split("\\s+")));
        }
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        pb.redirectErrorStream(true);
        String jsonLine = null;
        int exit;
        StringBuilder tail = new StringBuilder();
        try {
            Process proc = pb.start();
            try (BufferedReader br = new BufferedReader(
                new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    if (line.startsWith("JSON:")) {
                        jsonLine = line.substring(5);
                    }
                    tail.append(line).append('\n');
                    if (tail.length() > 4000) {
                        tail.delete(0, tail.length() - 4000);
                    }
                }
            }
            if (!proc.waitFor(TIMEOUT_MIN, TimeUnit.MINUTES)) {
                proc.destroyForcibly();
                throw new BusinessException("fetch_bilibili.mjs --list 超时 " + TIMEOUT_MIN + "min");
            }
            exit = proc.exitValue();
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new BusinessException("调 fetch_bilibili.mjs 异常: " + e.getMessage());
        }
        if (exit != 0 || jsonLine == null) {
            throw new BusinessException("发现失败 exit=" + exit + ", 输出尾部: " + tail);
        }

        int inserted = 0, skipped = 0;
        try {
            for (JsonNode v : OM.readTree(jsonLine)) {
                String bvid = v.get("bvid").asText();
                if (bilibiliVideoService.getByBvid(bvid) != null) {
                    skipped++;
                    continue;
                }
                BilibiliVideo video = new BilibiliVideo();
                video.setBvid(bvid);
                video.setAuthorMid(v.get("mid").asText());
                video.setTitle(v.get("title").asText());
                video.setPublishTime(
                    LocalDateTime.ofInstant(Instant.ofEpochSecond(v.get("pubdate").asLong()),
                        ZoneId.of("Asia/Shanghai")));
                video.setDuration(v.get("duration").asInt());
                video.setUrl("https://www.bilibili.com/video/" + bvid);
                video.setStep("NEW");
                bilibiliVideoService.save(video);
                inserted++;
            }
        } catch (Exception e) {
            throw new BusinessException("解析/入库异常: " + e.getMessage());
        }
        /* 第二段: 下载所有 step=NEW 的(mp4+m4a+json) → DOWNLOADED */
        String downloadResult = bilibiliVideoService.downloadPendingVideos(3);
        /* 第三段: 直链处理所有 step=DOWNLOADED 的(process_video.py: ASR→纠错→视觉→聚合) → VISION_DONE,
           单视频~15-20min, 长任务靠 quartz @DisallowConcurrentExecution 防重叠 */
        String processResult = bilibiliVideoService.processPendingVideos(3);
        return String.format("B站视频拉取完成(多UP): 发现新增 %d/跳过 %d, %s, %s", inserted, skipped,
            downloadResult, processResult);
    }

}
