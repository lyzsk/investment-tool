package result;

import lombok.AllArgsConstructor;
import lombok.NoArgsConstructor;

import java.io.Serializable;

/**
 * @author sichu huang
 * @since 2025/11/22 22:01
 */
@AllArgsConstructor
@NoArgsConstructor
public enum ResultCode implements IResultCode, Serializable {

    /* 常规错误码 */
    SUCCESS("200", "成功"), FAILED("500", "失败"), VALIDATE_FAILED("400",
        "参数验证失败"), UNAUTHORIZED("401", "未认证"), FORBIDDEN("403", "无权限"), NOT_FOUND("404",
        "未找到"), REQUEST_TIMEOUT("408", "请求超时"), INTERNAL_SERVER_ERROR("500",
        "服务器内部错误"), SERVICE_UNAVAILABLE("503", "服务不可用"), GATEWAY_TIMEOUT("504",
        "网关超时"),

    /* A类错误码 */
    UPLOAD_FILE_FAILED("A0000", "上传文件失败"), OCR_FAILED("A0001", "OCR识别失败");

    private String code;

    private String msg;

    @Override
    public String getCode() {
        return code;
    }

    @Override
    public String getMsg() {
        return msg;
    }

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }
}
