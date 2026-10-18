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

    /* 参数错误码 */
    PARAMS_EMPTY("PARAMS_001", "参数不能为空"), PARAMS_TYPE_ERROR("PARAMS_002",
        "参数类型错误"), PARAMS_NOT_FOUND("PARAMS_003", "参数不存在"), PARAMS_REPEAT("PARAMS_004",
        "参数重复"),

    /* upload 错误码 */
    FILE_EMPTY("FILE_001", "上传文件不能为空"), FILE_TYPE_NOT_SUPPORTED("FILE_002",
        "不支持的文件类型"), FILE_UPLOAD_FAILED("FILE_003", "文件上传失败，请重试"), FILE_NOT_FOUND(
        "FILE_004", "文件不存在"), FAILED_TO_READ_FILE("FILE_005", "读取文件失败"),

    /* 路径错误码 */
    INVALID_PATH("PATH_001", "路径不存在或不是文件夹"),

    /* img 错误码 */
    IMAGE_TYPE_NOT_SUPPORTED("IMG_001", "不支持的图像文件类型，仅支持 JPEG/JPG/PNG"),

    /* ocr 错误码 */
    OCR_FAILED("OCR_001", "OCR识别失败"),

    /* Cron表达式错误 */
    INVALID_CRON_EXPRESSION("CRON_001", "无效的Cron表达式");

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
