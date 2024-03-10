package cn.sichu.utils;

import org.json.JSONArray;
import org.json.JSONObject;
import org.jsoup.Connection;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.select.Elements;

import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * @author sichu huang
 * @date 2024/03/10
 **/
public class JsoupUtil {
    private static final String URL_PREFIX = "https://fund.eastmoney.com/";
    private static final String URL_SUFFIX = ".html";

    /**
     * @param code
     * @return java.util.Map<java.lang.String, java.lang.String>
     * @author sichu huang
     * @date 2024/03/10
     **/
    public static Map<String, String> getTransactionDateNavMap(String code) throws IOException {
        String url = URL_PREFIX + code + URL_SUFFIX;
        Document document = Jsoup.connect(url).get();
        Elements elements = document.getElementsByClass("dataItem01");
        String date = "";
        String nav = "";
        for (Element element : elements) {
            Elements span = element.select("span");
            nav = span.get(2).text();
            List<String> list = element.select("p").eachText();
            for (String s : list) {
                String regex = "\\d{4}-\\d{2}-\\d{2}";
                Pattern pattern = Pattern.compile(regex);
                Matcher matcher = pattern.matcher(s);
                if (matcher.find()) {
                    date = matcher.group();
                } else {
                    System.out.println("==========未找到匹配的日期字符串==========");
                }
            }
        }
        Map<String, String> map = new HashMap<>(1);
        map.put(date, nav);
        return map;
    }

    public static void main(String[] args) throws IOException {
        String rootURL = "https://fundf10.eastmoney.com/jjjz_";
        String code = "519191";
        String host = "api.fund.eastmoney.com";
        String userAgent =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
        String referer = rootURL + code + ".html";
        String startDate = "2023-01-01";
        String endDate = "2024-03-08";

        for (int pageIndex = 0; pageIndex < 15; pageIndex++) {
            String url =
                "https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery183023012608503785392_1710072348365&fundCode="
                    + code + "&pageIndex=" + pageIndex + "&pageSize=20&startDate=" + startDate + "&endDate=" + endDate
                    + "&_=1710079537101";

            Connection.Response response =
                Jsoup.connect(url).ignoreContentType(true).header("Host", host).userAgent(userAgent).referrer(referer)
                    .execute();

            Document doc = response.parse();
            String data = doc.body().text();

            int startIndex = data.indexOf("(");
            int endIndex = data.lastIndexOf(")");
            String jsonData = data.substring(startIndex + 1, endIndex);

            JSONObject jsonObject = new JSONObject(jsonData);
            JSONObject dataObject = jsonObject.getJSONObject("Data");
            JSONArray lsjzList = dataObject.getJSONArray("LSJZList");

            Map<String, String> fsrqDwzMap = new HashMap<>();

            for (int i = 0; i < lsjzList.length(); i++) {
                JSONObject item = lsjzList.getJSONObject(i);
                String fsrq = item.getString("FSRQ");
                String dwjz = item.getString("DWJZ");

                fsrqDwzMap.put(fsrq, dwjz);
            }

            System.out.println("Page Index: " + pageIndex);
            for (Map.Entry<String, String> entry : fsrqDwzMap.entrySet()) {
                System.out.println("FSRQ: " + entry.getKey() + ", DWJZ: " + entry.getValue());
            }
        }
    }

    // public static void main(String[] args) throws IOException {
    //     String rootURL = "https://fundf10.eastmoney.com/jjjz_";
    //     String code = "519191";
    //     // Host
    //     String host = "api.fund.eastmoney.com";
    //     // User-Agent
    //     String userAgent =
    //         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
    //     // Referer
    //     String referer = rootURL + code + ".html";
    //     String startDate = "2024-01-01";
    //     String endDate = "2024-03-08";
    //     String pageIndex = "1";
    //     String url =
    //         "https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery183023012608503785392_1710072348365&fundCode="
    //             + code + "&pageIndex=" + pageIndex + "&pageSize=20&startDate=" + startDate + "&endDate=" + endDate
    //             + "&_=1710079537101";
    //
    //     Connection.Response response = Jsoup.connect(url).ignoreContentType(true) // 忽略内容类型
    //         .header("Host", host).userAgent(userAgent).referrer(referer).execute();
    //
    //     Document doc = response.parse();
    //     String data = doc.body().text(); // 获取网页内容
    //
    //     // 去除 jQuery 回调函数部分
    //     int startIndex = data.indexOf("(");
    //     int endIndex = data.lastIndexOf(")");
    //     String jsonData = data.substring(startIndex + 1, endIndex);
    //
    //     // 解析 JSON 数据
    //     JSONObject jsonObject = new JSONObject(jsonData);
    //     JSONObject dataObject = jsonObject.getJSONObject("Data");
    //     JSONArray lsjzList = dataObject.getJSONArray("LSJZList");
    //
    //     // 创建Map来存储FSRQ和DWJZ信息
    //     Map<String, String> fsrqDwzMap = new HashMap<>();
    //
    //     // 遍历LSJZList数组
    //     for (int i = 0; i < lsjzList.length(); i++) {
    //         JSONObject item = lsjzList.getJSONObject(i);
    //         String fsrq = item.getString("FSRQ");
    //         String dwjz = item.getString("DWJZ");
    //
    //         // 将FSRQ和DWJZ信息存储在Map中
    //         fsrqDwzMap.put(fsrq, dwjz);
    //     }
    //
    //     // 输出Map中的信息
    //     for (Map.Entry<String, String> entry : fsrqDwzMap.entrySet()) {
    //         System.out.println("FSRQ: " + entry.getKey() + ", DWJZ: " + entry.getValue());
    //     }
    // }

    // public static void main(String[] args) throws ParseException {
    //     // https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery183023012608503785392_1710072348365&fundCode=519191&pageIndex=1&pageSize=20&startDate=2024-03-01&endDate=2024-03-08&_=1710082147336
    //     // https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery183023012608503785392_1710072348365&fundCode=519191&pageIndex=1&pageSize=20&startDate=2024-03-01&endDate=2024-03-08&_=1710082237069
    //     // https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery183023012608503785392_1710072348365&fundCode=519191&pageIndex=1&pageSize=20&startDate=2024-01-01&endDate=2024-03-08&_=1710082308035
    //     // https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery1830010224943442984413_1710071653695&fundCode=006479&pageIndex=1&pageSize=20&startDate=2024-01-01&endDate=2024-03-08&_=1710082368986
    //     String dateStr = "2024-03-01";
    //     SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
    //     // Date date = sdf.parse(dateStr);
    //     // System.out.println(date.getTime());
    //     Date date = new Date(1710082147336L);
    //     Date date1 = new Date(1710082237069L);
    //     System.out.println(sdf.format(date));
    //     System.out.println(sdf.format(date1));
    // }

    // public static void main(String[] args) throws IOException {
    //     String rootURL = "https://fundf10.eastmoney.com/jjjz_";
    //     String code = "519191";
    //     // Host
    //     String host = "api.fund.eastmoney.com";
    //     // User-Agent
    //     String userAgent =
    //         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
    //     // Referer
    //     String referer = rootURL + code + ".html";
    //
    //     String url =
    //         "https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery183023012608503785392_1710072348365&fundCode="
    //             + code + "&pageIndex=2&pageSize=20&startDate=&endDate=&_=1710079537101";
    //
    //     Connection.Response response = Jsoup.connect(url).ignoreContentType(true) // 忽略内容类型
    //         .header("Host", host).userAgent(userAgent).referrer(referer).execute();
    //
    //     Document doc = response.parse();
    //     String data = doc.body().text(); // 获取网页内容
    //
    //     // 去除 jQuery 回调函数部分
    //     int startIndex = data.indexOf("(");
    //     int endIndex = data.lastIndexOf(")");
    //     String jsonData = data.substring(startIndex + 1, endIndex);
    //
    //     // 解析 JSON 数据
    //     JSONObject jsonObject = new JSONObject(jsonData);
    //     JSONObject dataObject = jsonObject.getJSONObject("Data");
    //     JSONArray lsjzList = dataObject.getJSONArray("LSJZList");
    //
    //     // 创建Map来存储FSRQ和DWJZ信息
    //     Map<String, String> fsrqDwzMap = new HashMap<>();
    //
    //     // 遍历LSJZList数组
    //     for (int i = 0; i < lsjzList.length(); i++) {
    //         JSONObject item = lsjzList.getJSONObject(i);
    //         String fsrq = item.getString("FSRQ");
    //         String dwjz = item.getString("DWJZ");
    //
    //         // 将FSRQ和DWJZ信息存储在Map中
    //         fsrqDwzMap.put(fsrq, dwjz);
    //     }
    //
    //     // 输出Map中的信息
    //     for (Map.Entry<String, String> entry : fsrqDwzMap.entrySet()) {
    //         System.out.println("FSRQ: " + entry.getKey() + ", DWJZ: " + entry.getValue());
    //     }
    // }

}
