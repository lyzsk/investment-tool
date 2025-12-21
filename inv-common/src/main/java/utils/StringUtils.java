package utils;

import org.springframework.stereotype.Component;

/**
 * @author sichu huang
 * @since 2025/11/22 23:52
 */
@Component
public class StringUtils {

    public static final String EMPTY = "";
    public static final String SPACE = " ";
    public static final String COMMA = ",";
    public static final String DOT = ".";
    public static final String UNDERLINE = "_";
    public static final String SLASH = "/";

    public static final String LEFT_BRACE = "{";
    public static final String RIGHT_BRACE = "}";
    public static final String LEFT_PARENTHESIS = "(";
    public static final String RIGHT_PARENTHESIS = ")";

    public static boolean isEmpty(String str) {
        return str == null || str.trim().isEmpty();
    }

    public static boolean isNotEmpty(String str) {
        return str != null && !str.trim().isEmpty();
    }

    public static String maxLength(String str, int max) {
        if (str == null)
            return null;
        return str.length() > max ? str.substring(0, max) : str;
    }
}
