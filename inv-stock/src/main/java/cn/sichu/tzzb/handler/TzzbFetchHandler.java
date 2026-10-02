package cn.sichu.tzzb.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import cn.sichu.tzzb.service.ITzzbRecordService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.TradingDayUtils;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/10/02 00:02
 */
@Component("tzzbFetchHandler")
@RequiredArgsConstructor
public class TzzbFetchHandler implements JobHandler {
    private static final long TIMEOUT_MIN = 15;   // 10/2 起含 change_bs 全历史分页(51标的~400请求), 5min 不够
    private final ITzzbRecordService tzzbRecordService;
    private final ProjectConfig projectConfig;
    private final ObjectMapper om = new ObjectMapper();

    @Override
    public String execute(String params) throws Exception {
        LocalDate expect = expectedNavDay();
        StringBuilder sb = new StringBuilder();
        for (String ledger : loadLedgers()) {
            if (tzzbRecordService.hasNavDay(ledger, expect)) {
                sb.append(ledger).append("已最新,跳过; ");
                continue;
            }
            runNode(ledger);
            sb.append(ledger).append(": ").append(tzzbRecordService.syncFromRawJson(ledger))
                .append("; ");
        }
        return "tzzb[" + expect + "] " + sb;
    }

    private LocalDate expectedNavDay() {
        LocalDate today = LocalDate.now();
        return TradingDayUtils.isTradingDay(today) ? today :
            TradingDayUtils.getPreviousTradingDay(today);
    }

    private List<String> loadLedgers() {
        try {
            JsonNode arr = om.readTree(
                Paths.get(projectConfig.getRootDir(), "scripts", "tzzb", "tzzb_ledgers.json").toFile());
            List<String> out = new ArrayList<>();
            for (JsonNode n : arr) {
                out.add(n.get("ledger").asText());
            }
            return out;
        } catch (Exception e) {
            throw new BusinessException("读 scripts/tzzb_ledgers.json 失败: " + e.getMessage());
        }
    }

    private void runNode(String ledger) {
        Path script = Paths.get(projectConfig.getRootDir(), "scripts", "tzzb", "fetch_tzzb.mjs");
        ProcessBuilder pb = new ProcessBuilder("node", script.toString(), "--ledger", ledger);
        pb.directory(Paths.get(projectConfig.getRootDir()).toFile());
        pb.redirectErrorStream(true);
        StringBuilder tail = new StringBuilder();
        int exit;
        try {
            Process proc = pb.start();
            try (BufferedReader br = new BufferedReader(
                new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    tail.append(line).append('\n');
                    if (tail.length() > 4000) {
                        tail.delete(0, tail.length() - 4000);
                    }
                }
            }
            if (!proc.waitFor(TIMEOUT_MIN, TimeUnit.MINUTES)) {
                proc.destroyForcibly();
                throw new BusinessException(
                    "fetch_tzzb.mjs 超时 " + TIMEOUT_MIN + "min ledger=" + ledger);
            }
            exit = proc.exitValue();
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new BusinessException(
                "调 fetch_tzzb.mjs 异常 ledger=" + ledger + ": " + e.getMessage());
        }
        if (exit == 2) {
            throw new BusinessException("tzzb 凭证失效 ledger=" + ledger
                + ", 需用户重新取 key(见 skills/cb-skill/references/api.md)");
        }
        if (exit != 0) {
            throw new BusinessException(
                "fetch_tzzb.mjs 失败 ledger=" + ledger + " exit=" + exit + ", 输出尾部: " + tail);
        }
    }
}
