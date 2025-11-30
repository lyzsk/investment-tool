package exception;

import java.io.Serializable;

/**
 * @author sichu huang
 * @since 2025/11/29 02:34
 */
public class UtilException extends RuntimeException implements Serializable {

    public UtilException(Throwable e) {
        super(e.getMessage(), e);
    }

    public UtilException(String msg) {
        super(msg);
    }

    public UtilException(String message, Throwable throwable) {
        super(message, throwable);
    }

}
