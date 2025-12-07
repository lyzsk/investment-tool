package utils;

import java.io.PrintWriter;
import java.io.StringWriter;

/**
 * @author sichu huang
 * @since 2025/12/07 16:46
 */
public class ExceptionUtils {

    public static String stacktraceToString(Throwable e, int maxLength) {
        if (e == null) {
            return StringUtils.EMPTY;
        }
        StringWriter sw = new StringWriter();
        PrintWriter pw = new PrintWriter(sw);
        e.printStackTrace(pw);
        String stackTrace = sw.toString();
        if (maxLength > 0 && stackTrace.length() > maxLength) {
            return stackTrace.substring(0, maxLength);
        }
        return stackTrace;
    }
}
