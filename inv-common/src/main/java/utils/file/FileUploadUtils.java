package utils.file;

import config.ProjectConfig;
import exception.BusinessException;
import exception.UtilException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.multipart.MultipartFile;
import result.ResultCode;
import utils.IdUtils;
import utils.StringUtils;

import java.io.File;
import java.io.IOException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * 通用文件上传工具类, 用于 file_upload 表
 *
 * @author sichu huang
 * @since 2025/11/30 03:22
 */
@Slf4j
public class FileUploadUtils {
    public FileUploadUtils() {
        throw new UtilException("FileUploadUtils error");
    }

    /**
     * 单文件上传
     * <p/>
     * 1.校验 MIME 类型
     * <br/>
     * 2.生成安全文件名
     * <br/>
     * 3.生成日期子目录：/category/yyyy/MM/dd/
     * <br/>
     * 4.创建目录
     * <br/>
     * 5.写入文件
     * <br/>
     * 6.返回相对路径(存入file_upload表)
     *
     * @param file          file
     * @param category      category
     * @param projectConfig yml中project配置
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/11/30 07:53:10
     */
    public static String upload(MultipartFile file, String category, ProjectConfig projectConfig)
        throws IOException {
        ProjectConfig.FileUpload fileUploadConfig = projectConfig.getFile();
        return upload(file, category, fileUploadConfig.getRootDir(),
            fileUploadConfig.getAllowedTypes());
    }

    /**
     * 单文件上传(带参数)
     *
     * @param file         file
     * @param category     category
     * @param rootDir      rootDir
     * @param allowedTypes allowedTypes
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/11/30 07:54:24
     */
    public static String upload(MultipartFile file, String category, String rootDir,
        List<String> allowedTypes) throws IOException {
        if (file.isEmpty()) {
            throw new BusinessException(ResultCode.FILE_EMPTY);
        }

        String contentType = file.getContentType();
        if (!isAllowedType(contentType, allowedTypes)) {
            throw new BusinessException(ResultCode.FILE_TYPE_NOT_SUPPORTED);
        }

        String extension = FileTypeUtils.getFileExtension(file);
        String safeFilename = IdUtils.getSnowflakeNextId() + StringUtils.DOT + extension;
        String datePath = LocalDateTime.now().format(DateTimeFormatter.ofPattern("/yyyy.MM.dd/"));
        String relativeDir = "/" + category + datePath;
        String absoluteDir = rootDir + relativeDir;

        File dir = new File(absoluteDir);
        if (!dir.exists() && !dir.mkdirs()) {
            throw new IOException("无法创建上传目录: " + absoluteDir);
        }

        String absolutePath = absoluteDir + safeFilename;
        file.transferTo(new File(absolutePath));
        log.info("文件上传成功: {}", absolutePath);

        return relativeDir + safeFilename;
    }

    /**
     * 删除文件(根据相对路径)
     *
     * @param relativePath  relativePath
     * @param projectConfig yml中project配置
     * @return boolean
     * @author sichu huang
     * @since 2025/11/30 07:55:17
     */
    public static boolean delete(String relativePath, ProjectConfig projectConfig) {
        if (StringUtils.isEmpty(relativePath)) {
            return false;
        }
        String absolutePath = projectConfig.getFile().getRootDir() + relativePath;
        boolean deleted = FileUtils.deleteFile(absolutePath);
        if (deleted) {
            log.info("文件删除成功: {}", absolutePath);
        } else {
            log.warn("文件删除失败（可能不存在）: {}", absolutePath);
        }
        return deleted;
    }

    /**
     * 删除文件(根据相对路径+自定义根目录)
     *
     * @param relativePath relativePath
     * @param rootDir      rootDir
     * @return boolean
     * @author sichu huang
     * @since 2025/11/30 07:56:17
     */
    public static boolean delete(String relativePath, String rootDir) {
        if (StringUtils.isEmpty(relativePath)) {
            return false;
        }
        String absolutePath = rootDir + relativePath;
        boolean deleted = FileUtils.deleteFile(absolutePath);
        if (deleted) {
            log.info("文件删除成功: {}", absolutePath);
        } else {
            log.warn("文件删除失败（可能不存在）: {}", absolutePath);
        }
        return deleted;
    }

    /**
     * 获取文件绝对路径
     *
     * @param relativePath  relativePath
     * @param projectConfig yml中project配置
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/11/30 07:56:58
     */
    public static String getAbsolutePath(String relativePath, ProjectConfig projectConfig) {
        return projectConfig.getFile().getRootDir() + relativePath;
    }

    /**
     * 获取文件绝对路径
     *
     * @param relativePath relativePath
     * @param rootDir      rootDir
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/11/30 07:57:53
     */
    public static String getAbsolutePath(String relativePath, String rootDir) {
        return rootDir + relativePath;
    }

    /**
     * 校验文件类型
     *
     * @param contentType  contentType
     * @param allowedTypes allowedTypes
     * @return boolean
     * @author sichu huang
     * @since 2025/11/30 07:58:26
     */
    private static boolean isAllowedType(String contentType, List<String> allowedTypes) {
        if (contentType == null) {
            return false;
        }
        return allowedTypes.stream().anyMatch(
            allowedType -> contentType.toLowerCase().startsWith(allowedType.toLowerCase()));
    }
}
