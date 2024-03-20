package cn.sichu.utils;

import org.json.JSONArray;
import org.json.JSONObject;
import org.jsoup.Connection;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;

import java.io.IOException;
import java.util.Date;
import java.util.HashMap;
import java.util.Map;

/**
 * @author sichu huang
 * @date 2024/03/10
 **/
public class ScrapingUtil {

    /**
     * 270023: callback=18308729256618897205_1710513360069,
     * <br/>
     * 005698: callback=18308822785109745535_1710513639702,
     * <br/>
     * 001668: callback=18307774775763253026_1710513663724,
     * <br/>
     * 017093: callback=183001005516130397388_1710513689042,
     * <br/>
     * 017091: callback=183017588283309236918_1710513712248,
     * <br/>
     * 006479: callback=18306780763020042986_1710513740884,
     * <br/>
     * 162719: callback=18302674121354348442_1710513764895,
     * <br/>
     * 000043: callback=183046573651802964244_1710513960496,
     * <br/>
     * 160416: callback=1830004536902379467911_1710514024693,
     * <br/>
     * 519185: callback=,
     * <br/>
     * 519191: callback=,
     * <br/>
     * 015283: callback=,
     * <br/>
     * 007356: callback=,
     * <br/>
     * 005125: callback=,
     * <br/>
     * 519005: callback=,
     * <br/>
     * 005125: callback=,
     *
     * @param code
     * @param startDate
     * @param endDate
     * @param callback
     * @return java.util.Map<java.lang.String, java.lang.String>
     * @author sichu huang
     * @date 2024/03/11
     **/
    public static Map<String, String> getDailyNavMapBetweenDates(String code, String startDate, String endDate,
        String callback) throws IOException {
        String urlPrefix = "https://fundf10.eastmoney.com/jjjz_";
        String urlSuffix = ".html";
        String host = "api.fund.eastmoney.com";
        String userAgent =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
        String referer = urlPrefix + code + urlSuffix;
        int pageIndex = 1;
        int pageSize = 20;
        int totalCount;
        Map<String, String> map = new HashMap<>();
        do {
            String url = "https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery" + callback + "&fundCode=" + code
                + "&pageIndex=" + pageIndex + "&pageSize=" + pageSize + "&startDate=" + startDate + "&endDate="
                + endDate + "&_=" + new Date().getTime();
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
            totalCount = jsonObject.getInt("TotalCount");
            for (int i = 0; i < lsjzList.length(); i++) {
                JSONObject item = lsjzList.getJSONObject(i);
                String fsrq = item.getString("FSRQ");
                String dwjz = item.getString("DWJZ");
                map.put(fsrq, dwjz);
            }
            ++pageIndex;
        } while (pageIndex <= Math.ceil((double)totalCount / pageSize));
        return map;
    }

    public static void main(String[] args) throws IOException {
        Map<String, String> map =
            getDailyNavMapBetweenDates("270023", "2024-01-01", "2024-03-11", "18309632015620644496_1710164287417");
        System.err.println(map.entrySet().size());
        for (Map.Entry<String, String> entry : map.entrySet()) {
            System.out.println("FSRQ: " + entry.getKey() + ", DWJZ: " + entry.getValue());
        }
    }
}

