package cn.sichu.enums;

/**
 * @author sichu huang
 * @date 2024/05/02
 **/
public enum AppExceptionCodeMsg {
    FUND_TRANSACTION_EXCEPTION(999, "fund transaction exception"), EXCEL_EXPORT_EXCEPTION(998, "excel export exception");

    private int code;
    private String msg;

    AppExceptionCodeMsg(int code, String msg) {
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
