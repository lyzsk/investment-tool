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
public class CrawlUtil {

    /**
     * @param code      code
     * @param startDate startDate
     * @param endDate   endDate
     * @param callback  callback
     * @return java.util.Map<java.lang.String, java.lang.String>
     * @author sichu huang
     * @date 2024/03/11
     **/
    public static Map<String, String> getDailyNavMapBetweenDates(String code, String startDate, String endDate, String callback)
        throws IOException {
        String urlPrefix = "https://fundf10.eastmoney.com/jjjz_";
        String urlSuffix = ".html";
        String host = "api.fund.eastmoney.com";
        String userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
        String referer = urlPrefix + code + urlSuffix;
        int pageIndex = 1;
        int pageSize = 20;
        int totalCount;
        Map<String, String> map = new HashMap<>();
        do {
            String url = "https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery" + callback + "&fundCode=" + code + "&pageIndex=" + pageIndex
                + "&pageSize=" + pageSize + "&startDate=" + startDate + "&endDate=" + endDate + "&_=" + new Date().getTime();
            Connection.Response response =
                Jsoup.connect(url).ignoreContentType(true).header("Host", host).userAgent(userAgent).referrer(referer).execute();
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
}

