package exception;

import lombok.Getter;
import org.slf4j.helpers.MessageFormatter;
import result.IResultCode;

/**
 * @author sichu huang
 * @since 2025/11/22 23:42
 */
@Getter
public class BusinessException extends RuntimeException {
    public IResultCode resultCode;

    public BusinessException(IResultCode errorCode) {
        super(errorCode.getMsg());
        this.resultCode = errorCode;
    }

    public BusinessException(IResultCode resultCode, String customMsg) {
        super(customMsg);
        this.resultCode = resultCode;
    }

    public BusinessException(IResultCode resultCode, String customMsg, Throwable cause) {
        super(customMsg, cause);
        this.resultCode = resultCode;
    }

    public BusinessException(String msg, Throwable cause) {
        super(msg, cause);
    }

    public BusinessException(Throwable cause) {
        super(cause);
    }

    public BusinessException(String msg, Object... args) {
        super(formatMessage(msg, args));
    }

    private static String formatMessage(String msg, Object... args) {
        return MessageFormatter.arrayFormat(msg, args).getMessage();
    }
}
