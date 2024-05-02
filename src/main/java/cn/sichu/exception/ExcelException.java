package cn.sichu.exception;

import java.io.Serial;

/**
 * @author sichu huang
 * @date 2024/04/01
 **/
public class ExcelException extends RuntimeException {
    @Serial
    private static final long serialVersionUID = 3652175395071972828L;

    private int code;
    private String msg;

    public ExcelException(int code, String msg) {
        this.code = code;
        this.msg = msg;
    }

    public int getCode() {
        return code;
    }

    public void setCode(int code) {
        this.code = code;
    }

    public String getMsg() {
        return msg;
    }

    public void setMsg(String msg) {
        this.msg = msg;
    }
}
