package cn.sichu.utils;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.*;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * @author sichu huang
 * @date 2024/03/09
 **/
public class JsonUtil {
    /**
     * @param url url
     * @return org.json.JSONObject
     * @author sichu huang
     * @date 2024/03/09
     **/
    public static JSONObject readJsonFromUrl(String url) throws IOException, JSONException {
        try (InputStream inputStream = new URL(url).openStream()) {
            BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8));
            String jsonText = readAll(reader);
            return new JSONObject(jsonText);
        }
    }

    /**
     * @param reader reader
     * @return java.lang.String
     * @author sichu huang
     * @date 2024/03/09
     **/

    private static String readAll(Reader reader) throws IOException {
        StringBuilder sb = new StringBuilder();
        int cp;
        while ((cp = reader.read()) != -1) {
            sb.append((char)cp);
        }
        return sb.toString();
    }

}
