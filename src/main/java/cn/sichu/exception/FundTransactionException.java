package cn.sichu.exception;

import java.io.Serial;

/**
 * @author sichu huang
 * @date 2024/03/24
 **/
public class FundTransactionException extends RuntimeException {
    @Serial
    private static final long serialVersionUID = 4133294663645980698L;

    private Integer code;
    private String message;

    public FundTransactionException(Integer code, String message) {
        this.code = code;
        this.message = message;
    }

    public Integer getCode() {
        return code;
    }

    public void setCode(Integer code) {
        this.code = code;
    }

    @Override
    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }
}
