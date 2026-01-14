package utils;

/**
 * @author sichu huang
 * @since 2026/01/14 15:28
 */
public class MarkdownUtils {

    /**
     * 1. 统一换行为 \n
     * <p/>
     * 2. 合并多个连续空行为最多两个
     * <p/>
     * 3. 确保文件末尾有且仅有一个换行
     * <p/>
     * 规范化标题(如 ## 之后加空格)
     * <p/>
     * 列表项标准化
     *
     * @param content content
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/01/14 15:28:57
     */
    public static String format(String content) {
        content = content.replace("\r\n", "\n").replace("\r", "\n");
        content = content.replaceAll("\n{3,}", "\n\n");
        if (!content.endsWith("\n")) {
            content += "\n";
        }
        content = content.replaceAll("(#{1,6})([^\\s#])", "$1 $2");
        content = content.replaceAll("(?m)^([\\-\\*\\+])\\s+", "$1 ");
        return content;
    }
}
