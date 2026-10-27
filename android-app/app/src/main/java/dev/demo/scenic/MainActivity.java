package dev.demo.scenic;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Iterator;

/** Teaching demo: one background thread, hash-verified files and offline manifests. */
public class MainActivity extends Activity {
    // Android emulator host address. Replace with the LAN server for an actual vehicle.
    private static final String BASE = "http://10.0.2.2:8765";
    private TextView view;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        view = new TextView(this);
        view.setTextSize(18);
        view.setPadding(24, 32, 24, 32);
        setContentView(view);
        render("正在自动同步三个景区…");
        new Thread(() -> {
            try { sync(); render("同步完成"); }
            catch (Exception e) { render("网络不可用或下载失败，继续使用已有离线数据：" + e.getMessage()); }
        }, "scenic-sync").start();
    }

    private void render(String status) {
        StringBuilder text = new StringBuilder(status).append("\n\n");
        for (String id : new String[]{"A", "B", "C"}) {
            File active = new File(getFilesDir(), "scenic/" + id + "/active.json");
            if (!active.isFile()) { text.append(id).append("：尚未下载\n"); continue; }
            try {
                JSONObject manifest = new JSONObject(read(active));
                text.append(manifest.getString("scenicName")).append(" v")
                    .append(manifest.getInt("version")).append("\n");
                JSONArray stations = manifest.getJSONArray("stations");
                for (int i = 0; i < stations.length(); i++) {
                    JSONObject s = stations.getJSONObject(i);
                    text.append("  ").append(s.getString("name")).append("\n");
                    JSONArray groups = s.getJSONArray("categories");
                    for (int j = 0; j < groups.length(); j++) {
                        JSONObject group = groups.getJSONObject(j);
                        text.append("    ").append(group.getString("name")).append(": ");
                        JSONArray items = group.getJSONArray("items");
                        for (int k = 0; k < items.length(); k++) {
                            if (k > 0) text.append("、");
                            text.append(items.getJSONObject(k).getString("title"));
                        }
                        text.append("\n");
                    }
                }
                text.append("\n");
            } catch (Exception e) { text.append(id).append("：读取失败\n"); }
        }
        runOnUiThread(() -> view.setText(text.toString()));
    }

    private void sync() throws Exception {
        JSONArray scenics = new JSONArray(fetch(BASE + "/api/scenics"));
        for (int i = 0; i < scenics.length(); i++) {
            String id = scenics.getJSONObject(i).getString("id");
            JSONObject manifest = new JSONObject(fetch(BASE + "/api/scenics/" + id + "/manifest"));
            File scenic = new File(getFilesDir(), "scenic/" + id);
            File files = new File(scenic, "files");
            if (!files.exists() && !files.mkdirs()) throw new IOException("mkdir failed");
            JSONObject all = manifest.getJSONObject("files");
            Iterator<String> keys = all.keys();
            while (keys.hasNext()) {
                JSONObject asset = all.getJSONObject(keys.next());
                String hash = asset.getString("sha256");
                String remote = asset.getString("url");
                File local = new File(files, hash + remote.substring(remote.lastIndexOf('.')));
                if (valid(local, asset)) continue;
                File part = new File(files, local.getName() + ".part");
                download(BASE + remote, part);
                if (!valid(part, asset)) throw new IOException("SHA-256 mismatch");
                if (!part.renameTo(local)) throw new IOException("rename failed");
            }
            File tmp = new File(scenic, "active.json.tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(manifest.toString().getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            if (!tmp.renameTo(new File(scenic, "active.json"))) throw new IOException("activate failed");
            render("已同步景区 " + id);
        }
    }

    private static String fetch(String url) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(30000);
        try (InputStream in = conn.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            copy(in, out);
            return out.toString("UTF-8");
        } finally { conn.disconnect(); }
    }

    private static String read(File file) throws IOException {
        try (InputStream in = new FileInputStream(file); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            copy(in, out);
            return out.toString("UTF-8");
        }
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[65536];
        int size;
        while ((size = in.read(buf)) != -1) out.write(buf, 0, size);
    }

    private static void download(String url, File part) throws IOException {
        long offset = part.isFile() ? part.length() : 0;
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(30000);
        if (offset > 0) conn.setRequestProperty("Range", "bytes=" + offset + "-");
        try {
            int status = conn.getResponseCode();
            String range = conn.getHeaderField("Content-Range");
            boolean resume = offset > 0 && status == 206 && range != null &&
                             range.startsWith("bytes " + offset + "-");
            if (status != 200 && !resume) throw new IOException("HTTP " + status);
            try (InputStream in = conn.getInputStream(); FileOutputStream out = new FileOutputStream(part, resume)) {
                copy(in, out);
                out.getFD().sync();
            }
        } finally { conn.disconnect(); }
    }

    private static boolean valid(File file, JSONObject meta) throws Exception {
        if (!file.isFile() || file.length() != meta.getLong("size")) return false;
        MessageDigest sha = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] buf = new byte[65536]; int n;
            while ((n = in.read(buf)) != -1) sha.update(buf, 0, n);
        }
        StringBuilder hex = new StringBuilder();
        for (byte b : sha.digest()) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return meta.getString("sha256").equals(hex.toString());
    }
}
