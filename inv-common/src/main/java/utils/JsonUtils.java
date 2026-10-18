package utils;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.json.JsonReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;

import java.io.BufferedReader;
import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * @author sichu huang
 * @since 2026/01/03 16:37
 */
@Slf4j
public class JsonUtils {
    @Getter
    public static final ObjectMapper objectMapper =
        new ObjectMapper().registerModule(new JavaTimeModule())
            .configure(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS, false)
            .configure(JsonParser.Feature.ALLOW_COMMENTS, true)
            .configure(JsonReadFeature.ALLOW_TRAILING_COMMA.mappedFeature(), true)
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

    /**
     * 从 URL 中提取原始扩展名(不校验合法性, 不转换jpeg->jpg)
     *
     * @param url url
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/06 16:20:46
     */
    public static String getExtensionFromUrl(String url) {
        if (StringUtils.isEmpty(url)) {
            return null;
        }
        try {
            URI uri = new URI(url);
            String path = uri.getPath();
            if (path == null || path.isEmpty()) {
                return null;
            }
            int lastDotIndex = path.lastIndexOf('.');
            if (lastDotIndex > 0 && lastDotIndex < path.length() - 1) {
                String ext = path.substring(lastDotIndex + 1).toLowerCase();
                if (ext.matches("[a-zA-Z0-9]+")) {
                    return ext;
                }
            }
            return null;
        } catch (URISyntaxException e) {
            return null;
        }
    }

    /**
     * 读 jsonl 文件(一行一个 JSON 对象, 字段名=目标类驼峰属性名), 空行跳过; 未知字段忽略
     *
     * @author sichu huang
     * @param file 文件路径
     * @param type 目标类型
     * @since 2026/10/11
     * @return java.util.List<T>
     **/
    public static <T> List<T> readJsonl(Path file, Class<T> type) throws IOException {
        List<T> list = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (StringUtils.isNotEmpty(line.trim())) {
                    list.add(objectMapper.readValue(line, type));
                }
            }
        }
        return list;
    }
}
