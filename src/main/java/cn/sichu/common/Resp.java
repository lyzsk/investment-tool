package cn.sichu.common;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * @author sichu huang
 * @date 2024/05/02
 **/
public class Resp<T> {
    @JsonProperty("code")
    private int code;
    @JsonProperty("msg")
    private String msg;
    @JsonProperty("data")
    private T data;

    public Resp(int code, String msg, T data) {
        this.code = code;
        this.msg = msg;
        this.data = data;
    }

    public static <T> Resp<T> success(T data) {
        return new Resp<>(200, "success", data);
    }

    public static <T> Resp<T> success(String msg, T data) {
        return new Resp<>(200, msg, data);
    }

    public static <T> Resp<T> error(String msg) {
        return new Resp<>(500, msg, null);
    }

    public static <T> Resp<T> error(int code, String msg) {
        return new Resp<>(code, msg, null);
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

    public T getData() {
        return data;
    }

    public void setData(T data) {
        this.data = data;
    }
}
