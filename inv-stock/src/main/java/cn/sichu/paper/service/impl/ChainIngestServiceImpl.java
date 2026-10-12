package cn.sichu.paper.service.impl;

import cn.sichu.paper.entity.ChainDecision;
import cn.sichu.paper.entity.ChainDecisionRule;
import cn.sichu.paper.entity.ChainRun;
import cn.sichu.paper.entity.ChainStep;
import cn.sichu.paper.mapper.ChainDecisionMapper;
import cn.sichu.paper.mapper.ChainDecisionRuleMapper;
import cn.sichu.paper.mapper.ChainRunMapper;
import cn.sichu.paper.mapper.ChainStepMapper;
import cn.sichu.paper.service.IChainIngestService;
import cn.sichu.system.config.ProjectConfig;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import utils.DateTimeUtils;
import utils.JsonUtils;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 *
 * @author sichu huang
 * @since 2026/10/12
 **/
@Slf4j
@Service
@RequiredArgsConstructor
public class ChainIngestServiceImpl implements IChainIngestService {
    /* 步骤 → 产物文件(同 run_taoge_chain.py ART) */
    private static final Map<String, String> STEP_FILES = new LinkedHashMap<>();
    private static final Pattern CONTRACT = Pattern.compile("```contract\\s*\\n([\\s\\S]*?)```");
    private static final Pattern RUN_DIR = Pattern.compile("(live|asof)-(\\d{8})");
    private static final String FINAL = "FINAL";
    private static final int STR_MAX = 1000;

    static {
        STEP_FILES.put("01", "01_facts.md");
        STEP_FILES.put("02", "02_analysis.md");
        STEP_FILES.put("03b", "03_debate_bull.md");
        STEP_FILES.put("03s", "03_debate_bear.md");
        STEP_FILES.put("03j", "03_debate.md");
        STEP_FILES.put("04", "04_plan.md");
        STEP_FILES.put("05", "05_risk.md");
        STEP_FILES.put("06", "06_verdict.md");
        STEP_FILES.put("blind", "validate_report.md");
        STEP_FILES.put("07", "07_review.md");
    }

    private final ProjectConfig projectConfig;
    private final ChainRunMapper chainRunMapper;
    private final ChainStepMapper chainStepMapper;
    private final ChainDecisionMapper chainDecisionMapper;
    private final ChainDecisionRuleMapper chainDecisionRuleMapper;
    /* 历史补导每个目录一个事务(一个坏目录不回滚全部) */
    private final TransactionTemplate transactionTemplate;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String ingest(String skill, String mode, LocalDate runDate, String slot, Integer exitCode,
        LocalDateTime startedAt, LocalDateTime finishedAt) throws Exception {
        String dirName = mode.toLowerCase() + "-" + runDate.format(DateTimeUtils.YYYYMMDD);
        Path dir = Paths.get(projectConfig.getFile().getResult().getRootDir(), skill + "_chain", dirName);
        if (!Files.isDirectory(dir)) {
            throw new BusinessException("链运行目录不存在: " + dir);
        }
        deleteRuns(new LambdaQueryWrapper<ChainRun>().eq(ChainRun::getSkill, skill).eq(ChainRun::getMode, mode)
            .eq(ChainRun::getRunDate, runDate).eq(ChainRun::getSlot, slot));
        String yyyymmdd = runDate.format(DateTimeUtils.YYYYMMDD);
        ChainRun run = new ChainRun();
        run.setSkill(skill);
        run.setMode(mode);
        run.setRunDate(runDate);
        run.setSlot(slot);
        run.setRunDir(Paths.get(projectConfig.getRootDir()).relativize(dir).toString().replace('\\', '/'));
        run.setExitCode(exitCode);
        run.setStartedAt(startedAt);
        run.setBlindFailed(Files.exists(dir.resolve("BLIND_FAILED.txt")) ? 1 : 0);
        readRunMeta(dir, run);

        List<ChainStep> steps = new ArrayList<>();
        Map<String, JsonNode> contracts = new LinkedHashMap<>();
        List<String> touched = new ArrayList<>();
        LocalDateTime latest = null;
        for (Map.Entry<String, String> e : STEP_FILES.entrySet()) {
            Path f = dir.resolve(e.getValue());
            if (!Files.isRegularFile(f)) {
                continue;
            }
            String text = Files.readString(f, StandardCharsets.UTF_8);
            LocalDateTime mtime =
                LocalDateTime.ofInstant(Files.getLastModifiedTime(f).toInstant(), ZoneId.systemDefault());
            latest = latest == null || mtime.isAfter(latest) ? mtime : latest;
            /* 盘中子链只重跑 02/04/06, 其余是盘前留下的旧文件: steps 只记本次进程期间改过的 */
            if (startedAt == null || !mtime.isBefore(startedAt)) {
                touched.add(e.getKey());
            }
            ChainStep s = new ChainStep();
            s.setStep(e.getKey());
            s.setFileName(e.getValue());
            s.setFileMtime(mtime);
            s.setBytes((int) Files.size(f));
            s.setSha12(sha12(text));
            s.setSentinelOk(sentinelOk(text, e.getKey(), yyyymmdd) ? 1 : 0);
            Matcher m = CONTRACT.matcher(text);
            String block = null;
            while (m.find()) {
                block = m.group(1);
            }
            if (block == null) {
                s.setContractError("无 contract 块");
            } else {
                try {
                    JsonNode c = JsonUtils.objectMapper.readTree(block);
                    contracts.put(e.getKey(), c);
                    s.setContractJson(c.toString());
                } catch (Exception ex) {
                    s.setContractError(cut("contract JSON 解析失败: " + ex.getMessage(), 200));
                }
            }
            steps.add(s);
        }
        run.setFinishedAt(finishedAt != null ? finishedAt : latest);
        if (startedAt != null && run.getFinishedAt() != null) {
            run.setDurationS((int) Duration.between(startedAt, run.getFinishedAt()).getSeconds());
        }
        run.setSteps(String.join(",", touched));
        JsonNode c02 = contracts.get("02");
        if (c02 != null) {
            run.setMarketState(text(c02, "market_state", 16));
            run.setLeadingLayer(text(c02, "leading_layer", 16));
        }
        if (contracts.containsKey("03j")) {
            run.setDebateWinner(text(contracts.get("03j"), "winner", 4));
        }
        if (contracts.containsKey("blind")) {
            run.setBlindVerdict(text(contracts.get("blind"), "verdict", 8));
        }
        JsonNode c06 = contracts.get("06");
        JsonNode actions = c06 == null ? null : c06.path("actions");
        if (c06 != null) {
            run.setNoTrade(c06.path("no_trade").asBoolean(false) ? 1 : 0);
            run.setActionCount(actions.isArray() ? actions.size() : 0);
        }
        chainRunMapper.insert(run);
        for (ChainStep s : steps) {
            s.setRunId(run.getId());
            chainStepMapper.insert(s);
        }
        int decisions = 0;
        int rules = 0;
        if (actions != null && actions.isArray()) {
            for (int i = 0; i < actions.size(); i++) {
                JsonNode a = actions.get(i);
                ChainDecision d = new ChainDecision();
                d.setRunId(run.getId());
                d.setSkill(skill);
                d.setRunDate(runDate);
                d.setSlot(slot);
                d.setActionIdx(i);
                d.setName(text(a, "name", 64));
                d.setCode(text(a, "code", 16));
                d.setOp(text(a, "op", 8));
                d.setTriggerPrice(text(a, "trigger_price", 64));
                d.setQty(a.path("qty").canConvertToInt() || a.path("qty").isTextual() ? toInt(a.path("qty")) : null);
                d.setAnchor(text(a, "anchor", 64));
                d.setCancelBelow(decimal(a.path("cancel_below")));
                d.setStopBelow(decimal(a.path("stop_below")));
                d.setInvalidIf(text(a, "invalid_if", STR_MAX));
                d.setActionJson(a.toString());
                chainDecisionMapper.insert(d);
                decisions++;
                for (JsonNode r : a.path("rules")) {
                    String id = r.isTextual() ? r.asText() : text(r, "id", 16);
                    if (id == null || id.isBlank()) {
                        continue;
                    }
                    ChainDecisionRule dr = new ChainDecisionRule();
                    dr.setDecisionId(d.getId());
                    dr.setRunId(run.getId());
                    dr.setSkill(skill);
                    dr.setRuleId(cut(id, 16));
                    dr.setCtx(r.isTextual() ? null : r.path("ctx").asText(null));
                    chainDecisionRuleMapper.insert(dr);
                    rules++;
                }
            }
        }
        return "链入库 " + skill + " " + dirName + " slot=" + slot + ": 步骤 " + steps.size() + " / 终裁单 " + decisions
            + " / 规则引用 " + rules;
    }

    @Override
    public String ingestAll() throws Exception {
        Path root = Paths.get(projectConfig.getFile().getResult().getRootDir());
        List<Path> dirs = new ArrayList<>();
        try (Stream<Path> chains = Files.list(root)) {
            for (Path chain : chains.filter(p -> Files.isDirectory(p) && p.getFileName().toString().endsWith("_chain"))
                .sorted().toList()) {
                try (Stream<Path> runs = Files.list(chain)) {
                    runs.filter(p -> Files.isDirectory(p) && RUN_DIR.matcher(p.getFileName().toString()).matches())
                        .sorted().forEach(dirs::add);
                }
            }
        }
        int done = 0;
        int skipped = 0;
        List<String> failed = new ArrayList<>();
        for (Path dir : dirs) {
            String chain = dir.getParent().getFileName().toString();
            String skill = chain.substring(0, chain.length() - "_chain".length());
            Matcher m = RUN_DIR.matcher(dir.getFileName().toString());
            if (!m.matches()) {
                continue;
            }
            String mode = m.group(1).toUpperCase();
            LocalDate day = LocalDate.parse(m.group(2), DateTimeUtils.YYYYMMDD);
            long live = chainRunMapper.selectCount(
                new LambdaQueryWrapper<ChainRun>().eq(ChainRun::getSkill, skill).eq(ChainRun::getMode, mode)
                    .eq(ChainRun::getRunDate, day).ne(ChainRun::getSlot, FINAL));
            if (live > 0) {
                skipped++;
                continue;
            }
            try {
                transactionTemplate.execute(status -> {
                    try {
                        return ingest(skill, mode, day, FINAL, null, null, null);
                    } catch (Exception e) {
                        throw new BusinessException(e.getMessage());
                    }
                });
                done++;
            } catch (Exception e) {
                log.error("链历史补导失败 {}", dir, e);
                failed.add(skill + "/" + dir.getFileName());
            }
        }
        String summary = "链历史补导: 目录 " + dirs.size() + " / 入库 " + done + " / 已有实盘时段跳过 " + skipped + (failed.isEmpty() ?
            "" : " / 失败 " + failed.size() + " " + failed.stream().limit(20).toList());
        log.info(summary);
        return summary;
    }

    /**
     * 删运行及其下属行(物理删除)
     *
     * @author sichu huang
     * @param q q
     * @since 2026/10/12
     **/
    private void deleteRuns(LambdaQueryWrapper<ChainRun> q) {
        List<Long> ids = chainRunMapper.selectList(q).stream().map(ChainRun::getId).toList();
        if (ids.isEmpty()) {
            return;
        }
        chainDecisionRuleMapper.physicalDeleteByRunIds(ids);
        chainDecisionMapper.physicalDeleteByRunIds(ids);
        chainStepMapper.physicalDeleteByRunIds(ids);
        chainRunMapper.physicalDeleteByIds(ids);
    }

    /**
     * run_meta.jsonl 末行(10/11 起 driver 每次运行追加: persona 版本/规则条数/chain.md 版本), 没有就跳过
     *
     * @author sichu huang
     * @param dir dir
     * @param run run
     * @since 2026/10/12
     **/
    private void readRunMeta(Path dir, ChainRun run) {
        Path f = dir.resolve("run_meta.jsonl");
        if (!Files.isRegularFile(f)) {
            return;
        }
        try {
            List<String> lines = Files.readAllLines(f, StandardCharsets.UTF_8).stream().filter(l -> !l.isBlank()).toList();
            if (lines.isEmpty()) {
                return;
            }
            JsonNode meta = JsonUtils.objectMapper.readTree(lines.get(lines.size() - 1));
            run.setRulesCount(meta.path("rules_count").isNumber() ? meta.path("rules_count").asInt() : null);
            run.setChainMdSha12(text(meta, "chain_md_sha12", 12));
            run.setPersonaJson(meta.has("persona") ? meta.path("persona").toString() : null);
        } catch (Exception e) {
            log.warn("run_meta.jsonl 解析失败 {}: {}", f, e.getMessage());
        }
    }

    private boolean sentinelOk(String text, String step, String yyyymmdd) {
        String[] lines = text.strip().split("\\R");
        String last = lines.length == 0 ? "" : lines[lines.length - 1].strip();
        return "blind".equals(step) ? last.equals("REVIEW_OK " + yyyymmdd) : last.equals("STEP_OK " + step + " " + yyyymmdd);
    }

    private String sha12(String text) throws Exception {
        byte[] d = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        return HexFormat.of().formatHex(d).substring(0, 12);
    }

    private String text(JsonNode n, String field, int max) {
        JsonNode v = n.path(field);
        if (v.isMissingNode() || v.isNull()) {
            return null;
        }
        return cut(v.isTextual() ? v.asText() : v.toString(), max);
    }

    private String cut(String s, int max) {
        return s == null || s.length() <= max ? s : s.substring(0, max);
    }

    private Integer toInt(JsonNode v) {
        try {
            return v.isTextual() ? Integer.valueOf(v.asText().trim()) : v.asInt();
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private BigDecimal decimal(JsonNode v) {
        if (v.isNumber()) {
            return v.decimalValue();
        }
        if (v.isTextual()) {
            try {
                return new BigDecimal(v.asText().trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }
}
