package cn.sichu.system.service;

import cn.sichu.system.entity.FileUpload;
import com.baomidou.mybatisplus.extension.service.IService;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * @author sichu huang
 * @since 2025/11/30 05:36
 */
public interface IFileUploadService extends IService<FileUpload> {

    FileUpload upload(MultipartFile file, String category);

    List<FileUpload> batchUpload(List<MultipartFile> files, String category);
}
