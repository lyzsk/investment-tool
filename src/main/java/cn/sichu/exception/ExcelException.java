package cn.sichu.exception;

import java.io.Serial;

/**
 * @author sichu huang
 * @date 2024/04/01
 **/
public class ExcelException extends RuntimeException {
    @Serial
    private static final long serialVersionUID = 3652175395071972828L;

    private Integer code;
    private String message;

    public ExcelException(Integer code, String message) {
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
