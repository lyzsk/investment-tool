package cn.sichu.exception;

import java.io.Serial;

/**
 * @author sichu huang
 * @date 2024/03/24
 **/
public class TransactionException extends RuntimeException {
    @Serial
    private static final long serialVersionUID = 4133294663645980698L;

    private int code;
    private String msg;

    public TransactionException(int code, String msg) {
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
