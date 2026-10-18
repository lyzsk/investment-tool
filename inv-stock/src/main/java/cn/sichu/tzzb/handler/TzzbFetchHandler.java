package cn.sichu.tzzb.handler;

import cn.sichu.system.config.ProjectConfig;
import cn.sichu.system.quartz.handler.JobHandler;
import cn.sichu.tzzb.service.ITzzbRecordService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import utils.ProcessUtils;
import utils.TradingDayUtils;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;

/**
 *
 * @author sichu huang
 * @since 2026/10/02 00:02
 */
@Component("tzzbFetchHandler")
@RequiredArgsConstructor
public class TzzbFetchHandler implements JobHandler {
    /* 10/2 起含 change_bs 全历史分页(51标的~400请求), 5min 不够 */
    private static final long TIMEOUT_MIN = 15;
    private final ITzzbRecordService tzzbRecordService;
    private final ProjectConfig projectConfig;
    private final ObjectMapper om = new ObjectMapper();

    @Override
    public String execute(String params) throws Exception {
        LocalDate expect = expectedNavDay();
        StringBuilder sb = new StringBuilder();
        /* 10/14: 原先任一账本失败就整轮抛异常, 排在后面的账本全不抓(10/14 15:13 起 16 个账本只抓到 2 个);
           改为: 凭证失效=跳过该账本继续; IP 被封=立即停本轮(再抓只会延长封禁); 其余失败=记下继续 */
        List<String> failed = new ArrayList<>();
        boolean first = true;
        for (String ledger : loadLedgers()) {
            if (tzzbRecordService.hasNavDay(ledger, expect)) {
                sb.append(ledger).append("已最新,跳过; ");
                continue;
            }
            /* 10/15: 真正要抓的账本之间隔 30~60 秒随机(像人逐个点开, 防同花顺反爬按频率识别); 已最新跳过的不等 */
            if (!first) {
                TimeUnit.SECONDS.sleep(30 + ThreadLocalRandom.current().nextInt(31));
            }
            first = false;
            try {
                runNode(ledger);
            } catch (IpBannedException e) {
                throw new BusinessException("tzzb[" + expect + "] 同花顺封 IP 或当日请求预算用完(见输出尾部), 本轮停止(已完成: " + sb + "): " + e.getMessage());
            } catch (BusinessException e) {
                failed.add(ledger);
                sb.append(ledger).append(": 失败(").append(e.getMessage()).append("); ");
                continue;
            }
            sb.append(ledger).append(": ").append(tzzbRecordService.syncFromRawJson(ledger))
                .append("; ");
        }
        if (!failed.isEmpty()) {
            throw new BusinessException("tzzb[" + expect + "] 有 " + failed.size() + " 个账本失败 " + failed + ", 其余已抓: " + sb);
        }
        return "tzzb[" + expect + "] " + sb;
    }

    /** fetch_tzzb.mjs 退出码 5: 同花顺 WAF 返回 Nginx forbidden(封 IP), 或当日请求预算用完(10/15 起都走 5, 都该停本轮) */
    private static class IpBannedException extends RuntimeException {
        IpBannedException(String msg) {
            super(msg);
        }
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
            /* 10/17 健壮性 H6: 改用 ProcessUtils.run(独立线程读输出, 超时真生效并杀子孙进程); 原写法先读到 EOF 再 waitFor, 子进程卡住=线程永久挂起 */
            ProcessUtils.Result res = ProcessUtils.run(pb, TIMEOUT_MIN);
            tail.append(res.tail());
            if (res.timedOut()) {
                throw new BusinessException(
                    "fetch_tzzb.mjs 超时 " + TIMEOUT_MIN + "min ledger=" + ledger + "(进程树已杀)");
            }
            exit = res.exit();
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            throw new BusinessException(
                "调 fetch_tzzb.mjs 异常 ledger=" + ledger + ": " + e.getMessage());
        }
        if (exit == 5) {
            throw new IpBannedException("ledger=" + ledger + " 输出尾部: " + tail.toString().trim());
        }
        if (exit == 2) {
            throw new BusinessException("tzzb 凭证失效 ledger=" + ledger
                + ", 需用户重新取 key(见 skills/buchitudou0-skill/references/api.md)");
        }
        if (exit != 0) {
            throw new BusinessException(
                "fetch_tzzb.mjs 失败 ledger=" + ledger + " exit=" + exit + ", 输出尾部: " + tail);
        }
    }
}
