package cn.sichu.cls.utils;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;

import java.util.regex.Pattern;

/**
 * @author sichu huang
 * @since 2026/01/03 16:37
 */
@Slf4j
public class JsonFixUtils {
    public static final ObjectMapper objectMapper =
        new ObjectMapper().configure(JsonParser.Feature.ALLOW_COMMENTS, true)
            .configure(JsonParser.Feature.ALLOW_TRAILING_COMMA, true)
            .configure(JsonParser.Feature.ALLOW_SINGLE_QUOTES, true)
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    /* 移除尾随逗号（在 } 或 ] 前） */
    private static final Pattern TRAILING_COMMA_PATTERN = Pattern.compile(",(\\s*[}\\]])");

    /* 移除非法控制字符（U+0000 - U+001F，除了 \t\n\r */
    private static final Pattern CONTROL_CHAR_PATTERN =
        Pattern.compile("[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F]");

    public static String fixJsonString(String rawJson) {
        if (rawJson == null || rawJson.trim().isEmpty()) {
            throw new IllegalArgumentException("JSON 字符串为空");
        }
        /* 1. 清理控制字符 */
        String cleaned = CONTROL_CHAR_PATTERN.matcher(rawJson).replaceAll("");
        /* 2. 修复尾随逗号 */
        cleaned = TRAILING_COMMA_PATTERN.matcher(cleaned).replaceAll("$1");
        /* 3. 尝试解析验证 */
        try {
            JsonNode node = objectMapper.readTree(cleaned);
            return objectMapper.writeValueAsString(node);
        } catch (Exception e) {
            log.warn("JSON 修复后仍无法解析，原始内容前200字符: {}",
                rawJson.substring(0, Math.min(200, rawJson.length())));
            throw new RuntimeException("JSON 修复失败", e);
        }
    }

    public static JsonNode parseFixedJson(String rawJson) throws Exception {
        String fixed = fixJsonString(rawJson);
        return objectMapper.readTree(fixed);
    }
}
