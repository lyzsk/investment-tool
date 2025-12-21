package cn.sichu.system.file.service;

import cn.sichu.system.file.dto.FileUploadDto;
import cn.sichu.system.file.entity.FileUpload;
import com.baomidou.mybatisplus.extension.service.IService;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * @author sichu huang
 * @since 2025/11/30 05:36
 */
public interface IFileUploadService extends IService<FileUpload> {

    FileUpload upload(MultipartFile file, String category);

    FileUploadDto batchUpload(List<MultipartFile> files, String category);

    FileUploadDto batchUploadFromLocal(String category, String path, String contentType);

    FileUploadDto batchUploadFromPathWithExtensions(String category, String path,
        String extensions);
}
