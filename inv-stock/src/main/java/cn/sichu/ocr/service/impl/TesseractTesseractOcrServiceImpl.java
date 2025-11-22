package cn.sichu.ocr.service.impl;

import cn.sichu.ocr.init.TessdataExtractor;
import cn.sichu.ocr.service.ITesseractOcrService;
import exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import net.sourceforge.tess4j.Tesseract;
import org.springframework.stereotype.Service;
import result.ResultCode;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;

@Service
@Slf4j
public class TesseractTesseractOcrServiceImpl implements ITesseractOcrService {
    private final TessdataExtractor tessdataExtractor;

    public TesseractTesseractOcrServiceImpl(TessdataExtractor tessdataExtractor) {
        this.tessdataExtractor = tessdataExtractor;
    }

    @Override
    public String recognize(byte[] imageBytes) {
        Tesseract tesseract = new Tesseract();
        // tesseract.setDatapath(
        //     "C:/Users/Administrator/dev/investment-tool/inv-stock/src/main/resources/tessdata");
        tesseract.setDatapath(tessdataExtractor.getTessdataPath());
        tesseract.setLanguage("chi_sim");

        try (var in = new ByteArrayInputStream(imageBytes)) {
            BufferedImage image = ImageIO.read(in);
            String result = tesseract.doOCR(image);
            return result.trim();
        } catch (Exception e) {
            throw new BusinessException(ResultCode.OCR_FAILED);
        }
    }
}