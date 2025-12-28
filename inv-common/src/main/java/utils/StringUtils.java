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
    public static final String LEFT_SQUARE_BRACKET = "[";
    public static final String RIGHT_SQUARE_BRACKET = "]";
    public static final String PERCENT = "%";
    public static final String QUESTION_MARK = "?";
    public static final String EXCLAMATION_MARK = "!";
    public static final String AT = "@";
    public static final String HASH = "#";
    public static final String DOLLAR = "$";
    public static final String AMPERSAND = "&";
    public static final String COLON = ":";
    public static final String SEMICOLON = ";";
    public static final String EQUAL = "=";
    public static final String PLUS = "+";
    public static final String MINUS = "-";
    public static final String ASTERISK = "*";
    public static final String BACKSLASH = "\\";
    public static final String TILDE = "~";
    public static final String PIPE = "|";
    public static final String BACKTICK = "`";
    public static final String QUOTE = "\"";
    public static final String APOSTROPHE = "'";
    public static final String LEFT_ANGLE_BRACKET = "<";
    public static final String RIGHT_ANGLE_BRACKET = ">";
    public static final String CARET = "^";

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
