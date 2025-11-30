package utils;

import org.springframework.stereotype.Component;

/**
 * @author sichu huang
 * @since 2025/11/22 23:52
 */
@Component
public class StringUtils {

    public static final String EMPTY = "";
    public static final String DOT = ".";

    public static boolean isEmpty(String str) {
        return str == null || str.trim().isEmpty();
    }

    public static boolean isNotEmpty(String str) {
        return !isEmpty(str);
    }

    public static String maxLength(String str, int max) {
        if (str == null)
            return null;
        return str.length() > max ? str.substring(0, max) : str;
    }
}
