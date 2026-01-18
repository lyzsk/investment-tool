import os
import sys
import json
from paddleocr import PaddleOCR

os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

ocr_engine = PaddleOCR(
    use_angle_cls=True,
    lang="ch",
    drop_score=0.3
)


def ocr_image(img_path: str):
    if not os.path.exists(img_path):
        return {"error": f"Image not found: {img_path}"}

    try:
        # 执行 OCR
        result = ocr_engine.ocr(img_path, cls=True)
        lines = []

        for line in result[0]:
            box = line[0]
            text = line[1][0]
            confidence = float(line[1][1])
            stripped = text.strip()
            if not stripped or all(c in " :：\n\t.,，、" for c in stripped):
                continue
            lines.append({
                "text": stripped,
                "confidence": round(confidence, 3),
                "box": box
            })

        lines.sort(key=lambda x: x["box"][0][1])

        limit_up_stats = parse_limit_up_stats(lines)

        return {
            "limit_up_stats": limit_up_stats,
            "raw_lines": lines
        }

    except Exception as e:
        return {"error": str(e)}


def parse_limit_up_stats(lines):
    data = {}
    key_map = {
        "上涨": "up_count",
        "下跌": "down_count",
        "持平": "flat_count",
        "涨停": "limit_up_count",
        "跌停": "limit_down_count",
        "停牌": "halt_count"
    }

    # 只取最上方的关键词（避免重复匹配）
    keyword_ys = {}
    for line in lines:
        text = line["text"]
        y = line["box"][0][1]
        if any(kw in text for kw in key_map.keys()) and "家" not in text:
            for kw in key_map.keys():
                if kw in text:
                    if kw not in keyword_ys or y < keyword_ys[kw]:
                        keyword_ys[kw] = y

    for kw, target_key in key_map.items():
        if kw in keyword_ys:
            anchor_y = keyword_ys[kw]
            for line in lines:
                y = line["box"][0][1]
                text = line["text"]
                if anchor_y + 5 < y < anchor_y + 30:
                    clean = text.replace("家", "").strip()
                    if clean.isdigit():
                        data[target_key] = clean
                        break

    return data


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Usage: python ocr_zdfb.py <image_path>"}, ensure_ascii=False))
        sys.exit(1)

    image_path = sys.argv[1]
    output = ocr_image(image_path)

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    log_file = os.path.join(os.path.dirname(image_path), f"{base_name}.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ OCR result saved to: {log_file}", file=sys.stderr)