package utils.file;

import exception.UtilException;
import utils.StringUtils;

import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * @author sichu huang
 * @since 2025/11/29 02:33
 */
public class MimeTypeUtils {

    /**
     * 支持的图片 MIME 类型集合
     */
    public static final Set<String> SUPPORTED_IMAGE_MIME_TYPES =
        Set.of("image/jpeg", "image/jpg", "image/png");
    /**
     * 常见文件扩展名到 MIME 类型的映射(小写)
     */
    private static final Map<String, String> EXTENSION_TO_MIME = new ConcurrentHashMap<>();

    static {
        /* 图片 MIME 类型 */
        EXTENSION_TO_MIME.put("jpeg", "image/jpeg");
        EXTENSION_TO_MIME.put("jpg", "image/jpeg");
        EXTENSION_TO_MIME.put("png", "image/png");

        /* pdf, txt, doc, docx, xls, xlsx */
        EXTENSION_TO_MIME.put("pdf", "application/pdf");
        EXTENSION_TO_MIME.put("txt", "text/plain");
        EXTENSION_TO_MIME.put("doc", "application/msword");
        EXTENSION_TO_MIME.put("docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
        EXTENSION_TO_MIME.put("xls", "application/vnd.ms-excel");
        EXTENSION_TO_MIME.put("xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    }

    public MimeTypeUtils() {
        throw new UtilException("MimeTypeUtils error");
    }

    /**
     * 根据文件扩展名获取 MIME 类型（不区分大小写），未知则返回 application/octet-stream
     *
     * @param extension 文件扩展名, 不含点
     * @return java.lang.String MIME 类型(小写)
     * @author sichu huang
     * @since 2025/11/29 02:43:39
     */
    public static String getMimeType(String extension) {
        if (StringUtils.isEmpty(extension)) {
            return "application/octet-stream";
        }
        return EXTENSION_TO_MIME.getOrDefault(extension.toLowerCase(), "application/octet-stream");
    }

    /**
     * 从文件名中提取扩展名并获取 MIME 类型
     *
     * @param filename 文件名.扩展名
     * @return java.lang.String MIME 类型
     * @author sichu huang
     * @since 2025/11/29 02:44:11
     */
    public static String getMimeTypeFromFilename(String filename) {
        if (StringUtils.isEmpty(filename)) {
            return "application/octet-stream";
        }
        String extesion = FileTypeUtils.getFileExtension(filename);
        return getMimeType(extesion);
    }

    /**
     * 判断给定的 MIME 类型是否为支持的图片类型
     *
     * @param mimeType mimeType MIME 类型(如 "image/png")
     * @return boolean
     * @author sichu huang
     * @since 2025/11/29 02:46:37
     */
    public static boolean isSupportedImageType(String mimeType) {
        if (mimeType == null) {
            return false;
        }
        return SUPPORTED_IMAGE_MIME_TYPES.contains(mimeType.toLowerCase());
    }

    /**
     * 获取所有支持的图片 MIME 类型
     *
     * @return java.util.Set<java.lang.String>
     * @author sichu huang
     * @since 2025/11/29 02:47:47
     */
    public static Set<String> getSupportedImageMimeTypes() {
        return Collections.unmodifiableSet(SUPPORTED_IMAGE_MIME_TYPES);
    }
}